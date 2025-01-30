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

MODEL_NAMES = [
    "tiny", "base", "small", "medium", "large", "large-v2", "large-v3",
    "tiny.en", "base.en", "small.en", "medium.en",
    "jlondonobo/whisper-medium-pt",
    "clu-ling/whisper-large-v2-japanese-5k-steps",
    "distil-whisper/distil-medium.en", "distil-whisper/distil-small.en",
    "distil-whisper/distil-base", "distil-whisper/distil-small",
    "distil-whisper/distil-medium", "distil-whisper/distil-large",
    "distil-whisper/distil-large-v2", "distil-whisper/distil-large-v3",
    "Systran/faster-distil-medium", "Systran/faster-distil-large",
    "Systran/faster-distil-large-v2", "Systran/faster-distil-large-v3",
    "japanese-asr/distil-whisper-large-v3-ja-reazonspeech-large"
]

class TranscriptionApp(QWidget):
    def __init__(self):
        super().__init__()
        self.log_file = None
        self.selected_files = []
        self.selected_directory = None
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        # Model selection dropdown
        self.model_combo = QComboBox(self)
        self.model_combo.addItems(MODEL_NAMES)
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
            self.log(f"Converted {mkv_path} to {output_mp3}")
            return output_mp3
            
        except Exception as e:
            self.log(f"Error converting {mkv_path}: {str(e)}")
            return None

    def processFile(self, file_path, model_name):
        try:
            srt_file = os.path.splitext(file_path)[0] + f".{model_name}.srt"
            segments = 'segments.json'
            self.log(f"Processing {file_path} with model {model_name}...")
            transcribe.process_create(file_path, model_name, srt_file, segments, write=self.log)
            self.log(f"Transcription completed for {file_path}")
        except Exception as e:
            self.log(f"Error processing {file_path}: {str(e)}")

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

        for i, file_path in enumerate(files_to_process, 1):
            self.log(f"Processing file {i}/{len(files_to_process)}: {file_path}")
            
            if file_path.lower().endswith('.mkv'):
                file_path = self.convertMKVtoMP3(file_path)
                
            if file_path:
                self.processFile(file_path, model_name)

        self.log("Transcription process completed!")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TranscriptionApp()
    window.show()
    sys.exit(app.exec_())
