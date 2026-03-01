"""
Unified transcription module - single implementation for all transcription needs.
Uses faster_whisper directly without subprocess complexity.
"""

import os
import re
import logging
import threading
import datetime
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

import faster_whisper

# Setup logging
logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.WARNING)

@dataclass
class Segment:
    start: float
    end: float
    text: str


def format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds_val = seconds % 60
    milliseconds = int((seconds_val % 1) * 1000)
    seconds_int = int(seconds_val)
    return f"{hours:02d}:{minutes:02d}:{seconds_int:02d},{milliseconds:03d}"


def filter_garbage_segments(segments: List[Segment]) -> List[Segment]:
    """Remove segments that appear to be garbage/transcription errors."""
    filtered = []
    for seg in segments:
        text = seg.text.strip()
        # Skip very short segments with no real content
        if len(text) < 2:
            continue
        # Skip segments with only punctuation or special chars
        if re.match(r'^[\s\W]+$', text):
            continue
        filtered.append(seg)
    return filtered


def merge_adjacent_identical_segments(segments: List[Segment]) -> List[Segment]:
    """Merge adjacent segments with identical or very similar text."""
    if not segments:
        return []
    
    merged = [segments[0]]
    for s in segments[1:]:
        prev = merged[-1]
        # Merge if text is identical or very similar
        if prev.text.strip().lower() == s.text.strip().lower():
            prev.end = s.end
        else:
            merged.append(s)
    return merged


def transcribe_audio(
    audio_file: str,
    model_name: str,
    srt_file: str,
    language: Optional[str] = None,
    device: str = 'cpu',
    compute_type: str = 'int8',
    cpu_threads: Optional[int] = None,
    vad_filter: bool = False,
    vad_params: Optional[Dict] = None,
    callback: Optional[callable] = None
) -> bool:
    """
    Transcribe audio file and generate SRT subtitles.
    
    Args:
        audio_file: Path to audio file
        model_name: Whisper model name
        srt_file: Output SRT file path
        language: Language code (None for auto-detect)
        device: 'cuda' or 'cpu'
        compute_type: Quantization type (int8, float16, etc.)
        cpu_threads: Number of CPU threads (None = auto)
        vad_filter: Enable voice activity detection
        vad_params: VAD parameters dict
        callback: Optional callback for progress updates
    
    Returns:
        True if successful, False otherwise
    """
    import torch
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(srt_file) or '.', exist_ok=True)
    
    # Check CUDA availability
    if device == 'cuda' and not torch.cuda.is_available():
        device = 'cpu'
        compute_type = 'int8'
        if callback:
            callback("CUDA not available, falling back to CPU")
    
    try:
        if callback:
            callback(f"Loading model {model_name} on {device}...")
        
        # Load model
        whisper_model = faster_whisper.WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            device_index=0,
            cpu_threads=cpu_threads if cpu_threads else os.cpu_count()
        )
        
        if callback:
            callback(f"Transcribing {os.path.basename(audio_file)}...")
        
        # Setup VAD parameters
        vad_parameters = None
        if vad_filter and vad_params:
            vad_parameters = vad_params
        
        # Transcribe
        segments_gen, info = whisper_model.transcribe(
            audio_file,
            language=language,
            vad_filter=vad_filter,
            vad_parameters=vad_parameters,
            repetition_penalty=1.2,
            no_repeat_ngram_size=3,
            temperature=0.3,
            suppress_tokens=[-1]
        )
        
        if callback:
            callback(f"Detected language: {info.language} with probability {info.language_probability:.2f}")
        
        # Convert to list and process
        segments_list = [Segment(start=s.start, end=s.end, text=s.text) for s in segments_gen]
        
        # Post-processing
        segments_list = filter_garbage_segments(segments_list)
        segments_list = merge_adjacent_identical_segments(segments_list)
        
        if callback:
            callback(f"Writing {len(segments_list)} segments to SRT...")
        
        # Write SRT file
        with open(srt_file, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments_list, start=1):
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
                f.write(f"{i}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{segment.text}\n\n")
        
        if callback:
            callback(f"Successfully transcribed to {srt_file}")
        
        return True
        
    except Exception as e:
        error_msg = f"Transcription error: {str(e)}"
        if callback:
            callback(error_msg)
        logging.error(error_msg)
        return False


