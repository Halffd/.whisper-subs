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
def transcribe_audio(audio_file, model_name, srt_file="file.srt", language=None, device='cpu', compute='int8'):
    """  
    Modified to default to CPU for large models
    
    Performance tips for CPU processing:
    - Use int8 quantization for CPU processing
    - Increase CPU threads (set cpu_threads to match your CPU core count)
    - Use smaller chunk sizes (20-30 seconds)
    - Enable VAD (Voice Activity Detection) to skip silent parts
    - Consider using distilled models (they're smaller but still effective)
    
    Recommended models for your system:
    - Use distil-whisper/distil-large-v2 for CPU processing
    - Use small or distil-whisper/distil-small.en for GPU processing
    - Enable all CPU optimizations
    - Process files in smaller chunks (20-30 seconds)
    """
    global done
    done = False
    original = srt_file
    temp_srt = srt_file.replace('.srt','-unfinished.srt')

    # Automatically switch to CPU for large models
    if any(large_model in model_name for large_model in ['large', 'medium']):
        device = 'cpu'
        compute = 'int8'
        print(f"Using CPU for {model_name} model due to GPU memory constraints")

    try:
        torch.cuda.empty_cache()
        
        whisper_model = faster_whisper.WhisperModel(
            model_name, 
            device=device, 
            compute_type=compute,
            device_index=0,
            cpu_threads=4  # Use more CPU threads for better performance
        )
        
        # Process in smaller chunks
        result_segments, _ = whisper_model.transcribe(
            audio_file, 
            language=language,
            vad_filter=True,
            chunk_size=20  # Smaller chunks for CPU processing
        )
        
        # Write to temporary file first
        with open(temp_srt, "w", encoding="utf-8") as srt:
            for i, segment in enumerate(result_segments, start=1):
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
                srt.write(f"{i}\n")
                srt.write(f"{start_time} --> {end_time}\n")
                srt.write(f"{segment.text}\n\n")
                srt.flush()

        # Only rename if the temporary file was created successfully
        if os.path.exists(temp_srt):
            if os.path.exists(original):
                os.remove(original)
            os.rename(temp_srt, original)
            done = True
            return True
        
    except RuntimeError as e:
        if 'CUDA out of memory' in str(e):
            print("CUDA out of memory, retrying with CPU...")
            return transcribe_audio(audio_file, model_name, srt_file, language, 'cpu', compute)
        else:
            print(f"Error during transcription: {e}", file=sys.stderr)
            if os.path.exists(temp_srt):
                os.remove(temp_srt)
            return False

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
def process_create(file, model_name, srt_file='none', segments_file='segments.json', language='none', device='cuda', compute='int8_float32', write=print):
    """Creates a new process to retry the transcription."""
    global done
    
    if file is None:
        raise ValueError("The 'file' argument cannot be None. Please provide a valid file path.")
    
    model_names = model.model_names
    if model_name in model_names:
        i = model_names.index(model_name)
        for j in range(i, -1, -1):
            for c in range(0, 3):
                current_model = model_names[j]
                current_device = 'cpu' if c == 1 or 'large-' in current_model else device
                current_compute = 'int8' if c == 2 else compute
                
                if c == 2 and current_model == 'large-v3':
                    current_model = 'large-v2'
                
                try:
                    write(' '.join([str(i), str(j), str(c), current_compute, current_device, language]))
                    write(current_model)
                    write(f"Starting subprocess with model: {current_model}")
                    
                    # Create the subprocess with proper arguments
                    command = (
                        f"import faster_whisper; "
                        f"model = faster_whisper.WhisperModel('{current_model}', device='{current_device}', compute_type='{current_compute}'); "
                        f"segments, _ = model.transcribe('{file}', language={f"'{language}'" if language != 'none' else 'None'}); "
                        f"with open('{srt_file}', 'w', encoding='utf-8') as f: "
                        f"    for i, segment in enumerate(segments, 1): "
                        f"        f.write(f'{{i}}\\n'); "
                        f"        f.write(f'{{segment.start:.2f}} --> {{segment.end:.2f}}\\n'); "
                        f"        f.write(f'{{segment.text}}\\n\\n')"
                    )
                    
                    args = [sys.executable, '-c', command]
                    write(args)
                    
                    process = subprocess.Popen(
                        args,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        encoding='utf-8',
                        errors='replace',
                        text=True
                    )

                    # Monitor process and check for successful completion
                    while process.poll() is None:
                        stdout = process.stdout.readline()
                        if stdout:
                            write(f"Out : {stdout.strip()}")
                        stderr = process.stderr.readline()
                        if stderr:
                            write(f"Error: {stderr.strip()}")
                        time.sleep(0.1)
                    
                    exit_code = process.returncode
                    if exit_code == 0 or os.path.exists(srt_file):
                        write(f"Successfully created {srt_file}")
                        return True
                    
                    write(f"Process exited {exit_code}")
                    
                except Exception as e:
                    write(f"An error occurred on creation: {e}")
                    
                time.sleep(1)  # Brief pause before retrying with different settings
    else:
        write('No model')
    return False
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
