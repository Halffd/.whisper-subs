"""
WhisperSubs PyQt6 GUI - Desktop Application

Graphical interface for audio/video transcription using Whisper AI.
Supports all adapter backends via provider:model syntax.
"""
import os
import sys
import datetime
import subprocess
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Union, Callable


def _safe_model_filename(model_name: str) -> str:
    return model_name.replace(':', '_')

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLineEdit, QLabel,
    QFileDialog, QMessageBox, QTextEdit, QComboBox, QHBoxLayout, QCheckBox,
    QRadioButton, QGroupBox, QGridLayout, QSystemTrayIcon, QMenu,
    QListWidget, QAbstractItemView, QSlider, QStyledItemDelegate, QStyleOptionViewItem,
)
from PyQt6.QtGui import QAction, QIcon, QPixmap, QColor, QPalette
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, Qt, QModelIndex, qInstallMessageHandler
from PyQt6.QtWidgets import QStyle
import pymkv
import time
from whisper_subs import WhisperSubs
import pyperclip
import json

from ui.models import get_flat_display_list, is_separator as _is_sep

_PROVIDER_LABELS = {
    "groq": "Groq",
    "hf": "HuggingFace",
    "whisperx": "WhisperX",
    "whispercpp": "whisper.cpp",
    "moonshine": "Moonshine",
    "deepgram": "Deepgram",
    "chirp": "Google Chirp",
    "voxtral": "Voxtral (Mistral)",
    "parakeet": "Parakeet (NVIDIA NeMo)",
    "canary": "Canary (NVIDIA NeMo)",
    "vibevoice": "VibeVoice",
    "whisperturbo": "Whisper Turbo",
}

_transcribe_module = None
def _get_transcribe():
    global _transcribe_module
    if _transcribe_module is None:
        import transcribe as _transcribe_module
    return _transcribe_module


def qt_message_handler(mode, context, message):
    if mode == Qt.MsgType.QtWarningMsg and 'propagateSizeHints' in message:
        return
    if mode == Qt.MsgType.QtInfoMsg:
        mode_str = 'INFO'
    elif mode == Qt.MsgType.QtWarningMsg:
        mode_str = 'WARNING'
    elif mode == Qt.MsgType.QtCriticalMsg:
        mode_str = 'CRITICAL'
    elif mode == Qt.MsgType.QtFatalMsg:
        mode_str = 'FATAL'
    else:
        mode_str = 'DEBUG'
    print('qt_message_handler: line: %d, func: %s(), file: %s' % (
        context.line, context.function, context.file))
    print('  %s: %s\n' % (mode_str, message))

qInstallMessageHandler(qt_message_handler)

os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_SCALE_FACTOR"] = "1"


