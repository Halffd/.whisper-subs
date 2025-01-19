import sys
import model
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLineEdit, QFileDialog, QLabel, QMessageBox

class MinimalApp(QWidget):
    def __init__(self):
        super().__init__()
        
        self.initUI()
        
    def initUI(self):
        layout = QVBoxLayout()

        # Input box for numbers
        self.number_input = QLineEdit(self)
        self.number_input.setPlaceholderText("Enter a number")
        layout.addWidget(self.number_input)

        # Button to open the file picker
        self.file_button = QPushButton('Open File Picker', self)
        self.file_button.clicked.connect(self.showFilePicker)
        layout.addWidget(self.file_button)

        # Label to display selected file
        self.file_label = QLabel("Selected file: None", self)
        layout.addWidget(self.file_label)

        # Run button
        self.run_button = QPushButton('Run', self)
        self.run_button.clicked.connect(self.runAction)
        layout.addWidget(self.run_button)

        self.setLayout(layout)
        
        self.setWindowTitle('Minimal GUI Example')
        self.setGeometry(100, 100, 300, 200)
        
    def showFilePicker(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(self, "Select a file", "", "All Files (*);;Text Files (*.txt)", options=options)
        if file_name:
            self.file_label.setText(f'Selected file: {file_name}')

    def runAction(self):
        number_text = self.number_input.text()
        selected_file = self.file_label.text().replace('Selected file: ', '')

        if not number_text.isdigit():
            QMessageBox.warning(self, "Input Error", "Please enter a valid number.")
            return
        
        if selected_file == "None":
            QMessageBox.warning(self, "File Error", "Please select a file before running.")
            return

        # Example action: Show a message box with the input number and selected file
        QMessageBox.information(self, "Run Action", f"Number: {number_text}\nSelected File: {selected_file}")

default = 'small'
print(sys.argv)
args = model.getName(sys.argv, default)
if type(args) == dict:
    model_name = args['model_name']
    lang = args['lang']
else:
    model_name = args
import os
from pathlib import Path
import ffmpeg
from tkinter import Tk, filedialog
import transcribe
import subprocess
import datetime
import pymkv

fn = ''
def write(text, mpv = 'err'):
    global fn
    print(text)
    with open(file=fn, mode='a', encoding="utf-8") as f:
        try:
            f.write(f"{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')} :  {str(text)}\n")
            if mpv != 'err':
                f.write(f"{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')} :  {str(mpv)}\n")
        except UnicodeEncodeError:
            print(f"Warning: Could not write all characters to the file. Skipping problematic characters.")
            f.write('\n' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ' : ' + mpv.encode('ascii', 'ignore').decode('ascii'))
        except Exception as e:
            print(e)
            f.write(e + '\n')
def select_directory():
    root = Tk()
    root.withdraw()  # Hide the root window
    directory = filedialog.askdirectory()  # Open a dialog to select a directory
    return directory

def list_media_files(directory):
    media_files = []
    
    # List all files in the directory
    for filename in os.listdir(directory):
        if filename.endswith('.mkv') or filename.endswith('.mp3'):
            media_files.append(filename)
    
    # Sort the combined list
    media_files.sort()

    return media_files
def convert_mkv_to_mp3(mkv_path, output_mp3):
    """
    Extracts the Japanese audio track if available, otherwise undefined ('und'), or defaults to the first audio track.
    Converts the selected audio track to MP3.

    Args:
        mkv_path (str): Path to the MKV file.
        output_mp3 (str): Path for the output MP3 file.

    Returns:
        None
    """
    try:
        # Load the MKV file
        mkv = pymkv.MKVFile(mkv_path)

        audio_track_id = None

        # Check for Japanese audio track first
        for track in mkv.tracks:
            if track.track_type == 'audio' and track.language == 'jpn':
                audio_track_id = track.track_id
                break

        # Check for undefined audio track if Japanese is not found
        if audio_track_id is None:
            for track in mkv.tracks:
                if track.track_type == 'audio' and track.language == 'und':
                    audio_track_id = track.track_id
                    break

        # Default to the first audio track if no Japanese or undefined tracks are found
        if audio_track_id is None:
            for track in mkv.tracks:
                if track.track_type == 'audio':
                    audio_track_id = track.track_id
                    break

        if audio_track_id is None:
            raise ValueError("No audio tracks found in the MKV file.")

        # Extract the audio track to MP3
        command = [
            "ffmpeg", "-y", "-i", mkv_path,
            "-map", f"0:{audio_track_id}", "-c:a", "libmp3lame", output_mp3
        ]
        print(f"Running command: {' '.join(command)}")
        subprocess.run(command, check=True)
        print(f"Audio extracted and converted to MP3: {output_mp3}")

    except Exception as e:
        print(f"Error processing file {mkv_path}: {e}")

def process(file):
    global model_name
    srt_file = os.path.splitext(file)[0] + "." + model_name + ".srt"
    write(srt_file)
    segments = 'segments.json'
    transcribe.process_create(file, model_name, srt_file, segments, write=write)
    
if __name__ == "__main__":
    # Prompt the user to select one or more audio/video files
    app = QApplication(sys.argv)
    minimal_app = MinimalApp()
    minimal_app.show()
    files = [] #[input('File: ')]
   #select_directory()
    selection = 'files'
    if selection == 'directory':
        directory = 
        os.chdir(directory)
        if directory:
            files = list_media_files(directory)
            print("Media Files:")
            i=0
            for file in files:
                print(f"  - {files[i]}")
                i+=1
        else:
            print("No directory selected.")
    #filedialog.askopenfilenames(title="Select one or more files", filetypes=[("Audio/Video files", "*.mkv;*.wav;*.mp3;*.flac;*.ogg")])

    # Process each selected file
    for i, file in enumerate(files):
        file = os.path.join(directory, file)
        file_ext = os.path.splitext(file)[1]
        if fn == '':
            fn = os.path.splitext(file)[0] + '.log'
        write(' '.join(['------ ', file, ' ', str(i+1), '/', str(len(files))]))
        if file_ext == ".mkv":
            # Convert MKV to MP3
            mp3_file = os.path.splitext(file)[0] + ".mp3"
            print(file, '\n', mp3_file)
            convert_mkv_to_mp3(file, mp3_file)
            
            process(mp3_file)
        else:
            # Transcribe audio files using faster_whisper
            process(file)
    sys.exit(app.exec_())


