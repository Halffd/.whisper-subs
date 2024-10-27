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
logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)
done = False
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
def transcribe_audio(audio_file, model_name, srt_file="file.srt", language=None, device='cuda', compute='int8_float32'):
    """  
    Transcribe audio and yield segments in real-time.
    
    Args:
        audio_file (str): Path to the audio file.
        model_name (str): The Whisper model name to use.
        language (str, optional): Language code. Defaults to None.
        device (str, optional): Device to run the model on ('cuda' or 'cpu'). Defaults to 'cuda'.
        compute (str, optional): Compute type. Defaults to 'int8_float32'.
    
    Yields:         
        dict: The transcription segment as a dictionary with start, end, and text keys.
    """
    global done
    done = False
    original = srt_file
    srt_file = srt_file.replace('.srt','-unfinished.srt')

    with open(srt_file, "w", encoding="utf-8") as srt:
        whisper_model = faster_whisper.WhisperModel(model_name, device=device, compute_type=compute)

        try:
            result_segments, _ = whisper_model.transcribe(audio_file, language=language)
            
            for i, segment in enumerate(result_segments, start=1):
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)

                # Write each segment to the SRT file
                srt.write(f"{i}\n")
                srt.write(f"{start_time} --> {end_time}\n")
                srt.write(f"{segment.text}\n\n")

                srt.flush()  # Ensure everything is written out
        except Exception as e:
            print(f"Error during transcription: {e}", file=sys.stderr)
            return None
    os.rename(srt_file, original)
    done = True

def format_timestamp(timestamp):
    """
    Formats a timestamp in seconds to the HH:MM:SS,mmm format for SRT.

    Args:
        timestamp (float): The timestamp in seconds.

    Returns:
        str: The formatted timestamp in SRT format.
    """
    hours = int(timestamp // 3600)
    minutes = int(timestamp % 3600 // 60)
    seconds = int(timestamp % 60)
    milliseconds = int((timestamp % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
def read_segments_from_json(json_file: str) -> List[Segment]:
    """Reads the JSON file and converts it to a list of Segment objects."""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [Segment(**segment) for segment in data]
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error reading JSON file: {e}", file=sys.stderr)
        return []
def write_srt(segments_file, srt):
    if os.path.exists(segments_file):
        # Read the JSON segments file to fetch transcribed segments
        segments = read_segments_from_json(segments_file)
        for i, segment in enumerate(segments, start=1):
            start_time = format_timestamp(segment.start)
            end_time = format_timestamp(segment.end)
            text = segment.text.strip()

            # Write the segment to the SRT file
            srt.write(f"{i}\n")
            srt.write(f"{start_time} --> {end_time}\n")
            srt.write(f"{text}\n\n")                                        
def process_create(file, model_name, srt_file = 'none', segments_file = 'segments.json', language = 'none', device = 'cuda', compute = 'int8_float32', write = print):
    """Creates a new process to retry the transcription."""
    global done
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
                if c == 1 or 'large-' in model_name:
                    device = 'cpu'
                if c == 2:
                    compute = 'int8'
                    if model_name == 'large-v3':
                        model_name = 'large-v2'
                try:
                    write(' '.join([str(i), str(j), str(c), compute, device, language]))
                    write(model_name)
                    write(f"Starting subprocess with model: {model_name}")
                    args = [sys.executable, __file__, file, model_name, language, srt_file, device, compute]
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

                     # Reading the subprocess output and updating JSON and SRT files
                    try:
                        srt_temp_file = srt_file.replace(".srt", "-unfinished.srt")

                        while process.poll() is None:
                            # Read stderr output for errors
                            while not stderr_queue.empty():
                                error_msg = stderr_queue.get()
                                print(f"Error: {error_msg}", file=sys.stderr)

                            # Read stdout output and write to SRT incrementally
                            while not stdout_queue.empty():
                                output = stdout_queue.get()
                                if output:
                                    write(f"Out : {output}")
                            time.sleep(1)
                    finally:
                        stdout_thread.join()
                        stderr_thread.join()

                        stdout, stderr = process.communicate()
                        exit_code = process.returncode

                        if exit_code != 0 and not done:
                            write(f"Process exited {str(exit_code)} with error: {stderr}")
                        else:
                            #with open(srt_file, 'w') as srt:
                            #    write_srt(segments_file, srt)
                            #os.remove(segments_file)
                            return
                except Exception as e:
                    write(f"An error occurred on creation: {e}")
    else:
        write('No model')
def write_srt_from_segments(segments, srt):
    """Writes the transcription segments to an SRT file."""
    for i, segment in enumerate(segments, start=1):
        start_time = format_timestamp(segment.start)
        end_time = format_timestamp(segment.end)

        # Write each segment to the SRT file
        srt.write(f"{i}\n")
        srt.write(f"{start_time} --> {end_time}\n")
        srt.write(f"{segment.text}\n\n")

if __name__ == "__main__":
    if sys.argv[1] == '--write-srt':
        json_file = sys.argv[2]
        srt_file = sys.argv[3]
        if not ':' in json_file or not ':' in srt_file:
            subs_dir = "Documents\\Youtube-Subs"
            if not ':' in json_file:
                json_file = os.path.join(os.path.expanduser("~"), subs_dir, json_file)
            if not ':' in srt_file:
                srt_file = os.path.join(os.path.expanduser("~"), subs_dir, srt_file)
        with open(srt_file, mode='w', encoding='utf-8') as srt:
            write_srt(json_file, srt)
        sys.exit(0)
    elif len(sys.argv) < 5:
        print("Usage: python script.py <audio_file> <model_name> <language> <device> <compute>")
        sys.exit(1)
    audio_file = sys.argv[1]
    model_name = sys.argv[2]
    language = sys.argv[3] if sys.argv[3] != 'none' else None
    srt_file = sys.argv[4] if len(sys.argv) > 6 else 'transcription.srt'
    device = sys.argv[5] if len(sys.argv) > 4 else 'cuda'
    compute = sys.argv[6] if len(sys.argv) > 5 else 'int8_float32'

    print(f"Transcribing {audio_file} using model {model_name} and language {language}", file=sys.stderr)

    # Call the transcribe_audio generator
    transcribe_audio(audio_file, model_name, srt_file, language, device, compute)