import os
import sys
import datetime
import subprocess
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLineEdit, QLabel, 
    QFileDialog, QMessageBox, QTextEdit, QComboBox, QHBoxLayout, QCheckBox, QRadioButton
)
import pymkv
import transcribe
from PyQt5.QtCore import QThread, pyqtSignal, QTimer
import time
from youtubesubs import YoutubeSubs
import pyperclip

MODEL_NAMES = [
    "distil-whisper/distil-large-v2",  # Distilled version of large-v2
    "distil-whisper/distil-medium.en",  # English-only medium model
    "Systran/faster-distil-large-v2",  # Optimized for CPU
    "small", "medium",  # Original Whisper models
    "large-v2", "large-v3"  # For CPU-only use
]

class TranscriptionThread(QThread):
    finished = pyqtSignal()
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, files_to_process, model_name, log_callback, youtube_urls=None, youtube_subs=None):
        super().__init__()
        self.files_to_process = files_to_process
        self.model_name = model_name
        self.log_callback = log_callback
        self.youtube_urls = youtube_urls
        self.youtube_subs = youtube_subs

    def run(self):
        try:
            # Process YouTube URLs if any
            if self.youtube_urls and self.youtube_subs:
                self.youtube_subs.process_urls(self.youtube_urls, self.progress.emit)
                
            # Process local files if any
            for i, file_path in enumerate(self.files_to_process, 1):
                self.progress.emit(f"Processing file {i}/{len(self.files_to_process)}: {file_path}")
                
                if file_path.lower().endswith('.mkv'):
                    file_path = self.convertMKVtoMP3(file_path)
                    if not file_path:
                        self.progress.emit(f"Failed to convert {file_path}")
                        continue
                    
                if file_path:
                    self.processFile(file_path, self.model_name)
            
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def convertMKVtoMP3(self, mkv_path):
        output_mp3 = os.path.splitext(mkv_path)[0] + ".mp3"
        try:
            mkv = pymkv.MKVFile(mkv_path)
            
            # Try to find Japanese audio track first, then undefined, then any audio track
            audio_track_id = next(
                (track.track_id for track in mkv.tracks 
                 if track.track_type == 'audio' and track.language in ['jpn', 'und']),
                next(
                    (track.track_id for track in mkv.tracks if track.track_type == 'audio'),
                    None
                )
            )

            if audio_track_id is None:
                raise ValueError("No audio tracks found")

            command = [
                "ffmpeg", "-y", "-i", mkv_path,
                "-map", f"0:{audio_track_id}",
                "-c:a", "libmp3lame",
                output_mp3
            ]
            
            subprocess.run(command, check=True)
            self.progress.emit(f"Converted {mkv_path} to {output_mp3}")
            return output_mp3
            
        except Exception as e:
            self.progress.emit(f"Error converting {mkv_path}: {str(e)}")
            return None

    def processFile(self, file_path, model_name):
        try:
            srt_file = os.path.splitext(file_path)[0] + f".{model_name}.srt"
            self.progress.emit(f"Processing {file_path} with model {model_name}...")
            
            # Create a temporary Python script instead of using -c
            script_content = f'''
import faster_whisper
import os

def format_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds % 1) * 1000)
    seconds = int(seconds)
    return f"{{hours:02d}}:{{minutes:02d}}:{{seconds:02d}},{{milliseconds:03d}}"

model = faster_whisper.WhisperModel("{model_name}", device="cpu", compute_type="int8")
file_path = r"{file_path}"
srt_file = r"{srt_file}"

try:
    segments, _ = model.transcribe(file_path, language=None)
    with open(srt_file, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, 1):
            # Format timestamps as HH:MM:SS,mmm
            start_time = format_timestamp(segment.start)
            end_time = format_timestamp(segment.end)
            
            f.write(f"{{i}}\\n")
            f.write(f"{{start_time}} --> {{end_time}}\\n")
            f.write(f"{{segment.text.strip()}}\\n\\n")
except Exception as e:
    print(f"Error during transcription: {{e}}")
    exit(1)
'''
            
            # Write the script to a temporary file
            script_file = os.path.join(os.path.dirname(file_path), "temp_whisper_script.py")
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(script_content)
            
            # Run the script
            args = [sys.executable, script_file]
            self.progress.emit(f"Running transcription script...")
            
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace',
                text=True
            )

            # Monitor process and check for successful completion
            while process.poll() is None:
                stdout = process.stdout.readline()
                if stdout:
                    self.progress.emit(f"Out: {stdout.strip()}")
                stderr = process.stderr.readline()
                if stderr:
                    self.progress.emit(f"Error: {stderr.strip()}")
                time.sleep(0.1)
            
            # Clean up the temporary script
            try:
                os.remove(script_file)
            except:
                pass
            
            exit_code = process.returncode
            if exit_code == 0 or os.path.exists(srt_file):
                self.progress.emit(f"Successfully created {srt_file}")
                return True
            
            self.progress.emit(f"Process exited with code {exit_code}")
            return False
            
        except Exception as e:
            self.progress.emit(f"Error processing {file_path}: {str(e)}")
            return False

