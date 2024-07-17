import os
from pathlib import Path
import ffmpeg
from tkinter import Tk, filedialog
import whisperx
import torch

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
        ffmpeg.run(output_stream)
        print(f"Conversion successful: {input_file} -> {output_file}")
    except Exception as e:
        print(f"Error converting {input_file}: {e}")

def transcribe_audio(audio_file):
    """
    Transcribes the audio from the given file using the Whisper model.

    Args:
        audio_file (str): Path to the audio file.

    Returns:
        The transcription result.
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisperx.load_model("base", device=device, compute_type="int8")
    result = model.transcribe(audio_file, language="ja")
    return result

def format_timestamp(timestamp):
    """
    Formats a timestamp in seconds to the HH:MM:SS.xxx format.

    Args:
        timestamp (float): The timestamp in seconds.

    Returns:
        The formatted timestamp.
    """
    hours = int(timestamp // 3600)
    minutes = int(timestamp % 3600 // 60)
    seconds = timestamp % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"

if __name__ == "__main__":
    # Prompt the user to select one or more audio/video files
    root = Tk()
    root.withdraw()
    files = filedialog.askopenfilenames(title="Select one or more files", filetypes=[("Audio/Video files", "*.mkv;*.wav;*.mp3;*.flac;*.ogg")])

    # Process each selected file
    for file in files:
        file_ext = os.path.splitext(file)[1].lower()
        if file_ext == ".mkv":
            # Convert MKV to MP3
            mp3_file = os.path.splitext(file)[0] + ".mp3"
            convert_mkv_to_mp3(file, mp3_file)
        else:
            # Transcribe audio files using Whisper
            result = transcribe_audio(file)
            srt_file = os.path.splitext(file)[0] + ".srt"
            with open(srt_file, "w", encoding="utf-8") as f:
                for i, segment in enumerate(result.segments, start=1):
                    start_time = segment.start.total_seconds()
                    end_time = segment.end.total_seconds()
                    text = segment.text.strip()
                    f.write(f"{i}\n")
                    f.write(f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}\n")
                    f.write(f"{text}\n\n")
                print(f"SRT file saved: {srt_file}")