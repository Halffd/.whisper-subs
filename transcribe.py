"""
WhisperSubs Transcribe Module

Core transcription functionality using faster-whisper.
"""
import model as _model_module
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
from typing import Any, Dict, List, Optional, Tuple, Callable
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

def get_srt_resume_info(srt_path: str) -> Tuple[float, int]:
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
def standalone(seg):
    dur = seg["end"] - seg["start"]
    words = len(seg["text"].split())
    return dur >= 2.5 or words >= 12

def merge_segments(
    segments,
    max_gap=0.5,
    max_duration=4.0,
    max_words=20,
    max_chars=120,
):
    if not segments:
        return segments

    merged = [segments[0]]

    for s in segments[1:]:
        prev = merged[-1]

        gap = s.start - prev.end
        new_duration = s.end - prev.start

        merged_text = (prev.text.rstrip() + " " + s.text.lstrip()).strip()
        word_count = len(merged_text.split())
        char_count = len(merged_text)

        if (
            gap <= max_gap
            and new_duration <= max_duration
            and word_count <= max_words
            and char_count <= max_chars
            and not(standalone(prev) or standalone(s)) 
        ):
            prev.text = merged_text
            prev.end = s.end
        else:
            merged.append(s)

    return merged


class ProgressTracker:
    """Track transcription progress with ETA estimation"""
    
    def __init__(self, total_duration: float, write: Callable = print):
        self.total_duration = total_duration
        self.write = write
        self.start_time = time.time()
        self.last_progress_time = 0
        self.segments_processed = 0
        self.last_segment_time = 0
        
    def update(self, segment_start: float, segment_end: float) -> None:
        """Update progress with current segment"""
        self.segments_processed += 1
        current_time = time.time()
        
        # Calculate progress percentage
        progress = (segment_end / self.total_duration) * 100
        
        # Calculate ETA (only update every second to avoid spam)
        if current_time - self.last_progress_time >= 1.0:
            elapsed = current_time - self.start_time
            if progress > 0:
                estimated_total = elapsed / (progress / 100)
                remaining = estimated_total - elapsed
                eta_str = str(datetime.timedelta(seconds=int(remaining)))
                
                # Calculate processing speed
                speed = segment_end / elapsed if elapsed > 0 else 0
                
                self.write(f"Progress: {progress:.1f}% | "
                          f"Elapsed: {str(datetime.timedelta(seconds=int(elapsed)))} | "
                          f"ETA: {eta_str} | "
                          f"Speed: {speed:.1f}x real-time")
            
            self.last_progress_time = current_time


