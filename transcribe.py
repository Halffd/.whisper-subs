import model
import faster_whisper
import torch
import logging
import psutil
import time
import sys
import subprocess
import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, List


os.environ["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"

audiofile, modelname, langcode = '', 'base', None
"""
def on_error(exc_type, exc_value, tb):
    global audiofile, modelname, langcode
    import traceback
    traceback.print_exception(exc_type, exc_value, tb)
    print(audiofile, modelname, langcode, '\nrestarting')
    transcribe_audio(audiofile, modelname, langcode)


sys.excepthook = on_error
"""
logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)

@dataclass
class Segment:
    start: float
    end: float
    text: str

def dict_to_segment(data: Dict[str, Any]) -> Segment:
    """Convert a dictionary to a Segment dataclass instance."""
    return Segment(
        start=data.get('start', 0.0),
        end=data.get('end', 0.0),
        text=data.get('text', '')
    )

def convert_dict_to_segments(data: List[Dict[str, Any]]) -> List[Segment]:
    """Convert a list of dictionaries to a list of Segment instances."""
    return [dict_to_segment(item) for item in data]
def read_stream_proc(stream, label, process):
    """Read from the given stream and print its output."""
    while True:
        try:
            output = stream.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(f"{label}: {output.strip()}")
        except Exception as e:
            break

def read_stream(stream, queue):
    """Reads a stream line by line and puts it in a queue."""
    while True:
        line = stream.readline()
        if line:
            queue.put(line)
        else:
            break

def check_memory_usage():
    process = psutil.Process()
    memory_percent = process.memory_percent()
    print(f"{memory_percent}% Memory Usage")
    if memory_percent > 95:  # Check if memory usage is above 90%
        print(f"High memory usage detected ({memory_percent:.1f}%). Waiting...")
        time.sleep(10)  # Wait for 10 seconds
        check_memory_usage()  # Recursively check again
def transcribe_audio(audio_file, model_name, language = None, device = 'cuda', compute = 'int8_float32'):
    """
    Transcribes the audio from the given file using the specified Whisper model.

    Args:
        audio_file (str): Path to the audio file.
        model_name (str): The name of the Whisper model to use.

    Returns:
        The transcription result.
    """
    global audiofile, modelname, langcode
    audiofile = audio_file
    modelname = model_name
    langcode = language
    if device == 'cuda':
        torch.cuda.empty_cache()
    try:
        print(f"Trying model {model_name} on {device}", file=sys.stderr)
        whisper_model = faster_whisper.WhisperModel(model_name, device=device, compute_type=compute)
        if language is not None:
            segments, info = whisper_model.transcribe(audio_file, language=language, vad_filter=True,
                                                      vad_parameters=dict(min_silence_duration_ms=500,
                                                                          max_speech_duration_s=5))
        else:
            segments, info = whisper_model.transcribe(audio_file, vad_filter=True,
                                                      vad_parameters=dict(min_silence_duration_ms=500,
                                                                          max_speech_duration_s=5))
        for segment in segments:
            yield segment
    except RuntimeError as e:
        print(e, file=sys.stderr)   
    except Exception as e:
        print(e, file=sys.stderr)
    return None
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
def save_srt_file(audio_file, model_name, language=None, device='cuda', compute='int8_float32', subs_dir="subtitles"):
    """
    Transcribe audio in real-time and save the SRT file incrementally.

    Args:
        audio_file (str): Path to the audio file.
        model_name (str): The Whisper model name to use.
        language (str, optional): Language code. Defaults to None.
        device (str, optional): Device to run the model on. Defaults to 'cuda'.
        compute (str, optional): Compute type. Defaults to 'int8_float32'.
        subs_dir (str, optional): Directory to save the SRT file. Defaults to "subtitles".
    """
    # Create the SRT file in the appropriate directory
    srt_dir = os.path.join(os.path.expanduser("~"), subs_dir)
    os.makedirs(srt_dir, exist_ok=True)
    
    # Create folder based on the audio file's name
    name = os.path.splitext(os.path.basename(audio_file))[0]
    srt_file = os.path.join(srt_dir, name + "-unfinished.srt")
    
    with open(srt_file, "w", encoding="utf-8") as f:
        # Start transcribing and writing each segment to the SRT file
        for i, segment in enumerate(transcribe_audio(audio_file, model_name, language, device, compute), start=1):
            start_time = segment.start
            end_time = segment.end
            text = segment.text.strip()
            
            # Write the segment to the SRT file
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}\n")
            f.write(f"{text}\n\n")
            
            print(f"Segment {i} saved to {srt_file}: [{start_time} - {end_time}] {text}")
    new = os.path.join(srt_dir, name + ".srt")
    os.rename(srt_file, new)
    print(f"SRT file completed: {srt_file}")

