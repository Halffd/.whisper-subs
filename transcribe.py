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
        memory_percent = psutil.Process().memory_percent()
def transcribe_audio(audio_file, model_name, srt_file="file.srt", language=None, device='cpu', compute_type='int8'):
    """  
    Modified to handle compute_type parameter properly
    """
    original = srt_file
    temp_srt = srt_file.replace('.srt','-unfinished.srt')
    make_files(temp_srt)
    # Automatically switch to CPU if CUDA is not available
    if device == 'cuda':
        try:
            import torch
            if not torch.cuda.is_available():
                device = 'cpu'
                compute_type = 'int8'
                print("CUDA not available, falling back to CPU")
        except ImportError:
            device = 'cpu'
            compute_type = 'int8'
            print("PyTorch not available, falling back to CPU")

    try:
        whisper_model = faster_whisper.WhisperModel(
            model_name, 
            device=device, 
            compute_type=compute_type,  # Use the compute_type parameter
            device_index=0,
            cpu_threads=4
        )
        
        # Process in smaller chunks
        result_segments, _ = whisper_model.transcribe(
            audio_file, 
            language=language,
            vad_filter=True,
            chunk_size=20
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
                make_files(original)  # Recreate helper files to point at final SRT
                return True

        
    except RuntimeError as e:
        if 'CUDA' in str(e) or 'cuDNN' in str(e):
            print("CUDA/cuDNN error detected, falling back to CPU...")
            return transcribe_audio(audio_file, model_name, srt_file, language, 'cpu', compute_type)
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
def process_create(file, model_name, srt_file='none', segments_file='segments.json', language='none', device='cpu', compute_type='int8', force_device=False, write=print):
    """Creates a new process to retry the transcription."""
    if file is None:
        raise ValueError("The 'file' argument cannot be None. Please provide a valid file path.")
    
    # Only switch to CPU if not forcing device
    if not force_device:
        device = 'cpu'
        compute_type = 'int8'
    
    model_names = model.model_names
    if model_name in model_names:
        i = model_names.index(model_name)
        
        # Try with original settings first
        success = try_transcribe(file, model_name, srt_file, language, device, compute_type, force_device, write)
        if success:
            return True
            
        # If not forcing device and original settings fail, try smaller models
        if not force_device:
            write("Trying smaller models...")
            for j in range(i-1, -1, -1):
                current_model = model_names[j]
                success = try_transcribe(file, current_model, srt_file, language, device, compute_type, force_device, write)
                if success:
                    return True
    else:
        write('No model')
    return False

def try_transcribe(file, current_model, srt_file, language, device, compute_type, force_device, write):
    """Try transcription with given parameters"""
    try:
        # Format language parameter properly - force 'en' for English-only models
        is_english_only = '.en' in current_model
        language_param = "'en'" if is_english_only else ('None' if language == 'none' else f"'{language}'")
        
        # Create unfinished srt file name
        unfinished_srt = srt_file.replace('.srt', '.unfinished.srt')
        whisper_log = srt_file.replace('.srt', '.whisper.log')  # Add log file path
        
        script = f'''
import faster_whisper
import os
import sys
import threading
import queue
import time
import logging

# Setup logging
logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)
whisper_logger = logging.getLogger("faster_whisper")
whisper_logger.setLevel(logging.DEBUG)
# Add file handler for whisper output
log_file = r"{whisper_log}"
file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
whisper_logger.addHandler(file_handler)

# Ensure output directory exists
os.makedirs(os.path.dirname(r"{srt_file}"), exist_ok=True)

def format_timestamp(seconds):
    """Convert seconds to SRT timestamp format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds % 1) * 1000)
    seconds = int(seconds)
    return f"{{hours:02d}}:{{minutes:02d}}:{{seconds:02d}},{{milliseconds:03d}}"

# Create a queue with size limit for memory management
segment_queue = queue.Queue(maxsize=100)
write_event = threading.Event()
stop_event = threading.Event()

# Set device and compute type
device = "{device}"
compute_type = "{compute_type}"
force_device = {str(force_device)}  # Add force_device parameter

def write_segments():
    current_index = 1
    with open(r"{unfinished_srt}", "w", encoding="utf-8") as f:
        while not stop_event.is_set() or not segment_queue.empty():
            try:
                # Wait for new segments with timeout
                segment = segment_queue.get(timeout=0.5)
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
                
                # Write segment immediately
                f.write(f"{{current_index}}\\n")
                f.write(f"{{start_time}} --> {{end_time}}\\n")
                f.write(f"{{segment.text.strip()}}\\n\\n")
                f.flush()  # Force write to disk
                
                current_index += 1
                segment_queue.task_done()
                write_event.set()  # Signal that we wrote something
                
                if current_index % 10 == 0:
                    print(f"Written {{current_index}} segments")
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error writing segment: {{e}}")

# Start writer thread
writer_thread = threading.Thread(target=write_segments, daemon=True)
writer_thread.start()

try:
    print(f"Starting transcription with model {current_model} on device {{device}}")
    print(f"Full log will be written to: {{log_file}}")
    
    # Initialize model with verbose logging
    model = faster_whisper.WhisperModel(
        "{current_model}",
        device=device,
        compute_type=compute_type
    )
    
    # Process segments as they come
    segments, info = model.transcribe(r"{file}")
    
    # Process each segment
    for segment in segments:
        # Wait if queue is full
        while segment_queue.full() and not stop_event.is_set():
            time.sleep(0.1)
        
        if stop_event.is_set():
            break
            
        segment_queue.put(segment)
        
        # Wait for at least one write to happen
        write_event.wait(timeout=1.0)
        write_event.clear()
    
    # Signal completion and wait for writer
    stop_event.set()
    writer_thread.join(timeout=30)
    
    # Verify and rename
    if os.path.exists(r"{unfinished_srt}") and os.path.getsize(r"{unfinished_srt}") > 10:
        if os.path.exists(r"{srt_file}"):
            os.remove(r"{srt_file}")
        os.rename(r"{unfinished_srt}", r"{srt_file}")
        print("Transcription completed successfully")
    else:
        print("Output file is empty or too small")
        exit(1)
        
except Exception as e:
    print(f"Error during transcription: {{e}}")
    import traceback
    traceback.print_exc()
    exit(1)
finally:
    # Close log file handler
    file_handler.close()
    whisper_logger.removeHandler(file_handler)
'''
        
        # Write script to temporary file
        script_path = os.path.join(os.path.dirname(file), f"temp_whisper_{os.getpid()}.py")
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script)

        try:
            # Run the script
            args = [sys.executable, script_path]
            write(f"Running transcription with model {current_model} on {device}")
            
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                errors='replace',
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )

            # Monitor both stdout and stderr simultaneously
            def log_output(pipe, prefix):
                for line in pipe:
                    line = line.strip()
                    if line:
                        write(f"{prefix}: {line}")

            # Create threads for stdout and stderr
            stdout_thread = threading.Thread(target=log_output, args=(process.stdout, "Out"))
            stderr_thread = threading.Thread(target=log_output, args=(process.stderr, "Error"))
            
            # Start threads
            stdout_thread.start()
            stderr_thread.start()
            
            # Wait for process to complete
            exit_code = process.wait()
            
            # Wait for output threads to complete
            stdout_thread.join()
            stderr_thread.join()
            
            if exit_code == 0 and os.path.exists(srt_file) and os.path.getsize(srt_file) > 10:
                write(f"Successfully created {srt_file}")
                
                # Create helper files
                make_files(srt_file)
                return True
            
            write(f"Process exited with code {exit_code}")
            return False
            
        finally:
            # Clean up temporary script
            try:
                os.remove(script_path)
            except:
                pass

    except Exception as e:
        write(f"An error occurred: {e}")
        return False
