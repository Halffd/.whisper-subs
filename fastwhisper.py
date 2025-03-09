import os
import sys
import datetime
import subprocess
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLineEdit, QLabel, 
    QFileDialog, QMessageBox, QTextEdit, QComboBox, QHBoxLayout, QCheckBox, QRadioButton, QGroupBox, QGridLayout
)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from PyQt5 import QtGui, QtCore
import pymkv
import transcribe
import time
from youtubesubs import YoutubeSubs
import pyperclip

# Setup Qt message handler to suppress propagateSizeHints warning
def qt_message_handler(mode, context, message):
    if mode == QtCore.QtWarningMsg and 'propagateSizeHints' in message:
        return
    if mode == QtCore.QtInfoMsg:
        mode = 'INFO'
    elif mode == QtCore.QtWarningMsg:
        mode = 'WARNING'
    elif mode == QtCore.QtCriticalMsg:
        mode = 'CRITICAL'
    elif mode == QtCore.QtFatalMsg:
        mode = 'FATAL'
    else:
        mode = 'DEBUG'
    print('qt_message_handler: line: %d, func: %s(), file: %s' % (
          context.line, context.function, context.file))
    print('  %s: %s\n' % (mode, message))

QtCore.qInstallMessageHandler(qt_message_handler)

# Set High DPI handling before creating QApplication
if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
if hasattr(QtCore.Qt, 'AA_ShareOpenGLContexts'):
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)

# Set environment variables for better HiDPI support
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_SCALE_FACTOR"] = "1"

# Debug output for Qt
#os.environ['QT_DEBUG_PLUGINS'] = '1'

MODEL_NAMES = [
    "distil-whisper/distil-large-v2",  # Distilled version of large-v2
    "distil-whisper/distil-medium.en",  # English-only models
    "Systran/faster-distil-large-v2",  # Optimized for CPU
    "small", "medium",  # Original Whisper models
    "large-v2", "large-v3"  # For CPU-only use
]