def transcribe_audio(
    audio_file: str,
    model_name: str,
    srt_file: str = "file.srt",
    language: Optional[str] = None,
    device: str = 'cpu',
    compute_type: str = 'int8',
    cpu_threads: Optional[int] = None,
    write: Callable = print
) -> bool:
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
        # Get audio duration for progress tracking
        try:
            import subprocess
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', audio_file],
                capture_output=True, text=True, check=False
            )
            total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0
        except Exception:
            total_duration = 0
        
        # Initialize model with specified CPU threads
        whisper_model = faster_whisper.WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            device_index=0,
            cpu_threads=cpu_threads if cpu_threads else os.cpu_count()
        )
        
        # Initialize progress tracker
        progress = ProgressTracker(total_duration, write) if total_duration > 0 else None
        
        write(f"Starting transcription (duration: {str(datetime.timedelta(seconds=int(total_duration))) if total_duration else 'unknown'})")

        # Check if using distil-whisper model (needs special parameters)
        is_distil = 'distil' in model_name.lower()
        
        # Distil-whisper models need special parameters for best performance
        transcribe_params = {
            'audio_file': audio_file,
            'language': language,
            'vad_filter': False,
        }
        
        # Add distil-specific parameters
        if is_distil:
            transcribe_params.update({
                'condition_on_previous_text': False,  # Critical for distil models!
                'max_new_tokens': 128,
                'beam_size': 5,
            })
            write(f"Using distil-whisper optimized parameters")

        # Process in smaller chunks with progress tracking
        result_segments, info = whisper_model.transcribe(**transcribe_params)

        # Convert segments generator to list for post-processing
        segments_list = list(result_segments)

        write(f"Transcribed {len(segments_list)} segments, processing...")

        # Apply post-processing to remove garbage segments
        segments_list = filter_garbage_segments(segments_list)
        segments_list = merge_adjacent_identical_segments(segments_list)
        #segments_list = merge_segments(segments_list)

        # Write to temporary file first with progress tracking and metadata
        with open(temp_srt, "w", encoding="utf-8") as srt:
            # Write metadata header as SRT comments
            srt.write(f"1\n00:00:00,000 --> 00:00:00,000\n")
            srt.write(f"TRANSCRIPTION METADATA\n")
            srt.write(f"Model: {model_name}\n")
            srt.write(f"Date: {datetime.datetime.now().isoformat()}\n")
            srt.write(f"Source: {os.path.basename(audio_file)}\n")
            srt.write(f"Duration: {str(datetime.timedelta(seconds=int(total_duration))) if total_duration else 'unknown'}\n")
            srt.write(f"Language: {language or 'auto-detect'}\n")
            srt.write(f"Device: {device}\n")
            srt.write(f"Compute: {compute_type}\n")
            if vad_filter:
                srt.write(f"VAD: enabled\n")
            if temperature:
                srt.write(f"Temperature: {temperature}\n")
            if cpu_threads:
                srt.write(f"CPU Threads: {cpu_threads}\n")
            srt.write(f"\n")
            
            # Write actual subtitle segments
            for i, segment in enumerate(segments_list, start=1):
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
                srt.write(f"{i}\n")
                srt.write(f"{start_time} --> {end_time}\n")
                srt.write(f"{segment.text}\n\n")
                srt.flush()

                # Update progress tracker
                if progress:
                    progress.update(segment.start, segment.end)

        # Final progress update
        if progress:
            elapsed = time.time() - progress.start_time
            speed = total_duration / elapsed if elapsed > 0 else 0
            write(f"Transcription completed in {str(datetime.timedelta(seconds=int(elapsed)))} ({speed:.1f}x real-time)")

        # Only proceed if the temporary file was created successfully
        if os.path.exists(temp_srt):
            # Create directory for the final file if it doesn't exist
            os.makedirs(os.path.dirname(original) or '.', exist_ok=True)

            # Remove the old file if it exists
            if os.path.exists(original):
                os.remove(original)

            # Rename the temporary file to the final name
            os.rename(temp_srt, original)

            # Create JSON metadata file
            metadata_file = os.path.splitext(original)[0] + ".metadata.json"
            try:
                metadata = {
                    "model": model_name,
                    "date": datetime.datetime.now().isoformat(),
                    "source_file": os.path.basename(audio_file),
                    "duration_seconds": total_duration,
                    "duration_formatted": str(datetime.timedelta(seconds=int(total_duration))) if total_duration else "unknown",
                    "language": language or "auto-detect",
                    "device": device,
                    "compute_type": compute_type,
                    "cpu_threads": cpu_threads,
                    "vad_enabled": vad_filter,
                    "vad_params": vad_params,
                    "temperature": temperature,
                    "merge_lines": merge_lines,
                    "time_range": {
                        "start": start_time,
                        "end": end_time
                    } if start_time or end_time else None,
                    "segments_count": len(segments_list),
                    "output_files": {
                        "srt": original,
                        "json": metadata_file
                    }
                }
                with open(metadata_file, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                write(f"Metadata saved to: {metadata_file}")
            except Exception as e:
                write(f"Warning: Could not create metadata file: {e}")

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

def process_create(
    file: str,
    model_name: str,
    srt_file: str = 'none',
    segments_file: str = 'segments.json',
    language: str = 'none',
    device: str = 'cpu',
    compute_type: str = 'int8',
    force_device: bool = False,
    auto: bool = True,
    write: Callable = print,
    cpu_threads: Optional[int] = None,
    vad_filter: bool = False,
    vad_params: Optional[Dict[str, Any]] = None,
    diarization: bool = False,
    diarization_params: Optional[Dict[str, Any]] = None,
    temperature: float = 0,
    merge_lines: bool = False,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    mpv_ipc_reload: Optional[Callable] = None
) -> bool:
    """Creates a new process to retry the transcription."""
    if file is None:
        raise ValueError("The 'file' argument cannot be None. Please provide a valid file path.")

    # Only switch to CPU if not forcing device
    if not force_device and device == 'cpu':
        device = 'cpu'
        compute_type = 'int8'
        write(f"Falling back to CPU and int8")
    model_names = _model_module.MODEL_NAMES

    if device == 'cuda' and auto:
        chooser = WhisperModelChooser()
        best = chooser.choose_best_model(english_only='en' in model_name)
        model_name = best['model']
        compute_type = best['compute_type']
        write(f"Selected model: {model_name} {compute_type}")
    compute_type = 'int8'
    if not model_name in model_names:
        model_name = _model_module.getName(model_name)
    write(f"Transcribe Model name: {model_name}")
    if model_name in model_names:
        i = model_names.index(model_name)

        # Try with original settings first
        success = try_transcribe(file, model_name, srt_file, language, device, compute_type, force_device, write, cpu_threads,
                                 vad_filter, vad_params, diarization, diarization_params, temperature, merge_lines,
                                 start_time, end_time)
        if success:
            return True

        # If not forcing device and original settings fail, try smaller models
        if not force_device:
            write("Trying smaller models...")
            for j in range(i-1, -1, -1):
                current_model = model_names[j]
                success = try_transcribe(file, current_model, srt_file, language, device, compute_type, force_device, write, cpu_threads,
                                         vad_filter, vad_params, diarization, diarization_params, temperature, merge_lines,
                                         start_time, end_time)
                if success:
                    write(f"Successfully transcribed with {current_model}")
                    return True
            if device == 'cuda':
                write("All GPU models failed, falling back to CPU...")
                return try_transcribe(file, 'medium.en' if 'en' in model_name else 'large-v3', srt_file, language, 'cpu', 'int8', False, write, cpu_threads,
                                      vad_filter, vad_params, diarization, diarization_params, temperature, merge_lines,
                                      start_time, end_time)
    else:
        write('No model')
    return False

def try_transcribe(
    file: str,
    current_model: str,
    srt_file: str,
    language: str,
    device: str,
    compute_type: str,
    force_device: bool,
    write: Callable,
    cpu_threads: Optional[int] = None,
    vad_filter: bool = False,
    vad_params: Optional[Dict[str, Any]] = None,
    diarization: bool = False,
    diarization_params: Optional[Dict[str, Any]] = None,
    temperature: float = 0,
    merge_lines: bool = False,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    mpv_ipc_reload: Optional[Callable] = None
) -> bool:
    """Try transcription with given parameters, supporting resume."""
    script_path = None
    resume_audio_path = None
    trimmed_audio_path = None
    try:
        unfinished_srt = srt_file.replace('.srt', '.unfinished.srt')
        os.makedirs(os.path.dirname(unfinished_srt) or '.', exist_ok=True)

        # --- TIME RANGE CUTTING ---
        audio_to_transcribe = file
        start_offset_seconds = 0.0
        
        if start_time or end_time:
            trimmed_audio_path = os.path.splitext(file)[0] + ".trimmed.m4a"
            # Use -ss BEFORE -i for faster seeking, -vn to skip video processing
            ffmpeg_cmd = ['ffmpeg', '-y']

            if start_time:
                # Parse start time (support HH:MM:SS, MM:SS, or seconds)
                if ':' in str(start_time):
                    # Place -ss before -i for fast seeking
                    ffmpeg_cmd.extend(['-ss', str(start_time)])
                    # Calculate offset for subtitle timestamps
                    parts = str(start_time).split(':')
                    if len(parts) == 3:  # HH:MM:SS
                        start_offset_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                    elif len(parts) == 2:  # MM:SS
                        start_offset_seconds = int(parts[0]) * 60 + float(parts[1])
                    else:  # Invalid format
                        start_offset_seconds = 0
                        write(f"Warning: Invalid start_time format '{start_time}', expected HH:MM:SS or MM:SS")
                else:
                    start_offset_seconds = float(start_time)
                    ffmpeg_cmd.extend(['-ss', str(datetime.timedelta(seconds=start_offset_seconds))])

            ffmpeg_cmd.extend(['-i', file])

            if end_time:
                # Parse end time and calculate duration
                if ':' in str(end_time):
                    # Convert HH:MM:SS or MM:SS to seconds
                    parts = str(end_time).split(':')
                    if len(parts) == 3:  # HH:MM:SS
                        end_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                    elif len(parts) == 2:  # MM:SS
                        end_seconds = int(parts[0]) * 60 + float(parts[1])
                    else:  # Invalid format
                        end_seconds = 0
                        write(f"Warning: Invalid end_time format '{end_time}', expected HH:MM:SS or MM:SS")
                else:
                    end_seconds = float(end_time)

                # Calculate duration
                if start_time:
                    duration = end_seconds - start_offset_seconds
                else:
                    duration = end_seconds

                ffmpeg_cmd.extend(['-t', str(datetime.timedelta(seconds=duration))])

            # Audio only - optimized for transcription speed
            ffmpeg_cmd.extend([
                '-vn',  # No video
                '-acodec', 'aac',
                '-b:a', '128k',  # Sufficient for speech
                '-ac', '1',  # Mono
                '-ar', '16000',  # Whisper native sample rate
                trimmed_audio_path
            ])

            write(f"Cutting audio from {start_time or 'start'} to {end_time or 'end'}...")
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                audio_to_transcribe = trimmed_audio_path
                write(f"Created trimmed audio: {trimmed_audio_path}")
                write(f"Subtitle offset: {start_offset_seconds:.2f}s")
            else:
                write(f"Warning: FFmpeg trimming failed: {result.stderr}, using original file")
                trimmed_audio_path = None
                start_offset_seconds = 0.0
        # --- END TIME RANGE CUTTING ---

        # --- RESUME LOGIC ---
        resume_offset_seconds = 0.0
        start_index = 0
        open_mode = 'w'

        last_end_time, last_segment_number = get_srt_resume_info(unfinished_srt)

        if last_end_time > 0.1:  # Resume if there's more than 0.1s transcribed
            write(f"Found unfinished transcription. Resuming from {last_end_time:.2f} seconds.")
            resume_offset_seconds = last_end_time
            start_index = last_segment_number
            open_mode = 'a'
            resume_audio_path = os.path.splitext(audio_to_transcribe)[0] + ".resume.m4a"

            try:
                ss_time = str(datetime.timedelta(seconds=resume_offset_seconds))
                ffmpeg_command = ['/bin/ffmpeg', '-y', '-ss', ss_time, '-i', audio_to_transcribe, '-c:a', 'aac', '-b:a', '192k', resume_audio_path]
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

        # Create helper files for the unfinished SRT file
        make_files(unfinished_srt)

        is_english_only = '.en' in current_model
        language_param = '\'en\'' if is_english_only else ('None' if language == 'none' else f"'{language}'")
        whisper_log = srt_file.replace('.srt', '.whisper.log')
        
        # Initialize audio_duration for progress tracking (will be updated after model loads)
        audio_duration = 0

        script = f'''
import faster_whisper
import os
import sys
import threading
import queue
import time
import logging
import datetime
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
cpu_threads = {cpu_threads if cpu_threads else 'None'}
vad_filter = {str(vad_filter).capitalize()}
vad_params = {vad_params if vad_filter and vad_params else 'None'}
temperature = {temperature}
merge_lines = {str(merge_lines).capitalize()}
mpv_ipc_reload = {mpv_ipc_reload if mpv_ipc_reload else 'None'}
start_offset_seconds = {start_offset_seconds}
segments_written = 0
audio_duration = {audio_duration}

def write_segments():
    global segments_written
    current_index = {start_index} + 1
    with open(r"{unfinished_srt}", "{open_mode}", encoding="utf-8") as f:
        if "{open_mode}" == "a" and os.path.getsize(r"{unfinished_srt}") > 0:
            f.write("\\n")

        while not stop_event.is_set() or not segment_queue.empty():
            try:
                segment = segment_queue.get(timeout=0.5)
                # Apply time offset if audio was trimmed
                adjusted_start = segment.start + start_offset_seconds
                adjusted_end = segment.end + start_offset_seconds
                start_time = format_timestamp(adjusted_start)
                end_time = format_timestamp(adjusted_end)

                f.write(f"{{current_index}}\\n")
                f.write(f"{{start_time}} --> {{end_time}}\\n")
                f.write(f"{{segment.text.strip()}}\\n\\n")
                f.flush()

                current_index += 1
                segments_written += 1
                segment_queue.task_done()
                write_event.set()

                # Reload subtitles in MPV via IPC every 10 segments
                if segments_written % 10 == 0 and mpv_ipc_reload is not None:
                    try:
                        mpv_ipc_reload()
                    except Exception as ipc_err:
                        print(f"MPV IPC reload failed: {{ipc_err}}")

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

    model = faster_whisper.WhisperModel("{current_model}", device=device, compute_type=compute_type, cpu_threads=cpu_threads if cpu_threads else os.cpu_count())

    # Build transcribe kwargs dynamically - only pass non-None values
    transcribe_kwargs = {{
        "language": {language_param}
    }}
    
    if vad_filter is not None:
        transcribe_kwargs["vad_filter"] = vad_filter
        if vad_params is not None:
            transcribe_kwargs["vad_parameters"] = vad_params
    
    if temperature is not None:
        transcribe_kwargs["temperature"] = temperature
    
    if merge_lines:
        transcribe_kwargs["no_speech_threshold"] = 0.6
        transcribe_kwargs["compression_ratio_threshold"] = 1.4

    # Add distil-whisper specific parameters
    if 'distil' in '{current_model}'.lower():
        transcribe_kwargs["condition_on_previous_text"] = False
        transcribe_kwargs["max_new_tokens"] = 128
        transcribe_kwargs["beam_size"] = 5
        print("Using distil-whisper optimized parameters")

    # audio_file is passed as positional argument, not keyword
    segments, info = model.transcribe(r"{audio_to_transcribe}", **transcribe_kwargs)
    
    # Update audio_duration from info if available
    if hasattr(info, 'duration'):
        audio_duration = info.duration
    
    if audio_duration > 0:
        print(f"Starting transcription (duration: {str(datetime.timedelta(seconds=int(audio_duration)))})")
    
    start_time = time.time()
    last_progress = 0
    segments_count = 0

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
        segments_count += 1

        # Progress update every second
        current_time = time.time()
        if current_time - last_progress >= 1.0 and audio_duration > 0:
            progress_pct = (segment.end / audio_duration) * 100
            elapsed = current_time - start_time
            if progress_pct > 0:
                eta = (elapsed / progress_pct * 100) - elapsed
                speed = segment.end / elapsed
                print("Progress: %.1f%% | Elapsed: %s | ETA: %s | Speed: %.1fx" % (
                    progress_pct,
                    str(datetime.timedelta(seconds=int(elapsed))),
                    str(datetime.timedelta(seconds=int(eta))),
                    speed
                ))
            last_progress = current_time

        write_event.wait(timeout=1.0)
        write_event.clear()

    # Final progress
    if audio_duration > 0:
        elapsed = time.time() - start_time
        speed = audio_duration / elapsed
        print("Transcription completed in %s (%.1fx real-time)" % (
            str(datetime.timedelta(seconds=int(elapsed))),
            speed
        ))
    
    stop_event.set()
    writer_thread.join(timeout=30)

    if os.path.exists(r"{unfinished_srt}") and os.path.getsize(r"{unfinished_srt}") > 10:
        if os.path.exists(r"{srt_file}"): os.remove(r"{srt_file}")
        os.rename(r"{unfinished_srt}", r"{srt_file}")

        # Recreate helper files for the final SRT file
        import transcribe
        transcribe.make_files(r"{srt_file}")
        
        # Create JSON metadata file
        import json
        metadata_file = r"{srt_file}".replace('.srt', '.metadata.json')
        metadata = {{
            "model": "{current_model}",
            "date": datetime.datetime.now().isoformat(),
            "source_file": r"{audio_to_transcribe}",
            "language": {language_param},
            "device": "{device}",
            "compute_type": "{compute_type}",
            "cpu_threads": {cpu_threads if cpu_threads else 'None'},
            "vad_enabled": {vad_filter},
            "temperature": {temperature},
            "segments_count": segments_count
        }}
        try:
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            print(f"Metadata saved to: {{metadata_file}}")
        except Exception as e:
            print(f"Warning: Could not create metadata file: {{e}}")

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
            if trimmed_audio_path and os.path.exists(trimmed_audio_path):
                os.unlink(trimmed_audio_path)
                write("Removed temporary trimmed audio file.")
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
                            create_helper_files(dir_path, srt_file, url)
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

def filter_garbage_segments(segments: List[Segment]) -> List[Segment]:
    """Remove segments that are likely to be garbage."""
    return [s for s in segments if not is_garbage(s)]

def merge_adjacent_identical_segments(segments: List[Segment]) -> List[Segment]:
    """Merge adjacent segments that have identical text."""
    if not segments:
        return segments

    merged: List[Segment] = []
    for s in segments:
        if merged and s.text.strip() == merged[-1].text.strip():
            merged[-1].end = s.end
        else:
            merged.append(s)
    return merged

def create_helper_files(dir_path: str, subtitle_file: str, url: str) -> None:
    """Create helper files (HTML redirect, batch file, shell script)"""
    print(f"Creating helper files for {subtitle_file}")
    try:
        # Convert to absolute path
        subtitle_file = os.path.abspath(subtitle_file)
        base_name = os.path.splitext(os.path.basename(subtitle_file))[0].replace('.unfinished','')
        print(f"Base name: {base_name}")
        print(f"Dir path: {dir_path}")
        print(f"URL: {url}")
        
        # Helper function to escape single quotes for shell scripts
        def escape_shell_single_quotes(text: str) -> str:
            """Escape single quotes for use in single-quoted shell strings."""
            return text.replace("'", "'\\''")
        
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
        
        # Shell script (.sh) - properly escape single quotes in paths
        try:
            sh_file = os.path.join(dir_path, f"{base_name}.sh")
            linux_path = subtitle_file.replace("\\", "/")
            escaped_url = escape_shell_single_quotes(url)
            escaped_path = escape_shell_single_quotes(linux_path)
            with open(sh_file, "w", encoding='utf-8') as f:
                f.write(f"#!/bin/bash\nmpv '{escaped_url}' --pause --input-ipc-server=/tmp/mpvsocket --sub-file='{escaped_path}' $@\n")
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
            with open(bat_file, "w", encoding="utf-8") as f:
                f.write('@echo off\n'
                    'setlocal DisableDelayedExpansion\n'
                    f'mpv "{url}" --pause --input-ipc-server=/tmp/mpvsocket --sub-file="{win_path}"\n'
                )
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
