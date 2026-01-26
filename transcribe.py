import model
import faster_whisper
import torch.cuda as cuda
import torch.backends.cudnn as cudnn
import logging
import psutil
import time
import sys
import subprocess
import os
import json
import threading
import re
import datetime
from dataclasses import dataclass
from typing import Any, Dict, List
from whisper_model_chooser import WhisperModelChooser
os.environ["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"
os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'
audiofile, modelname, langcode = '', 'base', None
cuda.empty_cache()  # Clear GPU cache
cudnn.benchmark = False
cudnn.deterministic = True
logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)
@dataclass
class Segment:
    start: float
    end: float
    text: str

def srt_time_to_seconds(time_str: str) -> float:
    """Converts SRT time format HH:MM:SS,mmm to seconds."""
    try:
        parts = re.split('[:,]', time_str)
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000.0
    except (ValueError, IndexError):
        return 0.0

def get_srt_resume_info(srt_path: str) -> (float, int):
    """
    Parses an SRT file to find the last segment's number and end time.
    Returns (last_end_time_seconds, last_segment_number).
    """
    if not os.path.exists(srt_path) or os.path.getsize(srt_path) < 10:
        return 0.0, 0

    last_segment_number = 0
    last_end_time = 0.0
    
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            
        segments = content.split('\n\n')
        if not segments:
            return 0.0, 0
        
        # Iterate backwards to find the last valid segment block
        for segment_block in reversed(segments):
            lines = segment_block.strip().split('\n')
            if len(lines) >= 2:
                try:
                    current_segment_number = int(lines[0])
                    time_line = lines[1]
                    match = re.search(r'\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', time_line)
                    if match:
                        end_time_str = match.group(1)
                        last_end_time = srt_time_to_seconds(end_time_str)
                        last_segment_number = current_segment_number
                        # Found a valid segment, break the loop
                        return last_end_time, last_segment_number
                except (ValueError, IndexError):
                    # This block was malformed, continue to the previous one
                    continue
        
        return 0.0, 0 # Return defaults if no valid segment was found
    except Exception as e:
        print(f"Could not parse SRT for resume info: {e}")
        return 0.0, 0

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
    Transcribe audio file and generate SRT subtitles with helper files.
    Creates helper files for both in-progress and completed transcriptions.
    """
    original = srt_file
    temp_srt = srt_file.replace('.srt','.unfinished.srt')
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(temp_srt) or '.', exist_ok=True)
    
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
            cpu_threads=os.cpu_count()
        )

        # Process in smaller chunks
        result_segments, _ = whisper_model.transcribe(
            audio_file,
            language=language,
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.5,  # stricter threshold
                min_silence_duration_ms=800,  # longer silence minimum
                speech_pad_ms=400,  # more speech padding
            ),
            repetition_penalty=1.2,
            no_repeat_ngram_size=3,
            temperature=0.0,
            suppress_tokens=[-1],  # suppress non-speech tokens
            no_speech_threshold=0.6,  # raise threshold to filter more non-speech
            chunk_size=80
        )

        # Convert segments generator to list for post-processing
        segments_list = list(result_segments)

        # Apply post-processing to remove garbage segments
        segments_list = filter_garbage_segments(segments_list)
        segments_list = merge_adjacent_identical_segments(segments_list)

        # Write to temporary file first
        with open(temp_srt, "w", encoding="utf-8") as srt:
            for i, segment in enumerate(segments_list, start=1):
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
                srt.write(f"{i}\n")
                srt.write(f"{start_time} --> {end_time}\n")
                srt.write(f"{segment.text}\n\n")
                srt.flush()

        # Only proceed if the temporary file was created successfully
        if os.path.exists(temp_srt):
            # Create directory for the final file if it doesn't exist
            os.makedirs(os.path.dirname(original) or '.', exist_ok=True)
            
            # Remove the old file if it exists
            if os.path.exists(original):
                os.remove(original)
                
            # Rename the temporary file to the final name
            os.rename(temp_srt, original)
            
            # Clean up any temporary helper files
            temp_base = os.path.splitext(temp_srt)[0]
            for ext in ['.sh', '.bat']:
                temp_helper = f"{temp_base}{ext}"
                if os.path.exists(temp_helper):
                    try:
                        os.remove(temp_helper)
                    except Exception as e:
                        print(f"Warning: Could not remove temporary file {temp_helper}: {e}")
            
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
def process_create(file, model_name, srt_file='none', segments_file='segments.json', language='none', device='cpu', compute_type='int8', force_device=False, auto=True, write=print):
    """Creates a new process to retry the transcription."""
    if file is None:
        raise ValueError("The 'file' argument cannot be None. Please provide a valid file path.")
    
    # Only switch to CPU if not forcing device
    if not force_device and device == 'cpu':
        device = 'cpu'
        compute_type = 'int8'
        write(f"Falling back to CPU and int8")
    model_names = model.MODEL_NAMES

    if device == 'cuda' and auto:
        chooser = WhisperModelChooser()
        best = chooser.choose_best_model(english_only='en' in model_name)
        model_name = best['model']
        compute_type = best['compute_type']
        write(f"Selected model: {model_name} {compute_type}")
    compute_type = 'int8'
    if not model_name in model_names:
        model_name = model.getName(model_name)
    write(f"Transcribe Model name: {model_name}")
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
                    write(f"Successfully transcribed with {current_model}")
                    return True
            if device == 'cuda':
                write("All GPU models failed, falling back to CPU...")
                return try_transcribe(file, 'medium.en' if 'en' in model_name else 'large-v3', srt_file, language, 'cpu', 'int8', False, write)
    else:
        write('No model')
    return False

def try_transcribe(file, current_model, srt_file, language, device, compute_type, force_device, write):
    """Try transcription with given parameters, supporting resume."""
    script_path = None
    resume_audio_path = None
    try:
        unfinished_srt = srt_file.replace('.srt', '.unfinished.srt')
        os.makedirs(os.path.dirname(unfinished_srt) or '.', exist_ok=True)
        
        # --- RESUME LOGIC ---
        resume_offset_seconds = 0.0
        start_index = 0
        audio_to_transcribe = file
        open_mode = 'w'

        last_end_time, last_segment_number = get_srt_resume_info(unfinished_srt)

        if last_end_time > 0.1:  # Resume if there's more than 0.1s transcribed
            write(f"Found unfinished transcription. Resuming from {last_end_time:.2f} seconds.")
            resume_offset_seconds = last_end_time
            start_index = last_segment_number
            open_mode = 'a'
            resume_audio_path = os.path.splitext(file)[0] + ".resume.mp3"
            
            try:
                ss_time = str(datetime.timedelta(seconds=resume_offset_seconds))
                ffmpeg_command = ['/bin/ffmpeg', '-y', '-ss', ss_time, '-i', file, '-c:a', 'libmp3lame', resume_audio_path]
                write(f"Creating partial audio file for resume...")
                
                result = subprocess.run(ffmpeg_command, capture_output=True, text=True, check=False)
                if result.returncode != 0:
                    raise Exception(f"FFmpeg failed to create resume audio file: {result.stderr}")
                
                audio_to_transcribe = resume_audio_path
            except Exception as e:
                write(f"Could not create resume audio file: {e}. Starting from beginning.")
                resume_offset_seconds, start_index, open_mode = 0.0, 0, 'w'
                audio_to_transcribe = file
                with open(unfinished_srt, 'w', encoding='utf-8') as f: f.write('')
        else:
            with open(unfinished_srt, 'w', encoding='utf-8') as f: f.write('')
        # --- END RESUME LOGIC ---
        
        is_english_only = '.en' in current_model
        language_param = '\'en\'' if is_english_only else ('None' if language == 'none' else f"'{language}'")
        whisper_log = srt_file.replace('.srt', '.whisper.log')
        
        script = f'''
import faster_whisper
import os
import sys
import threading
import queue
import time
import logging
from dataclasses import dataclass

logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)
whisper_logger = logging.getLogger("faster_whisper")
whisper_logger.setLevel(logging.DEBUG)
log_file = r"{whisper_log}"
file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
whisper_logger.addHandler(file_handler)

os.makedirs(os.path.dirname(r"{srt_file}"), exist_ok=True)

@dataclass
class Segment:
    start: float
    end: float
    text: str

def format_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds_val = seconds % 60
    milliseconds = int((seconds_val % 1) * 1000)
    seconds_int = int(seconds_val)
    return f"{{hours:02d}}:{{minutes:02d}}:{{seconds_int:02d}},{{milliseconds:03d}}"

segment_queue = queue.Queue(maxsize=100)
write_event = threading.Event()
stop_event = threading.Event()
device = "{device}"
compute_type = "{compute_type}"

def write_segments():
    current_index = {start_index} + 1
    with open(r"{unfinished_srt}", "{open_mode}", encoding="utf-8") as f:
        if "{open_mode}" == "a" and os.path.getsize(r"{unfinished_srt}") > 0:
            f.write("\\n")

        while not stop_event.is_set() or not segment_queue.empty():
            try:
                segment = segment_queue.get(timeout=0.5)
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
                
                f.write(f"{{current_index}}\\n")
                f.write(f"{{start_time}} --> {{end_time}}\\n")
                f.write(f"{{segment.text.strip()}}\\n\\n")
                f.flush()
                
                current_index += 1
                segment_queue.task_done()
                write_event.set()
                
                if current_index % 10 == 0:
                    print(f"Written {{current_index - {start_index} - 1}} new segments (total {{current_index-1}})")
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error writing segment: {{e}}")

writer_thread = threading.Thread(target=write_segments, daemon=True)
writer_thread.start()

try:
    print(f"Starting transcription with model {current_model} on device {{device}}")
    print(f"Full log will be written to: {{log_file}}")
    
    model = faster_whisper.WhisperModel("{current_model}", device=device, compute_type=compute_type)

    segments, info = model.transcribe(
        r"{audio_to_transcribe}",
        language={language_param},
        vad_filter=True,
        vad_parameters=dict(
            threshold=0.5,  # stricter threshold
            min_silence_duration_ms=800,  # longer silence minimum
            speech_pad_ms=400,  # more speech padding
        ),
        repetition_penalty=1.2,
        no_repeat_ngram_size=3,
        temperature=0.0,
        suppress_tokens=[-1],  # suppress non-speech tokens
        no_speech_threshold=0.6,  # raise threshold to filter more non-speech
        word_timestamps=False
    )
    
    resume_offset = {resume_offset_seconds}
    
    for segment in segments:
        while segment_queue.full() and not stop_event.is_set():
            time.sleep(0.1)
        if stop_event.is_set(): break

        adjusted_segment = Segment(
            start=segment.start + resume_offset,
            end=segment.end + resume_offset,
            text=segment.text
        )
        segment_queue.put(adjusted_segment)
        
        write_event.wait(timeout=1.0)
        write_event.clear()
    
    stop_event.set()
    writer_thread.join(timeout=30)
    
    if os.path.exists(r"{unfinished_srt}") and os.path.getsize(r"{unfinished_srt}") > 10:
        if os.path.exists(r"{srt_file}"): os.remove(r"{srt_file}")
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
    file_handler.close()
    whisper_logger.removeHandler(file_handler)
'''
        
        import tempfile
        temp_dir = tempfile.gettempdir()
        script_path = os.path.join(temp_dir, f"temp_whisper_{os.getpid()}.py")
        
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script)

        args = [sys.executable, script_path]
        write(f"Running transcription with model {current_model} on {device}")
        
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', errors='replace', text=True, bufsize=1, universal_newlines=True
        )

        def log_output(pipe, prefix):
            for line in pipe:
                if line := line.strip(): write(f"{prefix}: {line}")

        stdout_thread = threading.Thread(target=log_output, args=(process.stdout, "Out"), daemon=True)
        stderr_thread = threading.Thread(target=log_output, args=(process.stderr, "Error"), daemon=True)
        stdout_thread.start(); stderr_thread.start()
        
        exit_code = process.wait()
        
        stdout_thread.join(timeout=5); stderr_thread.join(timeout=5)
        
        if exit_code == 0 and os.path.exists(srt_file) and os.path.getsize(srt_file) > 10:
            write(f"Successfully created {srt_file}")
            make_files(srt_file)
            return True
        
        write(f"Process exited with code {exit_code}")
        return False

    except Exception as e:
        write(f"An error occurred: {e}")
        return False
            
    finally:
        try:
            if script_path and os.path.exists(script_path): os.unlink(script_path)
            if resume_audio_path and os.path.exists(resume_audio_path):
                os.unlink(resume_audio_path)
                write("Removed temporary resume audio file.")
        except Exception as e:
            write(f"Warning: Could not remove temporary file: {e}")

def make_files(srt_file, url=None):
    """
    Create helper files (HTML, .sh, .bat) for the given SRT file.
    Handles both finished and unfinished transcriptions.
    
    Args:
        srt_file (str): Path to the SRT file
        url (str, optional): URL to use for helper files. If not provided, will try to extract from HTML.
    """
    if not srt_file:
        print("No SRT file provided")
        return
    try:
        print(f"Creating helper files for {srt_file}")
        if not os.path.exists(srt_file):
            # Create an empty file if it doesn't exist
            os.makedirs(os.path.dirname(srt_file) or '.', exist_ok=True)
            with open(srt_file, 'w', encoding='utf-8') as f:
                f.write('Transcription in progress...')
        
        dir_path = os.path.dirname(srt_file)
        base_name = os.path.splitext(os.path.basename(srt_file))[0]
        
        # Handle both finished and unfinished files
        is_unfinished = '.unfinished' in base_name
        clean_base = base_name.replace('.unfinished', '') if is_unfinished else base_name
        print(f"Base name: {base_name}, Clean base: {clean_base}")
        print(f"Dir path: {dir_path}")
        # Create directory if it doesn't exist
        os.makedirs(dir_path, exist_ok=True)
        
        # If URL was provided, use it directly
        if url:
            print(f"Using provided URL: {url}")
            create_helper_files(dir_path, srt_file, url)
            return
            
        # For unfinished files without URL, try to extract video ID from filename
        if is_unfinished:
            # Extract video ID from the filename if possible
            video_id = 'video_id_placeholder'  # Default if we can't extract
            try:
                # Try to get the YouTube video ID from the URL if it exists in the filename
                import re
                match = re.search(r'[?&]v=([^&\s]+)', base_name)
                if match:
                    video_id = match.group(1)
                else:
                    # If no URL in filename, try to use the first part of the filename
                    video_id = base_name.split('_')[0]
                    if len(video_id) > 20:  # Probably not a video ID if too long
                        video_id = 'video_id_placeholder'
            except:
                pass
                
            url = f"https://youtube.com/watch?v={video_id}"
            print(f"Using generated URL for unfinished transcription: {url}")
            create_helper_files(dir_path, base_name, url)
        else:
            # For finished files, try to get URL from HTML file
            html_file = os.path.join(dir_path, f"{clean_base}.htm")
            
            if os.path.exists(html_file):
                try:
                    print(f"Reading HTML file {html_file}")
                    with open(html_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        import re
                        match = re.search(r'URL=[\'"]([^\'"]+)[\'"]', content)
                        if match:
                            url = match.group(1)
                            print(f"URL from HTML: {url}")
                            create_helper_files(dir_path, base_name, url)
                except Exception as e:
                    print(f"Error reading HTML file {html_file}: {e}")
            
    except Exception as e:
        print(f"Error in make_files for {srt_file}: {e}")
def write_srt_from_segments(segments, srt):
    """Writes the transcription segments to an SRT file."""
    for i, segment in enumerate(segments, start=1):
        start_time = format_timestamp(segment.start)
        end_time = format_timestamp(segment.end)

        # Write each segment to the SRT file
        srt.write(f"{i}\n")
        srt.write(f"{start_time} --> {end_time}\n")
        srt.write(f"{segment.text}\n\n")

HALLUCINATION_NAMES = {
    "Sônia Ruberti",
    "Tiago Anderson",
    "Quintena Coelho",
    "Anderson",
    "Ruberti",
}

def is_whisper_entity(seg):
    """Check if a segment contains hallucinated entities."""
    t = seg.text.strip()

    if t in HALLUCINATION_NAMES:
        return True

    # Access the segment's properties if available
    # The attributes might not be available in all contexts, so handle safely
    try:
        if hasattr(seg, 'no_speech_prob') and seg.no_speech_prob > 0.5:
            return True
        if hasattr(seg, 'avg_logprob') and seg.avg_logprob < -1.2:
            return True
    except:
        pass  # If properties aren't available, continue with other checks

    if seg.end - seg.start < 0.6:
        return True

    return False

def is_garbage(seg):
    """Check if a segment contains garbage text that should be filtered out."""
    # First check if it's a hallucinated entity
    if is_whisper_entity(seg):
        return True

    text = seg.text.strip()
    dur = seg.end - seg.start

    if dur < 0.4:
        return True
    if len(text) <= 1:
        return True
    if text in {"え", "…", "...", "「", "」", "『", "』", "【", "】", "・"}:
        return True
    # Check for repeated characters like "えええ" or "あああ"
    if len(set(text)) == 1 and len(text) > 2:  # All characters are the same
        return True
    # Check for repeated tokens like "次回予告" * n
    if len(text) > 2 and text.count(text[0:2]) > len(text) // 2:
        return True
    return False

def filter_garbage_segments(segments):
    """Remove segments that are likely to be garbage."""
    return [s for s in segments if not is_garbage(s)]

def merge_adjacent_identical_segments(segments):
    """Merge adjacent segments that have identical text."""
    if not segments:
        return segments

    merged = []
    for s in segments:
        if merged and s.text.strip() == merged[-1].text.strip():
            merged[-1].end = s.end
        else:
            merged.append(s)
    return merged

def create_helper_files(dir_path, subtitle_file, url):
    """Create helper files (HTML redirect, batch file, shell script)"""
    print(f"Creating helper files for {subtitle_file}")
    try:
        if not subtitle_file.endswith('.srt'):
            subtitle_file += '.srt'
        #if subtitle_file is not a full path, add Documents/Youtube-Subs to the path
        if not any(x in subtitle_file for x in ['/', '\\']):
            subtitle_file = os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs", subtitle_file)
        base_name = os.path.splitext(os.path.basename(subtitle_file))[0].replace('.unfinished','')
        print(f"Base name: {base_name}")
        print(f"Dir path: {dir_path}")
        print(f"URL: {url}")
        # HTML redirect (same as before)
        html_file = os.path.join(dir_path, f"{base_name}.htm")
        try:
            with open(html_file, "w", encoding='utf-8') as f:
                f.write(f"""<!DOCTYPE html>