class TranscriptionThread(QThread):
    finished = pyqtSignal()
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, files_to_process, model_name, log_callback, youtube_urls=None):
        super().__init__()
        self.files_to_process = files_to_process
        self.model_name = model_name
        self.log_callback = log_callback
        self.youtube_urls = youtube_urls
        
        # Get UI settings from the main window
        main_window = QApplication.activeWindow()
        if main_window:
            self.device = 'cuda' if main_window.gpu_radio.isChecked() else 'cpu'
            self.compute_type = main_window.compute_combo.currentText().split(' ')[0]
            self.force_device = main_window.force_device_check.isChecked()
            
            # Get language selection
            selected_lang = main_window.lang_combo.currentText()
            self.force_lang = None if selected_lang == "Automatic" else selected_lang.split('(')[-1].strip(')')
            
            # Get VAD settings
            self.vad_enabled = main_window.vad_enabled.isChecked()
            try:
                self.vad_silence_duration = int(main_window.vad_silence_duration.text() or "500")
            except ValueError:
                self.vad_silence_duration = 500
            
            # Get diarization settings
            self.diarization_enabled = main_window.diarization_enabled.isChecked()
            try:
                self.min_speakers = int(main_window.min_speakers.text() or "1")
                self.max_speakers = int(main_window.max_speakers.text() or "2")
            except ValueError:
                self.min_speakers = 1
                self.max_speakers = 2
        else:
            # Default values if window not found
            self.device = 'cuda'
            self.compute_type = 'int8'
            self.force_device = False
            self.force_lang = None
            self.vad_enabled = True
            self.vad_silence_duration = 500
            self.diarization_enabled = False
            self.min_speakers = 1
            self.max_speakers = 2
        
        # Setup WebSocket
        import socketio
        self.sio = socketio.Client()
        self.sio.on('progress', self.handle_progress)
        try:
            self.sio.connect('http://localhost:5000')
        except Exception as e:
            self.error.emit(f"Could not connect to transcription service: {str(e)}")

    def handle_progress(self, data):
        """Handle progress updates from WebSocket"""
        if 'message' in data:
            self.progress.emit(data['message'])

    def run(self):
        try:
            # Process YouTube URLs if any
            if self.youtube_urls:
                urls = self.youtube_urls.strip().split('\n')
                for url in urls:
                    self.process_url(url.strip())
                
            # Process local files if any
            for i, file_path in enumerate(self.files_to_process, 1):
                self.progress.emit(f"Processing file {i}/{len(self.files_to_process)}: {file_path}")
                
                if file_path.lower().endswith('.mkv'):
                    file_path = self.convertMKVtoMP3(file_path)
                    if not file_path:
                        self.progress.emit(f"Failed to convert {file_path}")
                        continue
                    
                if file_path:
                    self.process_local_file(file_path)
            
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                self.sio.disconnect()
            except:
                pass

    def process_local_file(self, file_path):
        """Process a local file using the transcribe module with multi-language support"""
        try:
            # Create output srt file path
            dir_path = os.path.dirname(file_path)
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            srt_file = os.path.join(dir_path, f"{base_name}.{self.model_name}.srt")
            temp_srt = os.path.join(dir_path, f"{base_name}.{self.model_name}.temp.srt")
            
            # Get VAD and diarization settings
            vad_params = None
            if self.vad_enabled:
                vad_params = dict(min_silence_duration_ms=self.vad_silence_duration)

            diarization_params = None
            if self.diarization_enabled:
                diarization_params = dict(min_speakers=self.min_speakers, max_speakers=self.max_speakers)
            
            # Use transcribe module with proper settings
            success = transcribe.process_create(
                file=file_path,
                model_name=self.model_name,
                srt_file=srt_file,
                language=self.force_lang,  # Use the language from UI selection
                device=self.device,
                compute_type=self.compute_type,
                force_device=self.force_device,
                write=lambda msg: self.progress.emit(str(msg))
            )
            
            if success:
                self.progress.emit(f"Successfully transcribed {file_path}")
            else:
                self.error.emit(f"Failed to transcribe {file_path}")
            
        except Exception as e:
            self.error.emit(f"Error processing {file_path}: {str(e)}")
            if os.path.exists(temp_srt):
                try:
                    os.remove(temp_srt)
                except:
                    pass

    def format_timestamp(self, seconds):
        """Convert seconds to SRT timestamp format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds % 1) * 1000)
        seconds = int(seconds)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    def process_url(self, url):
        """Process a YouTube URL using YoutubeSubs"""
        try:
            yt = YoutubeSubs(
                model_name=self.model_name,
                device=self.device,
                compute=self.compute_type,
                force_device=self.force_device
            )
            
            # Process the URL
            yt.process_single_url(url, callback=lambda msg: self.progress.emit(str(msg)))
            
        except Exception as e:
            self.error.emit(f"Error processing {url}: {str(e)}")

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

class TranscriptionApp(QWidget):
    def __init__(self):
        super().__init__()
        self.log_file = None
        self.selected_files = []
        self.selected_directory = None
        self.youtube_subs = None
        self.last_clipboard = ""
        self.clipboard_monitoring = True
        self.force_device = False
        
        # Set window to maximize on primary monitor
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        self.setGeometry(screen_geometry)
        self.setWindowState(QtCore.Qt.WindowMaximized)
        
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
        
        # Model and language selection
        model_lang_layout = QHBoxLayout()
        
        # Model selection
        model_layout = QVBoxLayout()
        model_label = QLabel("Model:")
        self.model_combo = QComboBox()
        self.model_combo.addItems(MODEL_NAMES)
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_combo)
        model_lang_layout.addLayout(model_layout)
        
        # Language selection
        lang_layout = QVBoxLayout()
        lang_label = QLabel("Language:")
        self.lang_combo = QComboBox()
        # Add common languages and automatic option
        languages = [
            "Automatic",
            "English (en)", "Japanese (ja)", "Chinese (zh)", "Korean (ko)",
            "Spanish (es)", "French (fr)", "German (de)", "Italian (it)",
            "Russian (ru)", "Portuguese (pt)", "Dutch (nl)", "Polish (pl)",
            "Turkish (tr)", "Arabic (ar)", "Hindi (hi)", "Vietnamese (vi)"
        ]
        self.lang_combo.addItems(languages)
        self.lang_combo.setCurrentText("Automatic")  # Set default
        lang_layout.addWidget(lang_label)
        lang_layout.addWidget(self.lang_combo)
        model_lang_layout.addLayout(lang_layout)
        
        options_right.addLayout(model_lang_layout)
        
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

        # Device selection
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
            "float16 (GPU Only)",
            "float32 (High Accuracy)"
        ])
        compute_layout.addWidget(self.compute_combo)
        device_group.addLayout(compute_layout)

        # Add VAD and diarization options
        vad_diar_layout = QVBoxLayout()
        
        # VAD options group
        vad_group = QGroupBox("Voice Activity Detection (VAD)")
        vad_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #5E81AC;
                margin-top: 0.5em;
                padding-top: 0.5em;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
        """)
        vad_layout = QVBoxLayout()
        
        # VAD filter checkbox
        self.vad_enabled = QCheckBox("Enable VAD Filter")
        self.vad_enabled.setChecked(True)
        vad_layout.addWidget(self.vad_enabled)
        
        # VAD parameters
        vad_params = QHBoxLayout()
        vad_params.addWidget(QLabel("Min Silence Duration (ms):"))
        self.vad_silence_duration = QLineEdit()
        self.vad_silence_duration.setPlaceholderText("500")
        self.vad_silence_duration.setText("500")
        vad_params.addWidget(self.vad_silence_duration)
        vad_layout.addLayout(vad_params)
        
        vad_group.setLayout(vad_layout)
        vad_diar_layout.addWidget(vad_group)
        
        # Diarization options group
        diar_group = QGroupBox("Speaker Diarization")
        diar_group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #5E81AC;
                margin-top: 0.5em;
                padding-top: 0.5em;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
        """)
        diar_layout = QVBoxLayout()
        
        # Diarization checkbox
        self.diarization_enabled = QCheckBox("Enable Speaker Diarization")
        self.diarization_enabled.setChecked(False)
        diar_layout.addWidget(self.diarization_enabled)
        
        # Diarization parameters
        diar_params = QGridLayout()
        
        # Min/max speakers
        diar_params.addWidget(QLabel("Min Speakers:"), 0, 0)
        self.min_speakers = QLineEdit()
        self.min_speakers.setPlaceholderText("1")
        self.min_speakers.setText("1")
        diar_params.addWidget(self.min_speakers, 0, 1)
        
        diar_params.addWidget(QLabel("Max Speakers:"), 0, 2)
        self.max_speakers = QLineEdit()
        self.max_speakers.setPlaceholderText("2")
        self.max_speakers.setText("2")
        diar_params.addWidget(self.max_speakers, 0, 3)
        
        diar_layout.addLayout(diar_params)
        diar_group.setLayout(diar_layout)
        vad_diar_layout.addWidget(diar_group)
        
        device_group.addLayout(vad_diar_layout)
        layout.addLayout(device_group)

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

        # Process local files first
        files_to_process = []
        seen_base_names = set()  # Track files by their base name without extension

        # Helper function to add file with priority
        def add_file_with_priority(file_path):
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            if base_name in seen_base_names:
                return False
            
            # Check if we should add this file
            is_audio = file_path.lower().endswith(('.mp3', '.wav', '.flac', '.ogg'))
            is_mkv = file_path.lower().endswith('.mkv')
            
            # Get all possible related files
            dir_path = os.path.dirname(file_path)
            related_files = []
            for ext in ['.mp3', '.wav', '.flac', '.ogg', '.mkv']:
                related_path = os.path.join(dir_path, base_name + ext)
                if os.path.exists(related_path):
                    related_files.append(related_path)
            
            # If we have both audio and mkv files, prefer audio
            if related_files:
                has_audio = any(f.lower().endswith(('.mp3', '.wav', '.flac', '.ogg')) for f in related_files)
                if has_audio:
                    # Only add if this is the first audio file we've found
                    if is_audio and file_path == min(f for f in related_files if f.lower().endswith(('.mp3', '.wav', '.flac', '.ogg'))):
                        seen_base_names.add(base_name)
                        files_to_process.append(file_path)
                        return True
                    return False
                elif is_mkv:
                    # No audio exists, add the mkv
                    seen_base_names.add(base_name)
                    files_to_process.append(file_path)
                    return True
            else:
                # No related files exist, add this one
                seen_base_names.add(base_name)
                files_to_process.append(file_path)
                return True
            return False

        # Collect all potential files first
        all_files = []
        if self.selected_files:
            all_files.extend(self.selected_files)

        if self.selected_directory:
            for f in os.listdir(self.selected_directory):
                if f.lower().endswith(('.mkv', '.mp3', '.wav', '.flac', '.ogg')):
                    all_files.append(os.path.join(self.selected_directory, f))

        # Sort all files alphabetically first
        all_files.sort(key=lambda x: os.path.basename(x).lower())

        # Process files in alphabetical order, applying priority rules
        for file_path in all_files:
            add_file_with_priority(file_path)

        # Get YouTube URLs if any
        youtube_urls = self.youtube_input.toPlainText().strip()

        # No inputs case
        if not files_to_process and not youtube_urls:
            QMessageBox.warning(self, "Error", "No files, directory, or YouTube URLs selected.")
            return

        # Disable run button during processing
        self.run_button.setEnabled(False)
        self.log_output.clear()

        # Create thread for processing both files and URLs
        self.transcription_thread = TranscriptionThread(
            files_to_process=files_to_process,
            model_name=model_name,
            log_callback=self.log,
            youtube_urls=youtube_urls if youtube_urls else None
        )
        
        self.transcription_thread.progress.connect(self.log)
        self.transcription_thread.finished.connect(self.on_transcription_finished)
        self.transcription_thread.error.connect(self.on_transcription_error)
        self.transcription_thread.start(QThread.LowPriority)

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
    
    # Set font DPI
    font = app.font()
    font.setPointSize(10)  # Adjust base font size
    app.setFont(font)
    
    window = TranscriptionApp()
    window.show()  # Use show() instead of exec_() for better compatibility
    sys.exit(app.exec_())