class TranscriptionApp(QWidget):
    def __init__(self):
        super().__init__()
        self.log_file = None
        self.selected_files = []
        self.selected_directory = None
        self.youtube_subs = None
        self.last_clipboard = ""
        self.clipboard_monitoring = True
        self.force_device = False  # Don't auto-switch device
        self.initUI()
        
        # Setup clipboard monitoring
        self.clipboard_timer = QTimer()
        self.clipboard_timer.timeout.connect(self.check_clipboard)
        self.clipboard_timer.start(1000)  # Check every second

    def initUI(self):
        # Apply dark theme
        self.setStyleSheet("""
            QWidget {
                background-color: #2E3440;
                color: #D8DEE9;
            }
            QPushButton {
                background-color: #4C566A;
                color: #ECEFF4;
                border: 1px solid #5E81AC;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #5E81AC;
            }
            QComboBox {
                background-color: #4C566A;
                color: #ECEFF4;
                border: 1px solid #5E81AC;
                padding: 5px;
            }
            QTextEdit {
                background-color: #3B4252;
                color: #ECEFF4;
                border: 1px solid #5E81AC;
            }
            QLabel {
                color: #ECEFF4;
            }
            QMessageBox {
                background-color: #2E3440;
                color: #D8DEE9;
            }
        """)

        layout = QVBoxLayout()

        # Add clipboard monitoring and options
        clipboard_layout = QHBoxLayout()
        
        # Left side - clipboard controls
        clipboard_left = QVBoxLayout()
        self.clipboard_toggle = QPushButton('Clipboard Monitoring: ON', self)
        self.clipboard_toggle.setCheckable(True)
        self.clipboard_toggle.setChecked(True)
        self.clipboard_toggle.clicked.connect(self.toggle_clipboard_monitoring)
        clipboard_left.addWidget(self.clipboard_toggle)
        
        self.clear_urls_button = QPushButton('Clear URLs', self)
        self.clear_urls_button.clicked.connect(self.clear_youtube_urls)
        clipboard_left.addWidget(self.clear_urls_button)
        clipboard_layout.addLayout(clipboard_left)
        
        # Right side - options
        options_right = QVBoxLayout()
        
        # Sort and order options
        sort_layout = QHBoxLayout()
        
        # Sort by oldest checkbox
        sort_group = QVBoxLayout()
        self.sort_oldest_check = QCheckBox('Sort by Oldest', self)
        self.sort_oldest_check.stateChanged.connect(self.resort_urls)
        sort_group.addWidget(self.sort_oldest_check)
        
        # Reverse order checkbox
        self.reverse_order_check = QCheckBox('Reverse Order', self)
        self.reverse_order_check.stateChanged.connect(self.resort_urls)
        sort_group.addWidget(self.reverse_order_check)
        
        sort_layout.addLayout(sort_group)
        options_right.addLayout(sort_layout)
        
        # Time range
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("Start Time:"))
        self.start_time = QLineEdit(self)
        self.start_time.setPlaceholderText("HH:MM:SS")
        time_layout.addWidget(self.start_time)
        
        time_layout.addWidget(QLabel("End Time:"))
        self.end_time = QLineEdit(self)
        self.end_time.setPlaceholderText("HH:MM:SS")
        time_layout.addWidget(self.end_time)
        options_right.addLayout(time_layout)
        
        # Logging checkbox
        self.enable_logging_check = QCheckBox('Enable File Logging', self)
        self.enable_logging_check.setChecked(True)
        options_right.addWidget(self.enable_logging_check)
        
        clipboard_layout.addLayout(options_right)
        layout.addLayout(clipboard_layout)

        # Device and compute settings group
        device_group = QHBoxLayout()
        
        # Device selection
        device_layout = QVBoxLayout()
        device_label = QLabel("Processing Device:")
        device_layout.addWidget(device_label)
        
        device_controls = QHBoxLayout()
        self.gpu_radio = QRadioButton("GPU (CUDA)")
        self.cpu_radio = QRadioButton("CPU")
        self.gpu_radio.setChecked(True)  # Default to GPU
        device_controls.addWidget(self.gpu_radio)
        device_controls.addWidget(self.cpu_radio)
        device_layout.addLayout(device_controls)
        
        # Force device checkbox
        self.force_device_check = QCheckBox("Force Device (Don't Auto-Switch)")
        device_layout.addWidget(self.force_device_check)
        
        device_group.addLayout(device_layout)
        
        # Compute type selection
        compute_layout = QVBoxLayout()
        compute_layout.addWidget(QLabel("Compute Type:"))
        self.compute_combo = QComboBox()
        self.compute_combo.addItems([
            "int8_float32 (Balanced)",
            "int8 (Fast/Low Memory)",
            "float32 (High Accuracy)",
            "float16 (GPU Only)"
        ])
        compute_layout.addWidget(self.compute_combo)
        device_group.addLayout(compute_layout)
        
        layout.addLayout(device_group)

        # Model selection dropdown
        self.model_combo = QComboBox(self)
        
        # Add smaller models first as default options
        default_models = [
            "tiny", "base", "small", 
            "tiny.en", "base.en", "small.en", "medium.en"
            "distil-whisper/distil-small.en",
            "distil-whisper/distil-base"
        ]
        
        # Add all models after the default options
        self.model_combo.addItems(default_models)
        self.model_combo.addItems([model for model in MODEL_NAMES if model not in default_models])
        
        self.model_combo.setCurrentText("small")  # Set default model
        layout.addWidget(QLabel("Select Model:"))
        layout.addWidget(self.model_combo)

        # Add YouTube URL input with label showing URL count
        layout.addWidget(QLabel("YouTube URLs (one per line):"))
        self.url_count_label = QLabel("0 URLs")
        layout.addWidget(self.url_count_label)
        self.youtube_input = QTextEdit(self)
        self.youtube_input.setPlaceholderText("Paste YouTube video/channel URLs here...")
        self.youtube_input.setMinimumHeight(100)
        self.youtube_input.textChanged.connect(self.update_url_count)
        layout.addWidget(self.youtube_input)

        # File selection section
        self.file_button = QPushButton('Select Audio Files', self)
        self.file_button.clicked.connect(self.selectFiles)
        layout.addWidget(self.file_button)
        
        self.file_label = QLabel("Selected files: None", self)
        layout.addWidget(self.file_label)

        # Directory selection section
        self.dir_button = QPushButton('Select Directory', self)
        self.dir_button.clicked.connect(self.selectDirectory)
        layout.addWidget(self.dir_button)
        
        self.dir_label = QLabel("Selected directory: None", self)
        layout.addWidget(self.dir_label)

        # Run button
        self.run_button = QPushButton('Run Transcription', self)
        self.run_button.clicked.connect(self.runTranscription)
        layout.addWidget(self.run_button)

        # Log output
        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        layout.addWidget(QLabel("Log Output:"))
        layout.addWidget(self.log_output)

        self.setLayout(layout)
        self.setWindowTitle('Transcription App')
        self.setGeometry(100, 100, 800, 600)

    def selectFiles(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files",
            "",
            "Media Files (*.mkv *.mp3 *.wav *.flac *.ogg)"
        )
        
        if files:
            # Sort files naturally (e.g., "Episode 1" before "Episode 10")
            try:
                from natsort import natsorted  # For natural sorting
                self.selected_files = natsorted(files, key=lambda x: x.lower())
            except ImportError:
                # Fallback to alphabetical sorting if natsort isn't available
                self.selected_files = sorted(files, key=lambda x: x.lower())
            
            self.file_label.setText(f"Selected files: {len(self.selected_files)} files")
            
            if not self.log_file:
                self.log_file = os.path.splitext(self.selected_files[0])[0] + '.log'
    def selectDirectory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.selected_directory = directory
            self.dir_label.setText(f"Selected directory: {directory}")
            if not self.log_file:
                self.log_file = os.path.join(directory, 'transcription.log')

    def log(self, text, mpv='err'):
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_text = f"[{timestamp}] {text}"
        self.log_output.append(log_text)
        
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding="utf-8") as f:
                    f.write(log_text + '\n')
                    if mpv != 'err':
                        f.write(f"[{timestamp}] {mpv}\n")
            except Exception as e:
                self.log_output.append(f"Error writing to log file: {str(e)}")

    def runTranscription(self):
        model_name = self.model_combo.currentText()
        
        # Get device settings
        device = 'cuda' if self.gpu_radio.isChecked() else 'cpu'
        force_device = self.force_device_check.isChecked()
        
        # Get compute type (strip description)
        compute = self.compute_combo.currentText().split(' ')[0]
        
        # Get time range if specified
        start_time = self.start_time.text().strip() or None
        end_time = self.end_time.text().strip() or None
        
        # Initialize YouTube handler if needed
        if self.youtube_subs is None:
            self.youtube_subs = YoutubeSubs(
                model_name=model_name,
                device=device,
                compute=compute,
                force_device=force_device,
                subs_dir="Youtube-Subs",
                enable_logging=self.enable_logging_check.isChecked()
            )
        else:
            self.youtube_subs.enable_logging = self.enable_logging_check.isChecked()
            self.youtube_subs.device = device
            self.youtube_subs.compute = compute
            self.youtube_subs.force_device = force_device
            
        # Update time range
        self.youtube_subs.start_time = start_time
        self.youtube_subs.end_time = end_time

        # Process YouTube URLs if any
        youtube_urls = self.youtube_input.toPlainText().strip()
        if youtube_urls:
            self.run_button.setEnabled(False)
            
            # Create a QThread for YouTube processing
            self.transcription_thread = TranscriptionThread(
                files_to_process=[],
                model_name=model_name,
                log_callback=self.log,
                youtube_urls=youtube_urls,
                youtube_subs=self.youtube_subs
            )
            
            # Connect signals
            self.transcription_thread.progress.connect(self.log)
            self.transcription_thread.finished.connect(self.on_transcription_finished)
            self.transcription_thread.error.connect(self.on_transcription_error)
            
            # Start in low priority to prevent system freezing
            self.transcription_thread.start(QThread.LowPriority)
            return

        # Process local files if any
        files_to_process = self.selected_files.copy()
        if self.selected_directory:
            files_to_process.extend([
                os.path.join(self.selected_directory, f)
                for f in os.listdir(self.selected_directory)
                if f.lower().endswith(('.mkv', '.mp3', '.wav', '.flac', '.ogg'))
            ])

        if not files_to_process:
            QMessageBox.warning(self, "Error", "No files, directory, or YouTube URLs selected.")
            return

        # Disable run button during processing
        self.run_button.setEnabled(False)
        self.log_output.clear()

        # Create and start the thread
        self.transcription_thread = TranscriptionThread(
            files_to_process, 
            model_name,
            self.log
        )
        self.transcription_thread.progress.connect(self.log)
        self.transcription_thread.finished.connect(self.on_transcription_finished)
        self.transcription_thread.error.connect(self.on_transcription_error)
        self.transcription_thread.start()

    def on_transcription_finished(self):
        self.log("Transcription process completed!")
        self.run_button.setEnabled(True)

    def on_transcription_error(self, error_message):
        self.log(f"Error during transcription: {error_message}")
        self.run_button.setEnabled(True)

    def toggle_clipboard_monitoring(self):
        """Toggle clipboard monitoring on/off"""
        self.clipboard_monitoring = not self.clipboard_monitoring
        self.clipboard_toggle.setText(
            f'Clipboard Monitoring: {"ON" if self.clipboard_monitoring else "OFF"}'
        )
        if self.clipboard_monitoring:
            self.clipboard_timer.start()
        else:
            self.clipboard_timer.stop()

    def check_clipboard(self):
        """Check clipboard for YouTube URLs"""
        if not self.clipboard_monitoring:
            return
            
        try:
            current_clipboard = pyperclip.paste()
            if current_clipboard == self.last_clipboard:
                return
                
            self.last_clipboard = current_clipboard
            
            # Check for YouTube URLs
            urls = current_clipboard.split('\n')
            youtube_urls = []
            
            for url in urls:
                url = url.strip()
                if 'youtu' in url.lower():
                    youtube_urls.append(url)
            
            if youtube_urls:
                self.add_new_urls(youtube_urls)
                
        except Exception as e:
            self.log(f"Error checking clipboard: {str(e)}")

    def add_new_urls(self, new_urls):
        """Add new URLs if they don't already exist"""
        current_urls = set(self.youtube_input.toPlainText().split('\n'))
        current_urls.discard('')  # Remove empty lines
        
        added = False
        for url in new_urls:
            if url not in current_urls:
                current_urls.add(url)
                added = True
        
        if added:
            self.youtube_input.setPlainText('\n'.join(sorted(current_urls)))
            self.log(f"Added {len(new_urls)} new YouTube URL(s) from clipboard")

    def clear_youtube_urls(self):
        """Clear all YouTube URLs from the input"""
        self.youtube_input.clear()
        self.update_url_count()

    def update_url_count(self):
        """Update the URL count label"""
        urls = [url for url in self.youtube_input.toPlainText().split('\n') if url.strip()]
        self.url_count_label.setText(f"{len(urls)} URLs")

    def resort_urls(self):
        """Resort URLs based on current sort settings"""
        urls = [url for url in self.youtube_input.toPlainText().split('\n') if url.strip()]
        if not urls:
            return
            
        # Sort by oldest if enabled
        if self.sort_oldest_check.isChecked():
            if self.youtube_subs is None:
                self.youtube_subs = YoutubeSubs(
                    model_name=self.model_combo.currentText(),
                    device='cuda'
                )
            urls = self.youtube_subs.sort_by_date(urls)
            
        # Reverse if enabled
        if self.reverse_order_check.isChecked():
            urls.reverse()
            
        self.youtube_input.setPlainText('\n'.join(urls))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TranscriptionApp()
    window.show()
    sys.exit(app.exec_())