def transcribe_with_resume(
    audio_file: str,
    model_name: str,
    srt_file: str,
    language: Optional[str] = None,
    device: str = 'cpu',
    compute_type: str = 'int8',
    cpu_threads: Optional[int] = None,
    callback: Optional[callable] = None
) -> bool:
    """
    Transcribe with resume support for interrupted transcriptions.
    """
    # Check for existing unfinished transcription
    unfinished_srt = srt_file.replace('.srt', '.unfinished.srt')
    resume_offset = 0.0
    start_index = 0
    audio_to_use = audio_file
    
    # Try to resume from unfinished SRT
    if os.path.exists(unfinished_srt) and os.path.getsize(unfinished_srt) > 10:
        last_end_time, last_segment_num = get_srt_resume_info(unfinished_srt)
        if last_end_time > 0.1:
            resume_offset = last_end_time
            start_index = last_segment_num
            if callback:
                callback(f"Resuming from {last_end_time:.2f}s (segment {last_segment_num})")
            
            # Create partial audio file for resume
            resume_audio = os.path.splitext(audio_file)[0] + ".resume.m4a"
            try:
                import subprocess
                ss_time = str(datetime.timedelta(seconds=resume_offset))
                ffmpeg_cmd = [
                    'ffmpeg', '-y', '-ss', ss_time, '-i', audio_file,
                    '-c:a', 'aac', '-b:a', '192k', resume_audio
                ]
                if callback:
                    callback("Creating partial audio file for resume...")
                result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    audio_to_use = resume_audio
                else:
                    if callback:
                        callback(f"FFmpeg resume failed: {result.stderr}")
            except Exception as e:
                if callback:
                    callback(f"Resume audio creation failed: {e}")
    
    # Perform transcription
    success = transcribe_audio(
        audio_file=audio_to_use,
        model_name=model_name,
        srt_file=unfinished_srt,
        language=language,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        callback=callback
    )
    
    if success and os.path.exists(unfinished_srt):
        # Move unfinished to final
        if os.path.exists(srt_file):
            os.remove(srt_file)
        os.rename(unfinished_srt, srt_file)
        
        # Cleanup resume audio
        if audio_to_use != audio_file and os.path.exists(audio_to_use):
            os.remove(audio_to_use)
        
        return True
    
    return False