def process_create(file, model_name, language = 'none', device = 'cuda', compute = 'int8_float32', write = print):
    """Creates a new process to retry the transcription."""
    
    # Check if file is None and raise an informative error
    write(file)
    if file is None:
        raise ValueError("The 'file' argument cannot be None. Please provide a valid file path.")
    model_names = model.model_names
    if model_name in model_names:
        i = model_names.index(model_name)
        for j in range(i, -1, -1):
            for c in range(0, 3):
                model_name = model_names[j]
                if c == 1:
                    device = 'cpu'
                elif c == 2:
                    compute = 'int8'
                    if model_name == 'large-v3':
                        model_name = 'large-v2'
                try:
                    write(' '.join([str(i), str(j), str(c), compute, device, language]))
                    write(model_name)
                    write(f"Starting subprocess with model: {model_name}")
                    args = [sys.executable, __file__, file, model_name, language, device, compute]
                    write(args)
                    # Run the subprocess and capture its output
                    # Run the subprocess and capture its output with UTF-8 encoding
                    process = subprocess.Popen(
                        args,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        encoding='utf-8',   # Ensure utf-8 encoding for the output streams
                        errors='replace',   # Replace invalid characters instead of raising an error
                        text=True           # Ensure text mode (no binary reading)
                    )

                    # Use threads to read stdout and stderr concurrently
                    import queue
                    stdout_queue = queue.Queue()
                    stderr_queue = queue.Queue()

                    stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_queue))
                    stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_queue))

                    stdout_thread.start()
                    stderr_thread.start()

                    try:
                        while True:
                            # Check if the process has finished
                            if process.poll() is not None:
                                break  # Process has finished

                            # Check for stderr output and print it
                            while not stderr_queue.empty():
                                output = stderr_queue.get()
                                write(output.strip())

                            # Check for stdout output (if needed)
                            while not stdout_queue.empty():
                                output = stdout_queue.get()
                                write(output.strip())

                            # Sleep briefly to avoid busy-waiting
                            time.sleep(0.1)

                        # Wait for the process to complete and capture any remaining output
                        stdout_thread.join()
                        stderr_thread.join()
                        # Wait for the process to complete and capture any remaining output
                        stdout, stderr = process.communicate()
                        exit_code = process.returncode

                        if exit_code == 0:
                            # Handle empty output
                            try:
                                with open('segments.json', 'r') as file:
                                    loaded_segments = json.load(file)  # Load the JSON data
                                    write("Data successfully loaded from segments.json")
                                    write(loaded_segments)  # Print the loaded segments
                                    return convert_dict_to_segments(loaded_segments)
                            except (IOError, json.JSONDecodeError) as e:
                                write(f"Error reading from file: {e}")
                        else:
                            write(f"Process exited with error code: {exit_code}. Error: {stderr}")
                    except Exception as e:
                        write(f"An error occurred while handling: {e}")
                except Exception as e:
                    write(f"An error occurred on creation: {e}")
    else:
        write('No model')

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python script.py <audio_file> <model_name> <language> <device> <compute>")
        sys.exit(1)

    path, file, model_name, language = sys.argv[0], sys.argv[1], sys.argv[2], sys.argv[3]
    if language == 'none':
        language = None
    device = sys.argv[4] if len(sys.argv) > 4 else 'cuda'
    compute = sys.argv[5] if len(sys.argv) > 5 else 'int8_float32'
    
    print(f"{path}: Transcribing {file} using model {model_name} and language {language}", file=sys.stderr)
    
    result = transcribe_audio(file, model_name, language, device, compute)
    
    if result is None:
        raise RuntimeError("Transcription failed")
    
    # Convert segments to a list of dictionaries
    segments_dict = [
        {'start': segment.start, 'end': segment.end, 'text': segment.text}
        for segment in result
    ]
    
    # Save to a file with error handling
    try:
        with open('segments.json', 'w') as file:
            json.dump(segments_dict, file)  # Write the JSON data
        print("Data successfully saved to segments.json")
    except IOError as e:
        print(f"Error saving to file: {e}")
    print(segments_dict)