import os
import sys
import datetime
import subprocess
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLineEdit, QLabel, 
    QFileDialog, QMessageBox, QTextEdit, QComboBox
)
import pymkv
import transcribe
from PyQt5.QtCore import QThread, pyqtSignal
import time

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

    def __init__(self, files_to_process, model_name, log_callback):
        super().__init__()
        self.files_to_process = files_to_process
        self.model_name = model_name
        self.log_callback = log_callback

    def run(self):
        try:
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
        self.initUI()

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

        # Model selection dropdown
        self.model_combo = QComboBox(self)
        
        # Add smaller models first as default options
        default_models = [
            "tiny", "base", "small", 
            "tiny.en", "base.en", "small.en",
            "distil-whisper/distil-small.en",
            "distil-whisper/distil-base"
        ]
        
        # Add all models after the default options
        self.model_combo.addItems(default_models)
        self.model_combo.addItems([model for model in MODEL_NAMES if model not in default_models])
        
        self.model_combo.setCurrentText("small")  # Set default model
        layout.addWidget(QLabel("Select Model:"))
        layout.addWidget(self.model_combo)

        # File selection section
        self.file_button = QPushButton('Select Files', self)
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
        self.setGeometry(100, 100, 600, 500)

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
        files_to_process = self.selected_files.copy()

        if self.selected_directory:
            files_to_process.extend([
                os.path.join(self.selected_directory, f)
                for f in os.listdir(self.selected_directory)
                if f.lower().endswith(('.mkv', '.mp3', '.wav', '.flac', '.ogg'))
            ])

        if not files_to_process:
            QMessageBox.warning(self, "Error", "No files or directory selected for transcription.")
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TranscriptionApp()
    window.show()
    sys.exit(app.exec_())
