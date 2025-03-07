
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
log_file = r"/home/half-debian/Documents/Youtube-Subs/GEMAPLYS/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.whisper.log"
file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
whisper_logger.addHandler(file_handler)

# Ensure output directory exists
os.makedirs(os.path.dirname(r"/home/half-debian/Documents/Youtube-Subs/GEMAPLYS/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.srt"), exist_ok=True)

def format_timestamp(seconds):
    """Convert seconds to SRT timestamp format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds % 1) * 1000)
    seconds = int(seconds)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

# Create a queue with size limit for memory management
segment_queue = queue.Queue(maxsize=100)
write_event = threading.Event()
stop_event = threading.Event()

# Set device and compute type
device = "cpu"
compute_type = "int8"
force_device = False  # Add force_device parameter

def write_segments():
    current_index = 1
    with open(r"/home/half-debian/Documents/Youtube-Subs/GEMAPLYS/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.unfinished.srt", "w", encoding="utf-8") as f:
        while not stop_event.is_set() or not segment_queue.empty():
            try:
                # Wait for new segments with timeout
                segment = segment_queue.get(timeout=0.5)
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
                
                # Write segment immediately
                f.write(f"{current_index}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{segment.text.strip()}\n\n")
                f.flush()  # Force write to disk
                
                current_index += 1
                segment_queue.task_done()
                write_event.set()  # Signal that we wrote something
                
                if current_index % 10 == 0:
                    print(f"Written {current_index} segments")
                    
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Error writing segment: {e}")

# Start writer thread
writer_thread = threading.Thread(target=write_segments, daemon=True)
writer_thread.start()

try:
    print(f"Starting transcription with model large-v3 on device {device}")
    print(f"Full log will be written to: {log_file}")
    
    # Initialize model with verbose logging
    model = faster_whisper.WhisperModel(
        "large-v3",
        device=device,
        compute_type=compute_type
    )
    
    # Process segments as they come
    segments, info = model.transcribe(r"/home/all/repos/.whisper-subs/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.mp3")
    
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
    if os.path.exists(r"/home/half-debian/Documents/Youtube-Subs/GEMAPLYS/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.unfinished.srt") and os.path.getsize(r"/home/half-debian/Documents/Youtube-Subs/GEMAPLYS/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.unfinished.srt") > 10:
        if os.path.exists(r"/home/half-debian/Documents/Youtube-Subs/GEMAPLYS/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.srt"):
            os.remove(r"/home/half-debian/Documents/Youtube-Subs/GEMAPLYS/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.srt")
        os.rename(r"/home/half-debian/Documents/Youtube-Subs/GEMAPLYS/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.unfinished.srt", r"/home/half-debian/Documents/Youtube-Subs/GEMAPLYS/2025-02-26_deixei meus inscritos me enviarem coisas e me mandaram só coisas malditas.large-v3.srt")
        print("Transcription completed successfully")
    else:
        print("Output file is empty or too small")
        exit(1)
        
except Exception as e:
    print(f"Error during transcription: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
finally:
    # Close log file handler
    file_handler.close()
    whisper_logger.removeHandler(file_handler)