<html>
<head><meta http-equiv="refresh" content="0; URL='{url}'" /></head>
<body></body>
</html>""")
        except OSError as e:
            print(f"OS error creating HTML file: {e}")
        except Exception as e:
            print(f"Error creating HTML file: {e}")
        # Shell script (.sh)
        try:
            sh_file = os.path.join(dir_path, f"{base_name}.sh")
            linux_path = subtitle_file.replace("\\", "/")
            with open(sh_file, "w", encoding='utf-8') as f:
                f.write(f'#!/bin/bash\nmpv "{url}" --pause --input-ipc-server=/tmp/mpvsocket --sub-file="{linux_path}" $@\n')
            os.chmod(sh_file, 0o755)
        except OSError as e:
            print(f"OS error creating shell script: {e}")
        except Exception as e:
            print(f"Error creating shell script: {e}")

        # Batch file (.bat)
        bat_file = os.path.join(dir_path, f"{base_name}.bat")
        win_path = subtitle_file
        print(f"Win path: {win_path}")
        try:
            if win_path.startswith("/home"):
                win_path = f"C:\\Users{win_path[5:]}"
            win_path = win_path.replace("/", "\\")
            print(f"Win path after replacement: {win_path}")
            with open(bat_file, "w", encoding='utf-8') as f:
                f.write(f'mpv "{url}" --pause --input-ipc-server=/tmp/mpvsocket --sub-file="{win_path}"\n')
        except OSError as e:
            print(f"OS error creating batch file: {e}")
        except Exception as e:
            print(f"Error creating batch file: {e}")
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
