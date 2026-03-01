import os
import sys
import datetime
import subprocess
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLineEdit, QLabel,
    QFileDialog, QMessageBox, QTextEdit, QComboBox, QHBoxLayout, QCheckBox, QRadioButton, QGroupBox, QGridLayout,
    QSystemTrayIcon, QMenu, QAction, QListWidget, QAbstractItemView
)
from PyQt5.QtCore import QThread, pyqtSignal, QTimer
from PyQt5 import QtGui, QtCore
import pymkv
import transcribe
import time
from whisper_subs import WhisperSubs
import pyperclip
import json

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

    def __init__(self, files_to_process, model_name, log_callback, youtube_urls=None, use_cookies=False, browser=None, cookie_file=None):
        super().__init__()
        self.files_to_process = files_to_process
        self.model_name = model_name
        self.log_callback = log_callback
        self.youtube_urls = youtube_urls
        self.use_cookies = use_cookies
        self.browser = browser
        self.cookie_file = cookie_file
        
        # Get UI settings from the main window
        main_window = QApplication.activeWindow()
        if main_window:
            self.device = 'cuda' if main_window.gpu_radio.isChecked() else 'cpu'
            self.compute_type = main_window.compute_combo.currentText().split(' ')[0]
            self.force_device = main_window.force_device_check.isChecked()
            self.use_faster_whisper = main_window.faster_whisper_radio.isChecked()
            
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

            # Get thread count setting
            thread_text = main_window.thread_combo.currentText()
            if thread_text == "Auto (All Cores)":
                self.cpu_threads = None  # Will use os.cpu_count()
            else:
                self.cpu_threads = int(thread_text.split()[0])

            # Get process priority setting
            priority_text = main_window.priority_combo.currentText()
            self.process_priority = priority_text.split()[0]  # Get first word (e.g., "Normal", "Low")

            # Get advanced transcription settings
            self.temperature = float(main_window.temperature_spinbox.currentText())
            self.merge_lines = main_window.merge_lines_check.isChecked()

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
            self.use_faster_whisper = False
            self.cpu_threads = None
            self.process_priority = "Normal"
            self.temperature = 0.3
            self.merge_lines = False
        
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
            # Set process priority
            self.set_process_priority(self.process_priority)

            # Process YouTube URLs if any
            if self.youtube_urls:
                urls = self.youtube_urls.strip().split('\n')
                for url in urls:
                    self.process_url(url.strip())

            # Process local files if any
            for i, file_path in enumerate(self.files_to_process, 1):
                self.progress.emit(f"Processing file {i}/{len(self.files_to_process)}: {file_path}")

                if file_path.lower().endswith('.mkv'):
                    file_path = self.convertMKVtoM4A(file_path)
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

    def set_process_priority(self, priority):
        """Set the process priority level"""
        try:
            import psutil
            p = psutil.Process(os.getpid())
            priority_map = {
                'Low': psutil.IDLE_PRIORITY_CLASS if hasattr(psutil, 'IDLE_PRIORITY_CLASS') else 0,
                'Below': psutil.BELOW_NORMAL_PRIORITY_CLASS if hasattr(psutil, 'BELOW_NORMAL_PRIORITY_CLASS') else 1,
                'Normal': psutil.NORMAL_PRIORITY_CLASS if hasattr(psutil, 'NORMAL_PRIORITY_CLASS') else 2,
                'Above': psutil.ABOVE_NORMAL_PRIORITY_CLASS if hasattr(psutil, 'ABOVE_NORMAL_PRIORITY_CLASS') else 3,
                'High': psutil.HIGH_PRIORITY_CLASS if hasattr(psutil, 'HIGH_PRIORITY_CLASS') else 4,
                'Realtime': psutil.REALTIME_PRIORITY_CLASS if hasattr(psutil, 'REALTIME_PRIORITY_CLASS') else 5,
            }
            # Linux uses niceness values (0-19, higher = lower priority)
            if hasattr(p, 'nice'):
                niceness_map = {
                    'Low': 19,
                    'Below': 10,
                    'Normal': 0,
                    'Above': -5,
                    'High': -10,
                    'Realtime': -20,
                }
                try:
                    p.nice(niceness_map.get(priority, 0))
                    self.progress.emit(f"Set process priority: {priority}")
                except (psutil.AccessDenied, OSError) as e:
                    self.progress.emit(f"Could not set priority (may need root): {priority}")
        except Exception as e:
            self.progress.emit(f"Priority setting error: {str(e)}")

    def process_local_file(self, file_path):
        """Process a local file using unified transcription module"""
        try:
            # Create output srt file path
            dir_path = os.path.dirname(file_path)
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            srt_file = os.path.join(dir_path, f"{base_name}.{self.model_name}.srt")

            # Get VAD settings
            vad_params = None
            if self.vad_enabled:
                vad_params = dict(min_silence_duration_ms=self.vad_silence_duration)

            # Get diarization settings
            diarization_params = None
            if self.diarization_enabled:
                diarization_params = dict(min_speakers=self.min_speakers, max_speakers=self.max_speakers)

            # Use unified transcription module with all settings
            success = transcribe.process_create(
                file=file_path,
                model_name=self.model_name,
                srt_file=srt_file,
                language=self.force_lang,
                device=self.device,
                compute_type=self.compute_type,
                force_device=self.force_device,
                cpu_threads=self.cpu_threads,
                vad_filter=self.vad_enabled,
                vad_params=vad_params,
                diarization=self.diarization_enabled,
                diarization_params=diarization_params,
                temperature=self.temperature,
                merge_lines=self.merge_lines,
                write=lambda msg: self.progress.emit(str(msg))
            )

            if success:
                self.progress.emit(f"Successfully transcribed {file_path}")
            else:
                self.error.emit(f"Failed to transcribe {file_path}")

        except Exception as e:
            self.error.emit(f"Error processing {file_path}: {str(e)}")

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
                force_device=self.force_device,
                use_cookies=self.use_cookies,
                browser=self.browser,
                cookie_file=self.cookie_file
            )
            
            # Process the URL
            yt.process_single_url(url, callback=lambda msg: self.progress.emit(str(msg)))
            
        except Exception as e:
            self.error.emit(f"Error processing {url}: {str(e)}")

    def convertMKVtoM4A(self, mkv_path):
        output_m4a = os.path.splitext(mkv_path)[0] + ".m4a"
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
                "-c:a", "aac", "-b:a", "192k",
                output_m4a
            ]

            subprocess.run(command, check=True)
            self.progress.emit(f"Converted {mkv_path} to {output_m4a}")
            return output_m4a

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
        
        # Settings file path
        self.settings_file = os.path.join(os.path.expanduser("~"), ".whisper_subs_settings.json")
        
        # Set window to maximize on primary monitor
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        self.setGeometry(screen_geometry)
        self.setWindowState(QtCore.Qt.WindowMaximized)

        self.initUI()

        # Load saved settings
        self.load_settings()

        # Setup clipboard monitoring
        self.clipboard_timer = QTimer()
        self.clipboard_timer.timeout.connect(self.check_clipboard)
        self.clipboard_timer.start(1000)  # Check every second

        # Setup system tray icon
        self.setup_system_tray()

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

        # Sort files option
        self.sort_files_check = QCheckBox('Sort Files Alphabetically', self)
        self.sort_files_check.setChecked(True)  # Default to checked
        sort_group.addWidget(self.sort_files_check)

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

        # Minimize to tray checkbox
        self.enable_tray_check = QCheckBox('Minimize to Tray (Keep Running)', self)
        self.enable_tray_check.setChecked(True)
        options_right.addWidget(self.enable_tray_check)

        # Auto-hide on start checkbox
        self.auto_hide_check = QCheckBox('Auto-Hide on Start', self)
        self.auto_hide_check.setChecked(False)  # Default to unchecked
        options_right.addWidget(self.auto_hide_check)

        clipboard_layout.addLayout(options_right)
        layout.addLayout(clipboard_layout)

        # Device selection
        device_group = QHBoxLayout()
        
        # Engine selection
        engine_layout = QVBoxLayout()
        engine_label = QLabel("Transcription Engine:")
        engine_layout.addWidget(engine_label)
        
        engine_controls = QHBoxLayout()
        self.whisper_radio = QRadioButton("Whisper")
        self.faster_whisper_radio = QRadioButton("FasterWhisper")
        self.whisper_radio.setChecked(True)  # Default to normal Whisper
        engine_controls.addWidget(self.whisper_radio)
        engine_controls.addWidget(self.faster_whisper_radio)
        engine_layout.addLayout(engine_controls)
        device_group.addLayout(engine_layout)
        
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

        # Thread count and process priority
        advanced_layout = QVBoxLayout()

        # Thread count
        thread_layout = QHBoxLayout()
        thread_layout.addWidget(QLabel("CPU Threads:"))
        self.thread_combo = QComboBox()
        thread_options = [
            "Auto (All Cores)",
            "1 Thread",
            "2 Threads",
            "4 Threads",
            "8 Threads",
            "16 Threads",
            "32 Threads"
        ]
        self.thread_combo.addItems(thread_options)
        self.thread_combo.setCurrentText("Auto (All Cores)")
        thread_layout.addWidget(self.thread_combo)
        advanced_layout.addLayout(thread_layout)

        # Process priority
        priority_layout = QHBoxLayout()
        priority_layout.addWidget(QLabel("Process Priority:"))
        self.priority_combo = QComboBox()
        priority_options = [
            "Normal",
            "Low (Idle)",
            "Below Normal",
            "Above Normal",
            "High",
            "Realtime (Not Recommended)"
        ]
        self.priority_combo.addItems(priority_options)
        self.priority_combo.setCurrentText("Normal")
        priority_layout.addWidget(self.priority_combo)
        advanced_layout.addLayout(priority_layout)

        device_group.addLayout(advanced_layout)

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

        # Advanced transcription options
        advanced_transcribe_group = QGroupBox("Advanced Transcription")
        advanced_transcribe_group.setStyleSheet("""
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
        advanced_transcribe_layout = QVBoxLayout()

        # Temperature setting
        temp_layout = QHBoxLayout()
        temp_layout.addWidget(QLabel("Temperature:"))
        self.temperature_spinbox = QComboBox()
        self.temperature_spinbox.addItems(["0.0", "0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7", "0.8", "0.9", "1.0"])
        self.temperature_spinbox.setCurrentText("0.3")
        temp_layout.addWidget(self.temperature_spinbox)
        temp_layout.addWidget(QLabel("(Higher = more creative, Lower = more deterministic)"))
        advanced_transcribe_layout.addLayout(temp_layout)

        # Merge lines checkbox
        self.merge_lines_check = QCheckBox("Merge Adjacent Lines (combine short segments)")
        self.merge_lines_check.setChecked(False)
        advanced_transcribe_layout.addWidget(self.merge_lines_check)

        advanced_transcribe_group.setLayout(advanced_transcribe_layout)
        device_group.addWidget(advanced_transcribe_group)

        # YouTube Cookies Settings
        youtube_settings_layout = QVBoxLayout()
        youtube_settings_group = QGroupBox("YouTube Settings")
        youtube_settings_group.setStyleSheet("""
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
        
        youtube_settings_inner = QVBoxLayout()
        
        # Cookie settings
        cookies_layout = QHBoxLayout()
        self.use_cookies_check = QCheckBox("Use cookies for age-restricted videos")
        cookies_layout.addWidget(self.use_cookies_check)
        youtube_settings_inner.addLayout(cookies_layout)
        
        # Browser selection
        browser_layout = QHBoxLayout()
        browser_layout.addWidget(QLabel("Browser:"))
        self.browser_combo = QComboBox()
        self.browser_combo.addItems([
            "chrome", "firefox", "edge", "safari", "opera", "brave"
        ])
        browser_layout.addWidget(self.browser_combo)
        
        # Cookie file selection
        self.cookie_file_path = QLineEdit()
        self.cookie_file_path.setPlaceholderText("Or custom cookie file path...")
        browser_layout.addWidget(self.cookie_file_path)
        
        self.browse_cookie_button = QPushButton("Browse")
        self.browse_cookie_button.clicked.connect(self.select_cookie_file)
        browser_layout.addWidget(self.browse_cookie_button)
        
        youtube_settings_inner.addLayout(browser_layout)
        youtube_settings_group.setLayout(youtube_settings_inner)
        youtube_settings_layout.addWidget(youtube_settings_group)
        
        device_group.addLayout(youtube_settings_layout)
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

        # File list with reordering controls
        file_list_layout = QHBoxLayout()
        
        # File list widget
        self.file_list_widget = QListWidget()
        self.file_list_widget.setDragDropMode(QAbstractItemView.InternalMove)
        self.file_list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list_widget.setMinimumHeight(150)
        self.file_list_widget.itemSelectionChanged.connect(self.update_file_buttons_state)
        file_list_layout.addWidget(self.file_list_widget, stretch=1)
        
        # Move buttons
        move_buttons_layout = QVBoxLayout()
        self.move_up_button = QPushButton('↑ Up')
        self.move_up_button.clicked.connect(self.move_file_up)
        self.move_up_button.setEnabled(False)
        move_buttons_layout.addWidget(self.move_up_button)
        
        self.move_down_button = QPushButton('↓ Down')
        self.move_down_button.clicked.connect(self.move_file_down)
        self.move_down_button.setEnabled(False)
        move_buttons_layout.addWidget(self.move_down_button)
        
        self.remove_button = QPushButton('Remove')
        self.remove_button.clicked.connect(self.remove_selected_files)
        self.remove_button.setEnabled(False)
        move_buttons_layout.addWidget(self.remove_button)
        
        self.clear_all_button = QPushButton('Clear All')
        self.clear_all_button.clicked.connect(self.clear_all_files)
        self.clear_all_button.setEnabled(False)
        move_buttons_layout.addWidget(self.clear_all_button)
        
        move_buttons_layout.addStretch()
        file_list_layout.addLayout(move_buttons_layout)
        
        layout.addLayout(file_list_layout)
        
        # File count label
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

    def setup_system_tray(self):
        """Setup system tray icon with options to hide/show the window"""
        if QSystemTrayIcon.isSystemTrayAvailable():
            # Create a system tray icon
            self.tray_icon = QSystemTrayIcon(self)

            # Set an icon (using the default application icon if available)
            app_icon = QtGui.QIcon.fromTheme("audio-x-generic")  # Generic audio icon
            if app_icon.isNull():  # If system theme doesn't have the icon
                # Create a simple pixmap as fallback
                pixmap = QtGui.QPixmap(32, 32)
                pixmap.fill(QtGui.QColor(59, 66, 82))  # Dark background color
                app_icon = QtGui.QIcon(pixmap)
            self.tray_icon.setIcon(app_icon)

            # Create context menu
            tray_menu = QMenu()

            # Show window action
            show_action = QAction("Show Window", self)
            show_action.triggered.connect(self.show_normal)
            tray_menu.addAction(show_action)

            # Hide window action
            hide_action = QAction("Hide Window", self)
            hide_action.triggered.connect(self.hide_window)
            tray_menu.addAction(hide_action)

            # Separator
            tray_menu.addSeparator()

            # Quit action
            quit_action = QAction("Quit", self)
            quit_action.triggered.connect(self.quit_app)
            tray_menu.addAction(quit_action)

            # Set the context menu for the tray icon
            self.tray_icon.setContextMenu(tray_menu)

            # Connect double-click to show window
            self.tray_icon.activated.connect(self.tray_icon_activated)

            # Show the tray icon
            self.tray_icon.show()

    def tray_icon_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_normal()

    def show_normal(self):
        """Show the window normally"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def hide_window(self):
        """Hide the window to system tray"""
        self.hide()

    def quit_app(self):
        """Quit the application"""
        # Save settings before quitting
        self.save_settings()
        QApplication.quit()

    def closeEvent(self, event):
        """Override close event to minimize to tray instead of quitting"""
        # Check if the minimize to tray option is enabled
        if hasattr(self, 'enable_tray_check') and self.enable_tray_check.isChecked():
            # Check if a transcription is running
            transcription_running = hasattr(self, 'transcription_thread') and self.transcription_thread and self.transcription_thread.isRunning()

            if transcription_running:
                # If transcription is running, always minimize to tray
                self.hide()
                event.ignore()  # Ignore the close event
            else:
                # If no transcription is running, ask for confirmation
                reply = QMessageBox.question(
                    self,
                    'Minimize to Tray',
                    'No transcription is currently running. Would you like to minimize to tray instead of closing?',
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )

                if reply == QMessageBox.Yes:
                    self.hide()
                    event.ignore()  # Ignore the close event
                else:
                    # Save settings before quitting
                    self.save_settings()
                    event.accept()  # Accept the close event and quit
        else:
            # Save settings before quitting
            self.save_settings()
            event.accept()  # Accept the close event and quit

    def selectFiles(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files",
            "",
            "Media Files (*.mkv *.mp3 *.wav *.flac *.ogg *.m4a *.aac)"
        )

        if files:
            # Sort files based on user preference
            if hasattr(self, 'sort_files_check') and self.sort_files_check.isChecked():
                # Sort files naturally (e.g., "Episode 1" before "Episode 10")
                try:
                    from natsort import natsorted  # For natural sorting
                    new_files = natsorted(files, key=lambda x: x.lower())
                except ImportError:
                    # Fallback to alphabetical sorting if natsort isn't available
                    new_files = sorted(files, key=lambda x: x.lower())
            else:
                # Keep the original order as selected by the user
                new_files = files
            
            # Add new files to the list (avoid duplicates)
            existing_files = set(self.selected_files)
            for file in new_files:
                if file not in existing_files:
                    self.selected_files.append(file)
                    self.file_list_widget.addItem(file)
            
            self.update_file_label()
            self.update_file_buttons_state()

            if not self.log_file and self.selected_files:
                self.log_file = os.path.splitext(self.selected_files[0])[0] + '.log'
    
    def update_file_label(self):
        """Update the file count label"""
        count = len(self.selected_files)
        if count == 0:
            self.file_label.setText("Selected files: None")
        elif count == 1:
            self.file_label.setText("Selected files: 1 file")
        else:
            self.file_label.setText(f"Selected files: {count} files")
    
    def update_file_buttons_state(self):
        """Update the state of move/remove buttons based on selection"""
        selected_items = self.file_list_widget.selectedItems()
        selected_count = len(selected_items)
        current_row = self.file_list_widget.currentRow()
        total_count = self.file_list_widget.count()
        
        # Enable/disable remove button
        self.remove_button.setEnabled(selected_count > 0)
        
        # Enable/disable clear all button
        self.clear_all_button.setEnabled(total_count > 0)
        
        # Enable/disable move buttons based on selection
        if selected_count == 1:
            self.move_up_button.setEnabled(current_row > 0)
            self.move_down_button.setEnabled(current_row < self.file_list_widget.count() - 1)
        else:
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)
    
    def move_file_up(self):
        """Move selected file up in the list"""
        current_row = self.file_list_widget.currentRow()
        if current_row > 0:
            # Swap in list
            self.selected_files[current_row], self.selected_files[current_row - 1] = \
                self.selected_files[current_row - 1], self.selected_files[current_row]
            
            # Swap in widget
            current_item = self.file_list_widget.takeItem(current_row)
            self.file_list_widget.insertItem(current_row - 1, current_item)
            self.file_list_widget.setCurrentRow(current_row - 1)
            self.update_file_label()
    
    def move_file_down(self):
        """Move selected file down in the list"""
        current_row = self.file_list_widget.currentRow()
        if 0 <= current_row < self.file_list_widget.count() - 1:
            # Swap in list
            self.selected_files[current_row], self.selected_files[current_row + 1] = \
                self.selected_files[current_row + 1], self.selected_files[current_row]
            
            # Swap in widget
            current_item = self.file_list_widget.takeItem(current_row)
            self.file_list_widget.insertItem(current_row + 1, current_item)
            self.file_list_widget.setCurrentRow(current_row + 1)
            self.update_file_label()
    
    def remove_selected_files(self):
        """Remove selected files from the list"""
        selected_items = self.file_list_widget.selectedItems()
        for item in selected_items:
            row = self.file_list_widget.row(item)
            self.file_list_widget.takeItem(row)
            if 0 <= row < len(self.selected_files):
                self.selected_files.pop(row)
        
        self.update_file_label()
        self.update_file_buttons_state()
    
    def clear_all_files(self):
        """Clear all files from the list"""
        self.file_list_widget.clear()
        self.selected_files = []
        self.update_file_label()
        self.update_file_buttons_state()
    
    def selectDirectory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.selected_directory = directory
            self.dir_label.setText(f"Selected directory: {directory}")
            
            # Get all media files from directory
            media_extensions = {'.mkv', '.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma'}
            dir_files = []
            for file in sorted(os.listdir(directory)):
                if os.path.splitext(file)[1].lower() in media_extensions:
                    full_path = os.path.join(directory, file)
                    if full_path not in self.selected_files:
                        dir_files.append(full_path)
            
            # Add files to list
            for file in dir_files:
                self.selected_files.append(file)
                self.file_list_widget.addItem(file)
            
            self.update_file_label()
            self.update_file_buttons_state()
            
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
        # Save settings before running transcription
        self.save_settings()
        
        model_name = self.model_combo.currentText()
        
        # Get device settings
        device = 'cuda' if self.gpu_radio.isChecked() else 'cpu'
        force_device = self.force_device_check.isChecked()
        
        # Get compute type (strip description)
        compute = self.compute_combo.currentText().split(' ')[0]
        
        # Get time range if specified
        start_time = self.start_time.text().strip() or None
        end_time = self.end_time.text().strip() or None

        # Process local files - use selected_files directly
        files_to_process = list(self.selected_files)

        # Add files from directory if selected
        if self.selected_directory:
            for f in os.listdir(self.selected_directory):
                if f.lower().endswith(('.mkv', '.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac')):
                    full_path = os.path.join(self.selected_directory, f)
                    if full_path not in files_to_process:
                        files_to_process.append(full_path)

        # Sort files based on user preference
        if hasattr(self, 'sort_files_check') and self.sort_files_check.isChecked():
            # Sort files naturally (e.g., "Episode 1" before "Episode 10")
            try:
                from natsort import natsorted
                files_to_process = natsorted(files_to_process, key=lambda x: os.path.basename(x).lower())
            except ImportError:
                files_to_process.sort(key=lambda x: os.path.basename(x).lower())

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
            youtube_urls=youtube_urls if youtube_urls else None,
            use_cookies=self.use_cookies_check.isChecked(),
            browser=self.browser_combo.currentText() if not self.cookie_file_path.text() else None,
            cookie_file=self.cookie_file_path.text() if self.cookie_file_path.text() else None
        )

        self.transcription_thread.progress.connect(self.log)
        self.transcription_thread.finished.connect(self.on_transcription_finished)
        self.transcription_thread.error.connect(self.on_transcription_error)

        # Auto-hide the window if the option is enabled
        if hasattr(self, 'auto_hide_check') and self.auto_hide_check.isChecked():
            self.hide()

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

    def select_cookie_file(self):
        """Open file dialog to select a cookie file"""
        cookie_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Cookie File",
            "",
            "Cookie Files (*.txt);;All Files (*.*)"
        )
        
        if cookie_file:
            self.cookie_file_path.setText(cookie_file)
            self.use_cookies_check.setChecked(True)

    def save_settings(self):
        """Save current settings to JSON file"""
        settings = {
            'model': self.model_combo.currentText(),
            'language': self.lang_combo.currentText(),
            'device': 'cuda' if self.gpu_radio.isChecked() else 'cpu',
            'compute_type': self.compute_combo.currentText(),
            'force_device': self.force_device_check.isChecked(),
            'use_whisper': self.whisper_radio.isChecked(),
            'vad_enabled': self.vad_enabled.isChecked(),
            'vad_silence_duration': self.vad_silence_duration.text(),
            'diarization_enabled': self.diarization_enabled.isChecked(),
            'min_speakers': self.min_speakers.text(),
            'max_speakers': self.max_speakers.text(),
            'start_time': self.start_time.text(),
            'end_time': self.end_time.text(),
            'enable_logging': self.enable_logging_check.isChecked(),
            'clipboard_monitoring': self.clipboard_monitoring,
            'sort_oldest': self.sort_oldest_check.isChecked(),
            'reverse_order': self.reverse_order_check.isChecked(),
            'youtube_urls': self.youtube_input.toPlainText(),
            'selected_directory': self.selected_directory,
            'selected_files': self.selected_files,
            'use_cookies': self.use_cookies_check.isChecked(),
            'browser': self.browser_combo.currentText(),
            'cookie_file': self.cookie_file_path.text(),
            'enable_tray': self.enable_tray_check.isChecked(),
            'auto_hide': self.auto_hide_check.isChecked(),
            'cpu_threads': self.thread_combo.currentText(),
            'process_priority': self.priority_combo.currentText()
        }

        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            self.log(f"Error saving settings: {str(e)}")

    def load_settings(self):
        """Load settings from JSON file"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                # Apply loaded settings
                if 'model' in settings:
                    index = self.model_combo.findText(settings['model'])
                    if index >= 0:
                        self.model_combo.setCurrentIndex(index)
                
                if 'language' in settings:
                    index = self.lang_combo.findText(settings['language'])
                    if index >= 0:
                        self.lang_combo.setCurrentIndex(index)
                
                if 'device' in settings:
                    self.gpu_radio.setChecked(settings['device'] == 'cuda')
                    self.cpu_radio.setChecked(settings['device'] == 'cpu')
                
                if 'compute_type' in settings:
                    index = self.compute_combo.findText(settings['compute_type'])
                    if index >= 0:
                        self.compute_combo.setCurrentIndex(index)
                
                if 'force_device' in settings:
                    self.force_device_check.setChecked(settings['force_device'])
                
                if 'use_whisper' in settings:
                    self.whisper_radio.setChecked(settings['use_whisper'])
                    self.faster_whisper_radio.setChecked(not settings['use_whisper'])
                
                if 'vad_enabled' in settings:
                    self.vad_enabled.setChecked(settings['vad_enabled'])
                
                if 'vad_silence_duration' in settings:
                    self.vad_silence_duration.setText(settings['vad_silence_duration'])
                
                if 'diarization_enabled' in settings:
                    self.diarization_enabled.setChecked(settings['diarization_enabled'])
                
                if 'min_speakers' in settings:
                    self.min_speakers.setText(settings['min_speakers'])
                
                if 'max_speakers' in settings:
                    self.max_speakers.setText(settings['max_speakers'])
                
                if 'start_time' in settings:
                    self.start_time.setText(settings['start_time'])
                
                if 'end_time' in settings:
                    self.end_time.setText(settings['end_time'])
                
                if 'enable_logging' in settings:
                    self.enable_logging_check.setChecked(settings['enable_logging'])
                
                if 'clipboard_monitoring' in settings:
                    self.clipboard_monitoring = settings['clipboard_monitoring']
                    self.clipboard_toggle.setChecked(settings['clipboard_monitoring'])
                    self.clipboard_toggle.setText(f'Clipboard Monitoring: {"ON" if settings["clipboard_monitoring"] else "OFF"}')
                
                if 'sort_oldest' in settings:
                    self.sort_oldest_check.setChecked(settings['sort_oldest'])
                
                if 'reverse_order' in settings:
                    self.reverse_order_check.setChecked(settings['reverse_order'])
                
                if 'youtube_urls' in settings:
                    self.youtube_input.setPlainText(settings['youtube_urls'])
                
                if 'selected_directory' in settings and settings['selected_directory']:
                    self.selected_directory = settings['selected_directory']
                    self.dir_label.setText(f"Selected directory: {self.selected_directory}")

                if 'selected_files' in settings:
                    self.selected_files = settings['selected_files']
                    # Populate the file list widget
                    self.file_list_widget.clear()
                    for file in self.selected_files:
                        self.file_list_widget.addItem(file)
                    self.update_file_label()
                    self.update_file_buttons_state()
                
                # Load YouTube cookie settings
                if 'use_cookies' in settings:
                    self.use_cookies_check.setChecked(settings['use_cookies'])
                
                if 'browser' in settings:
                    index = self.browser_combo.findText(settings['browser'])
                    if index >= 0:
                        self.browser_combo.setCurrentIndex(index)
                
                if 'cookie_file' in settings:
                    self.cookie_file_path.setText(settings['cookie_file'])

                if 'enable_tray' in settings:
                    self.enable_tray_check.setChecked(settings['enable_tray'])

                if 'auto_hide' in settings:
                    self.auto_hide_check.setChecked(settings['auto_hide'])

                # Load thread count and process priority settings
                if 'cpu_threads' in settings:
                    index = self.thread_combo.findText(settings['cpu_threads'])
                    if index >= 0:
                        self.thread_combo.setCurrentIndex(index)

                if 'process_priority' in settings:
                    index = self.priority_combo.findText(settings['process_priority'])
                    if index >= 0:
                        self.priority_combo.setCurrentIndex(index)

        except Exception as e:
            self.log(f"Error loading settings: {str(e)}")

    def closeEvent(self, event):
        """Save settings when closing the application"""
        self.save_settings()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set font DPI
    font = app.font()
    font.setPointSize(10)  # Adjust base font size
    app.setFont(font)
    
    window = TranscriptionApp()
    window.show()  # Use show() instead of exec_() for better compatibility
    sys.exit(app.exec_())
