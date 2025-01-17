import sys
import model
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
import datetime

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

def convert_mkv_to_mp3(input_file, output_file):
    """
    Converts an MKV file to an MP3 file using ffmpeg.

    Args:
        input_file (str): Path to the input MKV file.
        output_file (str): Path to the output MP3 file.
    """
    try:
        # Load the input MKV file
        input_stream = ffmpeg.input(input_file)

        # Extract the audio stream and convert it to MP3
        audio_stream = input_stream.audio
        output_stream = ffmpeg.output(audio_stream, output_file, vcodec='libmp3lame')

        # Run the ffmpeg conversion
        ffmpeg.run(output_stream, overwrite_output=True)
        write(f"Conversion successful: {input_file} -> {output_file}")
    except Exception as e:
        write(f"Error converting {input_file}: {e}")
def process(file):
    global model_name
    srt_file = os.path.splitext(file)[0] + "." + model_name + ".srt"
    write(srt_file)
    segments = 'segments.json'
    transcribe.process_create(file, model_name, srt_file, segments, write=write)
    
if __name__ == "__main__":
    # Prompt the user to select one or more audio/video files
    root = Tk()
    root.withdraw()
    files = [] #[input('File: ')]
    directory = select_directory()
    if directory:
        files = list_media_files(directory)
        print("Media Files:")
        for file in files:
            print(f"  - {file}")
    else:
        print("No directory selected.")
    #filedialog.askopenfilenames(title="Select one or more files", filetypes=[("Audio/Video files", "*.mkv;*.wav;*.mp3;*.flac;*.ogg")])

    # Process each selected file
    for i, file in enumerate(files):
        file_ext = os.path.splitext(file)[1].lower()
        if fn == '':
            fn = os.path.splitext(file)[0].lower() + '.log'
        write(' '.join(['------ ', file, ' ', str(i+1), '/', str(len(files))]))
        if file_ext == ".mkv":
            # Convert MKV to MP3
            mp3_file = os.path.splitext(file)[0] + ".mp3"
            convert_mkv_to_mp3(file, mp3_file)
            process(mp3_file)
        else:
            # Transcribe audio files using faster_whisper
            process(file)