def make_files(srt_file):
    dir_path = os.path.dirname(srt_file)
    base_name = os.path.splitext(os.path.basename(srt_file))[0]
                
                # Try to find corresponding HTML file to get URL
    html_file = os.path.join(dir_path, f"{base_name}.htm")
    url = None
    if os.path.exists(html_file):
        try:
            with open(html_file, 'r', encoding='utf-8') as f:
                content = f.read()
                import re
                match = re.search(r'URL=\'([^\']+)\'', content)
                if match:
                    url = match.group(1)
        except:
            pass               
    if url:
        create_helper_files(dir_path, base_name, url)
def write_srt_from_segments(segments, srt):
    """Writes the transcription segments to an SRT file."""
    for i, segment in enumerate(segments, start=1):
        start_time = format_timestamp(segment.start)
        end_time = format_timestamp(segment.end)

        # Write each segment to the SRT file
        srt.write(f"{i}\n")
        srt.write(f"{start_time} --> {end_time}\n")
        srt.write(f"{segment.text}\n\n")

def create_helper_files(dir_path, subtitle_file, url):
    """Create helper files (HTML redirect, batch file, shell script)"""
    try:
        base_name = os.path.splitext(os.path.basename(subtitle_file))[0]

        # HTML redirect (same as before)
        html_file = os.path.join(dir_path, f"{base_name}.htm")
        with open(html_file, "w", encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head><meta http-equiv="refresh" content="0; URL='{url}'" /></head>
<body></body>
</html>""")

        # Shell script (.sh)
        sh_file = os.path.join(dir_path, f"{base_name}.sh")
        linux_path = subtitle_file.replace("\\", "/")
        with open(sh_file, "w", encoding='utf-8') as f:
            f.write(f'#!/bin/bash\nmpv "{url}" --pause --sub-file="{linux_path}"\n')
        os.chmod(sh_file, 0o755)

        # Batch file (.bat)
        bat_file = os.path.join(dir_path, f"{base_name}.bat")
        win_path = subtitle_file
        if win_path.startswith("/home"):
            win_path = f"C:\\Users{win_path[5:]}"
        win_path = win_path.replace("/", "\\")
        with open(bat_file, "w", encoding='utf-8') as f:
            f.write(f'mpv "{url}" --pause --sub-file="{win_path}"\n')

    except Exception as e:
        print(f"Error creating helper files: {e}")

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