def get_srt_resume_info(srt_path: str) -> tuple:
    """
    Parse SRT file to find last segment's number and end time.
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
        
        for segment_block in reversed(segments):
            lines = segment_block.strip().split('\n')
            if len(lines) >= 2:
                try:
                    current_segment_number = int(lines[0])
                    time_line = lines[1]
                    match = re.search(
                        r'\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})',
                        time_line
                    )
                    if match:
                        end_time_str = match.group(1)
                        last_end_time = srt_time_to_seconds(end_time_str)
                        last_segment_number = current_segment_number
                        return last_end_time, last_segment_number
                except (ValueError, IndexError):
                    continue
        
        return 0.0, 0
    except Exception as e:
        logging.error(f"Could not parse SRT for resume: {e}")
        return 0.0, 0


def srt_time_to_seconds(time_str: str) -> float:
    """Convert SRT timestamp to seconds."""
    try:
        parts = re.split('[:,]', time_str)
        return (int(parts[0]) * 3600 + 
                int(parts[1]) * 60 + 
                int(parts[2]) + 
                int(parts[3]) / 1000.0)
    except (ValueError, IndexError):
        return 0.0


def make_files(srt_file, url=None):
    """
    Create helper files (HTML, .sh, .bat) for the given SRT file.
    
    Args:
        srt_file: Path to the SRT file
        url: Optional URL for helper files
    """
    if not srt_file:
        print("No SRT file provided")
        return
    
    try:
        print(f"Creating helper files for {srt_file}")
        
        if not os.path.exists(srt_file):
            os.makedirs(os.path.dirname(srt_file) or '.', exist_ok=True)
            with open(srt_file, 'w', encoding='utf-8') as f:
                f.write('Transcription in progress...')
        
        dir_path = os.path.dirname(srt_file)
        base_name = os.path.splitext(os.path.basename(srt_file))[0]
        
        # Handle both finished and unfinished files
        is_unfinished = '.unfinished' in base_name
        clean_base = base_name.replace('.unfinished', '') if is_unfinished else base_name
        
        # If URL was provided, use it directly
        if url:
            print(f"Using provided URL: {url}")
            create_helper_files(dir_path, srt_file, url)
            return
        
        # For unfinished files without URL, try to extract video ID from filename
        if is_unfinished:
            video_id = 'video_id_placeholder'
            try:
                import re
                match = re.search(r'[?&]v=([^&\s]+)', base_name)
                if match:
                    video_id = match.group(1)
                else:
                    video_id = base_name.split('_')[0]
                    if len(video_id) > 20:
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


def create_helper_files(dir_path, srt_file, url):
    """Create HTML, .sh, and .bat helper files for a subtitle file."""
    try:
        base_name = os.path.splitext(os.path.basename(srt_file))[0]
        clean_base = base_name.replace('.unfinished', '')
        
        # Create HTML file
        html_file = os.path.join(dir_path, f"{clean_base}.htm")
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(f'<meta http-equiv="refresh" content="0;url={url}">')
        
        # Create shell script
        sh_file = os.path.join(dir_path, f"{clean_base}.sh")
        with open(sh_file, 'w', encoding='utf-8') as f:
            f.write(f'#!/bin/bash\nxdg-open "{url}"\n')
        os.chmod(sh_file, 0o755)
        
        # Create batch file
        bat_file = os.path.join(dir_path, f"{clean_base}.bat")
        with open(bat_file, 'w', encoding='utf-8') as f:
            f.write(f'@echo off\nstart "" "{url}"\n')
        
        print(f"Created helper files for {clean_base}")
        
    except Exception as e:
        print(f"Error creating helper files: {e}")


# Convenience function for backward compatibility
def process_create(
    file: str,
    model_name: str,
    srt_file: str,
    language: Optional[str] = None,
    device: str = 'cpu',
    compute_type: str = 'int8',
    force_device: bool = False,
    auto: bool = True,
    write: callable = print,
    cpu_threads: Optional[int] = None
) -> bool:
    """
    Backward-compatible wrapper for unified transcription.
    """
    import torch
    
    # Auto-select model if requested
    if device == 'cuda' and auto:
        try:
            from whisper_model_chooser import WhisperModelChooser
            chooser = WhisperModelChooser()
            best = chooser.choose_best_model(english_only='en' in model_name)
            model_name = best['model']
            compute_type = best['compute_type']
            write(f"Selected model: {model_name} {compute_type}")
        except Exception as e:
            write(f"Model chooser failed: {e}")
    
    # Fallback to CPU if not forcing device
    if not force_device and device == 'cpu':
        compute_type = 'int8'
    
    write(f"Transcribe Model name: {model_name}")
    
    # Try with current model
    success = transcribe_with_resume(
        audio_file=file,
        model_name=model_name,
        srt_file=srt_file,
        language=language if language != 'none' else None,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        callback=write
    )
    
    if success:
        return True
    
    # Try smaller models if not forcing device
    if not force_device and device == 'cuda':
        write("GPU transcription failed, trying CPU...")
        return transcribe_with_resume(
            audio_file=file,
            model_name='large-v3',
            srt_file=srt_file,
            language=language if language != 'none' else None,
            device='cpu',
            compute_type='int8',
            cpu_threads=cpu_threads,
            callback=write
        )
    
    return False