class SeparatorDelegate(QStyledItemDelegate):
    """Makes group-separator items non-selectable and visually distinct."""

    def paint(self, painter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if _is_sep(text):
            option = QStyleOptionViewItem(option)
            option.state &= ~QStyle.StateFlag.State_Enabled
            option.displayAlignment = Qt.AlignmentFlag.AlignCenter
            font = option.font
            font.setBold(True)
            option.font = font
            option.palette.setColor(
                QPalette.ColorRole.Text,
                option.palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            )
            super().paint(painter, option, index)

    def flags(self, index):
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if _is_sep(text):
            return Qt.ItemFlag.NoItemFlags
        return super().flags(index)


class TranscriptionThread(QThread):
    finished = pyqtSignal()
    progress = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        files_to_process: List[str],
        model_name: str,
        log_callback: Callable,
        youtube_urls: Optional[str] = None,
        use_cookies: bool = False,
        browser: Optional[str] = None,
        cookie_file: Optional[str] = None
    ):
        super().__init__()
        self.files_to_process: List[str] = files_to_process
        self.model_name: str = model_name
        self.log_callback: Callable = log_callback
        self.youtube_urls: Optional[str] = youtube_urls
        self.use_cookies: bool = use_cookies
        self.browser: Optional[str] = browser
        self.cookie_file: Optional[str] = cookie_file

        self._stop_event: threading.Event = threading.Event()
        self._pause_event: threading.Event = threading.Event()
        self._pause_event.set()
        self._lock: threading.Lock = threading.Lock()
        self._progress_lock: threading.Lock = threading.Lock()

        self.device: str = 'cuda'
        self.compute_type: str = 'int8'
        self.force_device: bool = False
        self.use_faster_whisper: bool = False
        self.force_lang: Optional[str] = None
        self.vad_enabled: Optional[bool] = None
        self.vad_silence_duration: Optional[int] = None
        self.diarization_enabled: bool = False
        self.min_speakers: int = 1
        self.max_speakers: int = 2
        self.cpu_threads: Optional[int] = None
        self.process_priority: str = "Normal"
        self.temperature: Optional[float] = None
        self.merge_lines: bool = False
        self.mpv_ipc: bool = False
        self.start_time: Optional[str] = None
        self.end_time: Optional[str] = None
        self.force: bool = False
        self.replace_subs: bool = False
        self.backup_subs: bool = True
        self.retry: bool = True

        main_window = QApplication.activeWindow()
        if main_window:
            self.device = 'cuda' if main_window.gpu_radio.isChecked() else 'cpu'
            self.compute_type = main_window.compute_combo.currentText().split(' ')[0]
            self.force_device = main_window.force_device_check.isChecked()
            self.use_faster_whisper = main_window.faster_whisper_radio.isChecked()

            selected_lang = main_window.lang_combo.currentText()
            self.force_lang = None if selected_lang == "Automatic" else selected_lang.split('(')[-1].strip(')')

            self.vad_enabled = main_window.vad_enabled.isChecked() if main_window.vad_enabled.isChecked() else None
            try:
                self.vad_silence_duration = int(main_window.vad_silence_duration.text() or "500") if main_window.vad_enabled.isChecked() else None
            except ValueError:
                self.vad_silence_duration = None

            self.diarization_enabled = main_window.diarization_enabled.isChecked()
            try:
                self.min_speakers = int(main_window.min_speakers.text() or "1")
                self.max_speakers = int(main_window.max_speakers.text() or "2")
            except ValueError:
                self.min_speakers = 1
                self.max_speakers = 2

            thread_text = main_window.thread_combo.currentText()
            if thread_text == "Auto (All Cores)":
                self.cpu_threads = None
            else:
                self.cpu_threads = int(thread_text.split()[0])

            priority_text = main_window.priority_combo.currentText()
            self.process_priority = priority_text.split()[0]

            if hasattr(main_window, 'temperature_auto_check') and main_window.temperature_auto_check.isChecked():
                self.temperature = None
            elif hasattr(main_window, 'temperature_slider'):
                self.temperature = main_window.temperature_slider.value() / 10.0
            else:
                self.temperature = None

            self.merge_lines = hasattr(main_window, 'merge_lines_check') and main_window.merge_lines_check.isChecked()
            self.mpv_ipc = hasattr(main_window, 'mpv_ipc_check') and main_window.mpv_ipc_check.isChecked()

            self.force = hasattr(main_window, 'force_check') and main_window.force_check.isChecked()
            self.replace_subs = hasattr(main_window, 'replace_subs_check') and main_window.replace_subs_check.isChecked()
            self.backup_subs = hasattr(main_window, 'backup_subs_check') and main_window.backup_subs_check.isChecked()
            self.retry = hasattr(main_window, 'retry_check') and main_window.retry_check.isChecked()

        else:
            self.device = 'cuda'
            self.compute_type = 'int8'
            self.force_device = False
            self.force_lang = None
            self.vad_enabled = None
            self.vad_silence_duration = None
            self.diarization_enabled = False
            self.min_speakers = 1
            self.max_speakers = 2
            self.use_faster_whisper = False
            self.cpu_threads = None
            self.process_priority = "Normal"
            self.temperature = None
            self.merge_lines = False
            self.mpv_ipc = False
            self.start_time = None
            self.end_time = None
            self.force = False
            self.replace_subs = False
            self.backup_subs = True
            self.retry = True

        import socketio
        self.sio = socketio.Client()
        self.sio.on('progress', self.handle_progress)
        try:
            self.sio.connect('http://localhost:5000')
        except Exception as e:
            self.error.emit(f"Could not connect to transcription service: {str(e)}")

    def handle_progress(self, data: Dict[str, Any]) -> None:
        if 'message' in data:
            self.progress.emit(data['message'])

    def run(self) -> None:
        try:
            self.set_process_priority(self.process_priority)

            if self.youtube_urls:
                urls = self.youtube_urls.strip().split('\n')
                for url in urls:
                    self.process_url(url.strip())

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
        try:
            import psutil
            p = psutil.Process(os.getpid())
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
                except (psutil.AccessDenied, OSError):
                    self.progress.emit(f"Could not set priority (may need root): {priority}")
                except Exception as e:
                    self.progress.emit(f"Priority setting error: {str(e)}")
        except ImportError:
            pass

    def process_local_file(self, file_path: str) -> None:
        try:
            dir_path = os.path.dirname(file_path)
            base_name = os.path.splitext(os.path.basename(file_path))[0]

            safe_model = _safe_model_filename(self.model_name)
            srt_file = os.path.join(dir_path, f"{base_name}.{safe_model}.srt")

            output_dir = os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs")
            local_files_dir = os.path.join(output_dir, "local_files")
            os.makedirs(local_files_dir, exist_ok=True)
            srt_file_secondary = os.path.join(local_files_dir, f"{base_name}.{safe_model}.srt")

            vad_params = None
            if self.vad_enabled is True:
                vad_params = dict(min_silence_duration_ms=self.vad_silence_duration) if self.vad_silence_duration else None

            diarization_params = None
            if self.diarization_enabled:
                diarization_params = dict(min_speakers=self.min_speakers, max_speakers=self.max_speakers)

            mpv_reload_callback = None
            if self.mpv_ipc:
                import socket
                import json as _json
                mpv_socket_path = '/tmp/mpvsocket'

                def reload_subtitles():
                    try:
                        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        sock.connect(mpv_socket_path)
                        command = {"command": ["sub-reload"]}
                        sock.sendall(_json.dumps(command).encode() + b'\n')
                        response = sock.recv(4096).decode()
                        sock.close()
                    except Exception as e:
                        self.progress.emit(f"MPV IPC reload failed: {e}")

                mpv_reload_callback = reload_subtitles

            success = _get_transcribe().process_create(
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
                start_time=self.start_time,
                end_time=self.end_time,
                mpv_ipc_reload=mpv_reload_callback,
                write=lambda msg: self.progress.emit(str(msg))
            )

            if success:
                self.progress.emit(f"Successfully transcribed {file_path}")
                if os.path.exists(srt_file):
                    try:
                        import shutil
                        shutil.copy2(srt_file, srt_file_secondary)
                        self.progress.emit(f"Copied subtitle to: {srt_file_secondary}")
                    except Exception as copy_err:
                        self.progress.emit(f"Warning: Could not copy to secondary location: {copy_err}")
            else:
                self.error.emit(f"Failed to transcribe {file_path}")

        except Exception as e:
            self.error.emit(f"Error processing {file_path}: {str(e)}")

    def format_timestamp(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = seconds % 60
        milliseconds = int((seconds % 1) * 1000)
        seconds = int(seconds)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    def process_url(self, url: str) -> None:
        try:
            yt = WhisperSubs(
                model_name=self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                browser=self.browser if self.use_cookies else None
            )
            yt.process(url)
        except Exception as e:
            self.error.emit(f"Error processing {url}: {str(e)}")

    def convertMKVtoM4A(self, mkv_path):
        output_m4a = os.path.splitext(mkv_path)[0] + ".m4a"
        try:
            mkv = pymkv.MKVFile(mkv_path)
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
        self.whisper_subs_processor = None
        self.last_clipboard = ""
        self.clipboard_monitoring = True
        self.force_device = False

        self.settings_file = os.path.join(os.path.expanduser("~"), ".whisper_subs_settings.json")

        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        self.setGeometry(screen_geometry)
        self.setWindowState(Qt.WindowState.WindowMaximized)

        self.initUI()
        self.load_settings()

        self.clipboard_timer = QTimer()
        self.clipboard_timer.timeout.connect(self.check_clipboard)
        self.clipboard_timer.start(1000)

        self.setup_system_tray()

    def initUI(self):
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
        QComboBox QAbstractItemView {
            background-color: #3B4252;
            color: #ECEFF4;
            selection-background-color: #5E81AC;
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

        # Clipboard and options row
        clipboard_layout = QHBoxLayout()

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

        options_right = QVBoxLayout()

        sort_layout = QHBoxLayout()
        sort_group = QVBoxLayout()
        self.sort_oldest_check = QCheckBox('Sort by Oldest', self)
        self.sort_oldest_check.stateChanged.connect(self.resort_urls)
        sort_group.addWidget(self.sort_oldest_check)

        self.reverse_order_check = QCheckBox('Reverse Order', self)
        self.reverse_order_check.stateChanged.connect(self.resort_urls)
        sort_group.addWidget(self.reverse_order_check)

        self.sort_files_check = QCheckBox('Sort Files Alphabetically', self)
        self.sort_files_check.setChecked(True)
        sort_group.addWidget(self.sort_files_check)

        sort_layout.addLayout(sort_group)
        options_right.addLayout(sort_layout)

        # Model and language selection
        model_lang_layout = QHBoxLayout()

        model_layout = QVBoxLayout()
        model_label = QLabel("Model:")

        adapter_model_row = QHBoxLayout()
        self.adapter_combo = QComboBox()
        self._populate_adapter_combo()
        self.adapter_combo.currentIndexChanged.connect(self._on_adapter_filter_changed)
        adapter_model_row.addWidget(QLabel("Provider:"))
        adapter_model_row.addWidget(self.adapter_combo, 1)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._populate_model_combo()
        self.model_combo.setItemDelegate(SeparatorDelegate(self.model_combo))
        self.model_combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
        adapter_model_row.addWidget(self.model_combo, 3)

        model_layout.addWidget(model_label)
        model_layout.addLayout(adapter_model_row)
        model_lang_layout.addLayout(model_layout)

        lang_layout = QVBoxLayout()
        lang_label = QLabel("Language:")
        self.lang_combo = QComboBox()
        languages = [
            "Automatic",
            "English (en)", "Japanese (ja)", "Chinese (zh)", "Korean (ko)",
            "Spanish (es)", "French (fr)", "German (de)", "Italian (it)",
            "Russian (ru)", "Portuguese (pt)", "Dutch (nl)", "Polish (pl)",
            "Turkish (tr)", "Arabic (ar)", "Hindi (hi)", "Vietnamese (vi)"
        ]
        self.lang_combo.addItems(languages)
        self.lang_combo.setCurrentText("Automatic")
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

        self.enable_logging_check = QCheckBox('Enable File Logging', self)
        self.enable_logging_check.setChecked(True)
        options_right.addWidget(self.enable_logging_check)

        self.enable_tray_check = QCheckBox('Minimize to Tray (Keep Running)', self)
        self.enable_tray_check.setChecked(True)
        options_right.addWidget(self.enable_tray_check)

        self.auto_hide_check = QCheckBox('Auto-Hide on Start', self)
        self.auto_hide_check.setChecked(False)
        options_right.addWidget(self.auto_hide_check)

        clipboard_layout.addLayout(options_right)
        layout.addLayout(clipboard_layout)

        # Device selection
        device_group = QHBoxLayout()

        engine_layout = QVBoxLayout()
        engine_label = QLabel("Transcription Engine:")
        engine_layout.addWidget(engine_label)

        engine_controls = QHBoxLayout()
        self.whisper_radio = QRadioButton("Whisper")
        self.faster_whisper_radio = QRadioButton("FasterWhisper")
        self.whisper_radio.setChecked(True)
        engine_controls.addWidget(self.whisper_radio)
        engine_controls.addWidget(self.faster_whisper_radio)
        engine_layout.addLayout(engine_controls)
        device_group.addLayout(engine_layout)

        device_layout = QVBoxLayout()
        device_label = QLabel("Processing Device:")
        device_layout.addWidget(device_label)

        device_controls = QHBoxLayout()
        self.gpu_radio = QRadioButton("GPU (CUDA)")
        self.cpu_radio = QRadioButton("CPU")
        self.gpu_radio.setChecked(True)
        device_controls.addWidget(self.gpu_radio)
        device_controls.addWidget(self.cpu_radio)
        device_layout.addLayout(device_controls)

        self.force_device_check = QCheckBox("Force Device (Don't Auto-Switch)")
        device_layout.addWidget(self.force_device_check)

        device_group.addLayout(device_layout)

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

        advanced_layout = QVBoxLayout()

        options_group = QGroupBox("Transcription Options")
        options_group.setStyleSheet("""
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
        options_layout = QGridLayout()

        self.force_check = QCheckBox("Force (Ignore existing subtitles)")
        options_layout.addWidget(self.force_check, 0, 0)

        self.replace_subs_check = QCheckBox("Replace existing subtitles")
        options_layout.addWidget(self.replace_subs_check, 0, 1)

        self.backup_subs_check = QCheckBox("Backup existing subtitles")
        self.backup_subs_check.setChecked(True)
        options_layout.addWidget(self.backup_subs_check, 1, 0)

        self.retry_check = QCheckBox("Retry on failure (smaller models)")
        self.retry_check.setChecked(True)
        options_layout.addWidget(self.retry_check, 1, 1)

        options_group.setLayout(options_layout)
        advanced_layout.addWidget(options_group)

        thread_layout = QHBoxLayout()
        thread_layout.addWidget(QLabel("CPU Threads:"))
        self.thread_combo = QComboBox()
        thread_options = [
            "Auto (All Cores)",
            "1 Thread", "2 Threads", "4 Threads",
            "8 Threads", "16 Threads", "32 Threads"
        ]
        self.thread_combo.addItems(thread_options)
        self.thread_combo.setCurrentText("Auto (All Cores)")
        thread_layout.addWidget(self.thread_combo)
        advanced_layout.addLayout(thread_layout)

        priority_layout = QHBoxLayout()
        priority_layout.addWidget(QLabel("Process Priority:"))
        self.priority_combo = QComboBox()
        priority_options = [
            "Normal", "Low (Idle)", "Below Normal",
            "Above Normal", "High", "Realtime (Not Recommended)"
        ]
        self.priority_combo.addItems(priority_options)
        self.priority_combo.setCurrentText("Normal")
        priority_layout.addWidget(self.priority_combo)
        advanced_layout.addLayout(priority_layout)

        device_group.addLayout(advanced_layout)

        # VAD and diarization
        vad_diar_layout = QVBoxLayout()

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
        self.vad_enabled = QCheckBox("Enable VAD Filter")
        self.vad_enabled.setChecked(False)
        vad_layout.addWidget(self.vad_enabled)

        vad_params = QHBoxLayout()
        vad_params.addWidget(QLabel("Min Silence Duration (ms):"))
        self.vad_silence_duration = QLineEdit()
        self.vad_silence_duration.setPlaceholderText("500")
        self.vad_silence_duration.setText("500")
        vad_params.addWidget(self.vad_silence_duration)
        vad_layout.addLayout(vad_params)

        vad_group.setLayout(vad_layout)
        vad_diar_layout.addWidget(vad_group)

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
        self.diarization_enabled = QCheckBox("Enable Speaker Diarization")
        self.diarization_enabled.setChecked(False)
        diar_layout.addWidget(self.diarization_enabled)

        diar_params = QGridLayout()
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

        # Advanced transcription
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

        temp_checkbox_layout = QHBoxLayout()
        self.temperature_auto_check = QCheckBox("Auto (Model Default)")
        self.temperature_auto_check.setChecked(True)
        temp_checkbox_layout.addWidget(self.temperature_auto_check)
        temp_checkbox_layout.addStretch()
        advanced_transcribe_layout.addLayout(temp_checkbox_layout)

        temp_slider_layout = QHBoxLayout()
        temp_slider_layout.addWidget(QLabel("Temperature:"))

        self.temperature_slider = QSlider(Qt.Orientation.Horizontal)
        self.temperature_slider.setMinimum(0)
        self.temperature_slider.setMaximum(10)
        self.temperature_slider.setValue(3)
        self.temperature_slider.setTickPosition(QSlider.TicksBelow)
        self.temperature_slider.setTickInterval(1)
        self.temperature_slider.setEnabled(False)
        temp_slider_layout.addWidget(self.temperature_slider)

        self.temperature_value_label = QLabel("0.3")
        self.temperature_value_label.setMinimumWidth(30)
        temp_slider_layout.addWidget(self.temperature_value_label)

        advanced_transcribe_layout.addLayout(temp_slider_layout)

        self.temperature_auto_check.stateChanged.connect(self.toggle_temperature_slider)
        self.temperature_slider.valueChanged.connect(self.update_temperature_label)

        advanced_transcribe_layout.addWidget(QLabel("(Higher = more creative, Lower = more deterministic)"))

        self.merge_lines_check = QCheckBox("Merge Adjacent Lines (combine short segments)")
        self.merge_lines_check.setChecked(False)
        advanced_transcribe_layout.addWidget(self.merge_lines_check)

        self.mpv_ipc_check = QCheckBox("MPV IPC Subtitle Reload (update subtitles in real-time while transcribing)")
        self.mpv_ipc_check.setChecked(False)
        advanced_transcribe_layout.addWidget(self.mpv_ipc_check)

        advanced_transcribe_group.setLayout(advanced_transcribe_layout)
        device_group.addWidget(advanced_transcribe_group)

        # YouTube settings
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
        cookies_layout = QHBoxLayout()
        self.use_cookies_check = QCheckBox("Use cookies for age-restricted videos")
        cookies_layout.addWidget(self.use_cookies_check)
        youtube_settings_inner.addLayout(cookies_layout)

        browser_layout = QHBoxLayout()
        browser_layout.addWidget(QLabel("Browser:"))
        self.browser_combo = QComboBox()
        self.browser_combo.addItems([
            "chrome", "firefox", "edge", "safari", "opera", "brave"
        ])
        browser_layout.addWidget(self.browser_combo)

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

        # API Keys configuration
        api_keys_group = QGroupBox("API Keys")
        api_keys_group.setStyleSheet("""
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
        api_keys_layout = QVBoxLayout()

        self._api_key_fields = {}
        api_key_defs = [
            ("GROQ_API_KEY", "Groq API Key:"),
            ("HF_API_KEY", "HuggingFace API Key:"),
            ("HF_TOKEN", "HuggingFace Token (NeMo/WhisperX):"),
            ("DEEPGRAM_API_KEY", "Deepgram API Key:"),
            ("GOOGLE_APPLICATION_CREDENTIALS", "Google Credentials JSON Path:"),
        ]

        for env_var, label_text in api_key_defs:
            row = QHBoxLayout()
            row.addWidget(QLabel(label_text))
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText(f"Set {env_var}")
            existing = os.environ.get(env_var, "")
            if existing:
                field.setText(existing)
            row.addWidget(field, 1)

            toggle_btn = QPushButton("Show")
            toggle_btn.setFixedWidth(50)
            toggle_btn.setCheckable(True)
            toggle_btn.toggled.connect(lambda checked, f=field: f.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            ))
            toggle_btn.toggled.connect(lambda checked, b=toggle_btn: b.setText("Hide" if checked else "Show"))
            row.addWidget(toggle_btn)

            set_btn = QPushButton("Set")
            set_btn.setFixedWidth(40)
            set_btn.clicked.connect(lambda _, ev=env_var, f=field: self._set_env_key(ev, f.text()))
            row.addWidget(set_btn)

            api_keys_layout.addLayout(row)
            self._api_key_fields[env_var] = field

        api_keys_group.setLayout(api_keys_layout)
        device_group.addWidget(api_keys_group)
        layout.addLayout(device_group)

        # YouTube URL input
        layout.addWidget(QLabel("YouTube URLs (one per line):"))
        self.url_count_label = QLabel("0 URLs")
        layout.addWidget(self.url_count_label)
        self.youtube_input = QTextEdit(self)
        self.youtube_input.setPlaceholderText("Paste YouTube video/channel URLs here...")
        self.youtube_input.setMinimumHeight(100)
        self.youtube_input.textChanged.connect(self.update_url_count)
        layout.addWidget(self.youtube_input)

        # File selection
        self.file_button = QPushButton('Select Audio Files', self)
        self.file_button.clicked.connect(self.selectFiles)
        layout.addWidget(self.file_button)

        file_list_layout = QHBoxLayout()
        self.file_list_widget = QListWidget()
        self.file_list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.file_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list_widget.setMinimumHeight(150)
        self.file_list_widget.itemSelectionChanged.connect(self.update_file_buttons_state)
        file_list_layout.addWidget(self.file_list_widget, stretch=1)

        move_buttons_layout = QVBoxLayout()
        self.move_up_button = QPushButton('Up')
        self.move_up_button.clicked.connect(self.move_file_up)
        self.move_up_button.setEnabled(False)
        move_buttons_layout.addWidget(self.move_up_button)

        self.move_down_button = QPushButton('Down')
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

        self.file_label = QLabel("Selected files: None", self)
        layout.addWidget(self.file_label)

        self.dir_button = QPushButton('Select Directory', self)
        self.dir_button.clicked.connect(self.selectDirectory)
        layout.addWidget(self.dir_button)

        self.dir_label = QLabel("Selected directory: None", self)
        layout.addWidget(self.dir_label)

        self.run_button = QPushButton('Run Transcription', self)
        self.run_button.clicked.connect(self.runTranscription)
        layout.addWidget(self.run_button)

        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)
        layout.addWidget(QLabel("Log Output:"))
        layout.addWidget(self.log_output)

        self.setLayout(layout)
        self.setWindowTitle('WhisperSubs - Transcription App')

    def _populate_adapter_combo(self):
        """Populate adapter/provider filter combo."""
        self._all_adapter_items = ["All Providers"]
        try:
            import model as _m
            ctx = _m.get_context()
            for info in ctx.list_available_adapters():
                prefix = info['prefix']
                if prefix == '(local/faster-whisper)':
                    self._all_adapter_items.append("Local (faster-whisper)")
                else:
                    label = _PROVIDER_LABELS.get(prefix, prefix.upper())
                    avail = " [unavailable]" if not info['available'] else ""
                    self._all_adapter_items.append(f"{label}{avail}")
        except Exception:
            self._all_adapter_items.extend(["Local (faster-whisper)", "Groq", "HuggingFace", "Deepgram"])
        self.adapter_combo.addItems(self._all_adapter_items)

    def _on_adapter_filter_changed(self):
        """Re-populate model combo when adapter filter changes."""
        self._populate_model_combo()

    def _populate_model_combo(self):
        """Populate model combo with grouped providers, optionally filtered."""
        current = self.model_combo.currentText()
        self.model_combo.clear()

        filter_index = self.adapter_combo.currentIndex()
        show_all = filter_index == 0

        grouped = get_flat_display_list()
        if show_all:
            self.model_combo.addItems(grouped)
        else:
            adapter_name = self._all_adapter_items[filter_index] if filter_index < len(self._all_adapter_items) else ""
            adapter_name_clean = adapter_name.replace(" [unavailable]", "")
            in_section = False
            for item in grouped:
                if _is_sep(item):
                    in_section = adapter_name_clean in item
                    if in_section:
                        self.model_combo.addItems([item])
                    continue
                if in_section:
                    self.model_combo.addItems([item])

        self.model_combo.setItemDelegate(SeparatorDelegate(self.model_combo))

        if current:
            idx = self.model_combo.findText(current)
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
            elif not _is_sep(current):
                self.model_combo.setCurrentText(current)
        elif self.model_combo.count() > 1:
            for i in range(self.model_combo.count()):
                if not _is_sep(self.model_combo.itemText(i)):
                    self.model_combo.setCurrentIndex(i)
                    break

    def _get_selected_model(self) -> str:
        """Get the currently selected model, skipping separators."""
        text = self.model_combo.currentText()
        if _is_sep(text):
            for i in range(self.model_combo.currentIndex() + 1, self.model_combo.count()):
                candidate = self.model_combo.itemText(i)
                if not _is_sep(candidate):
                    return candidate
            return ""
        return text

    def setup_system_tray(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = QSystemTrayIcon(self)
        app_icon = QIcon.fromTheme("audio-x-generic")
        if app_icon.isNull():
            pixmap = QPixmap(32, 32)
            pixmap.fill(QColor(59, 66, 82))
            app_icon = QIcon(pixmap)
            self.tray_icon.setIcon(app_icon)

            tray_menu = QMenu()
            show_action = QAction("Show Window", self)
            show_action.triggered.connect(self.show_normal)
            tray_menu.addAction(show_action)

            hide_action = QAction("Hide Window", self)
            hide_action.triggered.connect(self.hide_window)
            tray_menu.addAction(hide_action)

            tray_menu.addSeparator()

            quit_action = QAction("Quit", self)
            quit_action.triggered.connect(self.quit_app)
            tray_menu.addAction(quit_action)

            self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)

        self.tray_icon.show()

    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_normal()

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def hide_window(self):
        self.hide()

    def quit_app(self):
        self.save_settings()
        QApplication.quit()

    def closeEvent(self, event):
        if hasattr(self, 'enable_tray_check') and self.enable_tray_check.isChecked():
            transcription_running = hasattr(self, 'transcription_thread') and self.transcription_thread and self.transcription_thread.isRunning()

            if transcription_running:
                self.hide()
                event.ignore()
            else:
                reply = QMessageBox.question(
                    self,
                    'Minimize to Tray',
                    'No transcription is currently running. Would you like to minimize to tray instead of closing?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )

                if reply == QMessageBox.StandardButton.Yes:
                    self.hide()
                    event.ignore()
                else:
                    self.save_settings()
                    super().closeEvent(event)
        else:
            self.save_settings()
            super().closeEvent(event)

    def selectFiles(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files",
            "",
            "Media Files (*.mkv *.mp3 *.wav *.flac *.ogg *.m4a *.aac)"
        )

        if files:
            if hasattr(self, 'sort_files_check') and self.sort_files_check.isChecked():
                try:
                    from natsort import natsorted
                    new_files = natsorted(files, key=lambda x: x.lower())
                except ImportError:
                    new_files = sorted(files, key=lambda x: x.lower())
            else:
                new_files = files

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
        count = len(self.selected_files)
        if count == 0:
            self.file_label.setText("Selected files: None")
        elif count == 1:
            self.file_label.setText("Selected files: 1 file")
        else:
            self.file_label.setText(f"Selected files: {count} files")

    def toggle_temperature_slider(self, state):
        is_auto = self.temperature_auto_check.isChecked()
        self.temperature_slider.setEnabled(not is_auto)
        if is_auto:
            self.temperature_value_label.setText("None")

    def update_temperature_label(self, value):
        temp = value / 10.0
        self.temperature_value_label.setText(f"{temp:.1f}")

    def update_file_buttons_state(self):
        selected_items = self.file_list_widget.selectedItems()
        selected_count = len(selected_items)
        current_row = self.file_list_widget.currentRow()
        total_count = self.file_list_widget.count()

        self.remove_button.setEnabled(selected_count > 0)
        self.clear_all_button.setEnabled(total_count > 0)

        if selected_count == 1:
            self.move_up_button.setEnabled(current_row > 0)
            self.move_down_button.setEnabled(current_row < self.file_list_widget.count() - 1)
        else:
            self.move_up_button.setEnabled(False)
            self.move_down_button.setEnabled(False)

    def move_file_up(self):
        current_row = self.file_list_widget.currentRow()
        if current_row > 0:
            self.selected_files[current_row], self.selected_files[current_row - 1] = \
                self.selected_files[current_row - 1], self.selected_files[current_row]

            current_item = self.file_list_widget.takeItem(current_row)
            self.file_list_widget.insertItem(current_row - 1, current_item)
            self.file_list_widget.setCurrentRow(current_row - 1)
            self.update_file_label()

    def move_file_down(self):
        current_row = self.file_list_widget.currentRow()
        if 0 <= current_row < self.file_list_widget.count() - 1:
            self.selected_files[current_row], self.selected_files[current_row + 1] = \
                self.selected_files[current_row + 1], self.selected_files[current_row]

            current_item = self.file_list_widget.takeItem(current_row)
            self.file_list_widget.insertItem(current_row + 1, current_item)
            self.file_list_widget.setCurrentRow(current_row + 1)
            self.update_file_label()

    def remove_selected_files(self):
        selected_items = self.file_list_widget.selectedItems()
        for item in selected_items:
            row = self.file_list_widget.row(item)
            self.file_list_widget.takeItem(row)
            if 0 <= row < len(self.selected_files):
                self.selected_files.pop(row)

        self.update_file_label()
        self.update_file_buttons_state()

    def clear_all_files(self):
        self.file_list_widget.clear()
        self.selected_files = []
        self.update_file_label()
        self.update_file_buttons_state()

    def selectDirectory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            self.selected_directory = directory
            self.dir_label.setText(f"Selected directory: {directory}")

            media_extensions = {'.mkv', '.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.wma'}
            dir_files = []
            for file in sorted(os.listdir(directory)):
                if os.path.splitext(file)[1].lower() in media_extensions:
                    full_path = os.path.join(directory, file)
                    if full_path not in self.selected_files:
                        dir_files.append(full_path)

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
        self.save_settings()

        model_name = self._get_selected_model()

        device = 'cuda' if self.gpu_radio.isChecked() else 'cpu'
        force_device = self.force_device_check.isChecked()
        compute = self.compute_combo.currentText().split(' ')[0]

        start_time = self.start_time.text().strip() or None
        end_time = self.end_time.text().strip() or None

        files_to_process = list(self.selected_files)

        if self.selected_directory:
            for f in os.listdir(self.selected_directory):
                if f.lower().endswith(('.mkv', '.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac')):
                    full_path = os.path.join(self.selected_directory, f)
                    if full_path not in files_to_process:
                        files_to_process.append(full_path)

        if hasattr(self, 'sort_files_check') and self.sort_files_check.isChecked():
            try:
                from natsort import natsorted
                files_to_process = natsorted(files_to_process, key=lambda x: os.path.basename(x).lower())
            except ImportError:
                files_to_process.sort(key=lambda x: os.path.basename(x).lower())

        youtube_urls = self.youtube_input.toPlainText().strip()

        if not files_to_process and not youtube_urls:
            QMessageBox.warning(self, "Error", "No files, directory, or YouTube URLs selected.")
            return

        self.run_button.setEnabled(False)
        self.log_output.clear()

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

        if hasattr(self, 'auto_hide_check') and self.auto_hide_check.isChecked():
            self.hide()

        self.transcription_thread.start(QThread.Priority.LowPriority)

    def on_transcription_finished(self):
        self.log("Transcription process completed!")
        self.run_button.setEnabled(True)

    def on_transcription_error(self, error_message):
        self.log(f"Error during transcription: {error_message}")
        self.run_button.setEnabled(True)

    def toggle_clipboard_monitoring(self):
        self.clipboard_monitoring = not self.clipboard_monitoring
        self.clipboard_toggle.setText(
            f'Clipboard Monitoring: {"ON" if self.clipboard_monitoring else "OFF"}'
        )
        if self.clipboard_monitoring:
            self.clipboard_timer.start()
        else:
            self.clipboard_timer.stop()

    def check_clipboard(self):
        if not self.clipboard_monitoring:
            return

        try:
            current_clipboard = pyperclip.paste()
            if current_clipboard == self.last_clipboard:
                return

            self.last_clipboard = current_clipboard

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
        current_urls = set(self.youtube_input.toPlainText().split('\n'))
        current_urls.discard('')

        added = False
        for url in new_urls:
            if url not in current_urls:
                current_urls.add(url)
                added = True

        if added:
            self.youtube_input.setPlainText('\n'.join(sorted(current_urls)))
            self.log(f"Added {len(new_urls)} new YouTube URL(s) from clipboard")

    def clear_youtube_urls(self):
        self.youtube_input.clear()
        self.update_url_count()

    def update_url_count(self):
        urls = [url for url in self.youtube_input.toPlainText().split('\n') if url.strip()]
        self.url_count_label.setText(f"{len(urls)} URLs")

    def resort_urls(self):
        urls = [url for url in self.youtube_input.toPlainText().split('\n') if url.strip()]
        if not urls:
            return

        if self.reverse_order_check.isChecked():
            urls.reverse()

        self.youtube_input.setPlainText('\n'.join(urls))

    def select_cookie_file(self):
        cookie_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Cookie File",
            "",
            "Cookie Files (*.txt);;All Files (*.*)"
        )

        if cookie_file:
            self.cookie_file_path.setText(cookie_file)
            self.use_cookies_check.setChecked(True)

    def _set_env_key(self, env_var: str, value: str):
        os.environ[env_var] = value
        self.log(f"Set {env_var} ({'****' if value else 'empty'})")

    def save_settings(self):
        settings = {
            'model': self._get_selected_model(),
            'adapter_filter': self.adapter_combo.currentIndex(),
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
            'process_priority': self.priority_combo.currentText(),
            'temperature_auto': self.temperature_auto_check.isChecked(),
            'temperature_value': self.temperature_slider.value(),
            'force': self.force_check.isChecked(),
            'replace_subs': self.replace_subs_check.isChecked(),
            'backup_subs': self.backup_subs_check.isChecked(),
            'retry': self.retry_check.isChecked(),
            'api_keys': {k: v.text() for k, v in self._api_key_fields.items()},
        }

        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            self.log(f"Error saving settings: {str(e)}")

    def load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            else:
                return

            if 'model' in settings:
                index = self.model_combo.findText(settings['model'])
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
                elif settings['model']:
                    self.model_combo.setCurrentText(settings['model'])

            if 'adapter_filter' in settings:
                idx = settings['adapter_filter']
                if 0 <= idx < self.adapter_combo.count():
                    self.adapter_combo.setCurrentIndex(idx)

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
                self.file_list_widget.clear()
                for file in self.selected_files:
                    self.file_list_widget.addItem(file)
                self.update_file_label()
                self.update_file_buttons_state()

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

            if 'cpu_threads' in settings:
                index = self.thread_combo.findText(settings['cpu_threads'])
                if index >= 0:
                    self.thread_combo.setCurrentIndex(index)

            if 'process_priority' in settings:
                index = self.priority_combo.findText(settings['process_priority'])
                if index >= 0:
                    self.priority_combo.setCurrentIndex(index)

            if 'temperature_auto' in settings:
                self.temperature_auto_check.setChecked(settings['temperature_auto'])
            if 'temperature_value' in settings:
                self.temperature_slider.setValue(settings['temperature_value'])
                temp = settings['temperature_value'] / 10.0
                self.temperature_value_label.setText(f"{temp:.1f}")
                self.toggle_temperature_slider(None)

            if 'force' in settings:
                self.force_check.setChecked(settings['force'])
            if 'replace_subs' in settings:
                self.replace_subs_check.setChecked(settings['replace_subs'])
            if 'backup_subs' in settings:
                self.backup_subs_check.setChecked(settings['backup_subs'])
            if 'retry' in settings:
                self.retry_check.setChecked(settings['retry'])

            if 'api_keys' in settings:
                for env_var, value in settings['api_keys'].items():
                    if env_var in self._api_key_fields and value:
                        self._api_key_fields[env_var].setText(value)
                        os.environ[env_var] = value

        except Exception as e:
            self.log(f"Error loading settings: {str(e)}")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    font = app.font()
    font.setPointSize(10)
    app.setFont(font)

    window = TranscriptionApp()
    window.show()
    sys.exit(app.exec())
