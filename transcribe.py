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
def transcribe_audio(audio_file, model_name, language=None, device='cuda', compute='int8_float32', json_file="segments.json"):
    """ 
    Transcribe audio and yield segments while writing to a JSON file in real-time.
 
    Args:
        audio_file (str): Path to the audio file.
        model_name (str): The Whisper model name to use.
        language (str, optional): Language code. Defaults to None.
        device (str, optional): Device to run the model on ('cuda' or 'cpu'). Defaults to 'cuda'.
        compute (str, optional): Compute type. Defaults to 'int8_float32'.
        json_file (str, optional): Path to save the JSON file with segments. Defaults to 'segments.json'.
    
    Yields:
        dict: The transcription segment as a dictionary with start, end, and text keys.
    """
    whisper_model = faster_whisper.WhisperModel(model_name, device=device, compute_type=compute)
    
    segments = []
    
    try:
        if language:
            result_segments, _ = whisper_model.transcribe(audio_file, language=language)
        else:
            result_segments, _ = whisper_model.transcribe(audio_file)
        
        # Process each segment
        for segment in result_segments:
            segment_data = {
                'start': segment.start,
                'end': segment.end,
                'text': segment.text
            }
            segments.append(segment_data)
            
            # Write each segment to the JSON file
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(segments, f, indent=4, ensure_ascii=False)
            
            # Yield the segment for further processing
            yield segment_data

    except Exception as e:
        print(f"Error during transcription: {e}", file=sys.stderr)
        return None
def read_segments_from_json(json_file: str) -> List[Segment]:
    """Reads the JSON file and converts it to a list of Segment objects."""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [Segment(**segment) for segment in data]
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error reading JSON file: {e}", file=sys.stderr)
        return []
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
# Save SRT file incrementally as audio is being transcribed
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
                    args = [sys.executable, __file__, file, model_name, language, segments_file , device, compute]
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

                        with open(srt_temp_file, "w", encoding="utf-8") as srt:
                            while process.poll() is None:
                                write_srt(segments_file, srt)
                                # Read stderr output for errors
                                while not stderr_queue.empty():
                                    error_msg = stderr_queue.get()
                                    print(f"Error: {error_msg}", file=sys.stderr)

                                # Read stdout output and write to SRT incrementally
                                while not stdout_queue.empty():
                                    output = stdout_queue.get()
                                    if output:
                                        write(f"Out : {output}")
                                time.sleep(5)

                        # Finalize and rename the SRT file
                        os.rename(srt_temp_file, srt_file)
                        write(f"SRT file completed: {srt_file}")

                    finally:
                        stdout_thread.join()
                        stderr_thread.join()

                        stdout, stderr = process.communicate()
                        exit_code = process.returncode

                        if exit_code != 0:
                            write(f"Process exited with error: {stderr}", file=sys.stderr)
                        else:
                            with open(srt_file, 'w') as srt:
                                write_srt(segments_file, srt)
                            os.remove(segments_file)
                            return
                except Exception as e:
                    write(f"An error occurred on creation: {e}")
    else:
        write('No model')

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

    path, file, model_name, language, segments_file = sys.argv[0], sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    if language == 'none':
        language = None
    device = sys.argv[5] if len(sys.argv) > 4 else 'cuda'
    compute = sys.argv[6] if len(sys.argv) > 5 else 'int8_float32'
    
    print(f"{path}: Transcribing {file} using model {model_name} and language {language}", file=sys.stderr)
    
    result = transcribe_audio(file, model_name, language, device, compute, segments_file)
    
    if result is None:
        raise RuntimeError("Transcription failed")
    
    # Convert segments to a list of dictionaries
    segments_dict = [
        {'start': segment['start'], 'end': segment['end'], 'text': segment['text']}
        for segment in result
    ]
   
    # Save to a file with error handling
    try:
        with open(segments_file, 'w', encoding='utf-8') as file:
            json.dump(segments_dict, file, ensure_ascii=False)  # Write the JSON data
        print("Data successfully saved to segments.json")
    except IOError as e:
        print(f"Error saving to file: {e}")
    print(segments_dict)

"""def save_srt_file(audio_file, model_name, srt_file="subtitles.srt", language=None, device='cuda', compute='int8_float32'):
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(srt_file), exist_ok=True)

    # Prepare file paths
    original = srt_file
    srt_file = srt_file.replace(".srt", "-unfinished.srt")

    # Open the SRT file to write
    with open(srt_file, "w", encoding="utf-8") as f:
        segments = []
        for i, segment in enumerate(transcribe_audio(audio_file, model_name, language, device, compute), start=1):
            # Extract segment data
            start_time = segment['start']
            end_time = segment['end']
            text = segment['text'].strip()

            # Write the segment to the SRT file
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}\n")
            f.write(f"{text}\n\n")

            print(f"Segment {i} saved to {srt_file}: [{start_time} - {end_time}] {text}")
    # Once the transcription is done, rename the file to its final name
    os.rename(srt_file, original)
    print(f"SRT file completed: {original}")
"""