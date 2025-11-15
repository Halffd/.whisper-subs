#!/usr/bin/env python3
"""
Live Stream Transcription Module

Handles real-time transcription of live streams from Twitch/YouTube.
"""
import os
import sys
import time
import subprocess
import threading
import queue
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
import yt_dlp


class LiveStreamTranscriber:
    """Handles real-time transcription of live streams."""
    
    def __init__(self, model_name='base.en', device='cpu', compute_type='int8', 
                 output_dir=None, log_func=print):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.output_dir = output_dir or os.path.expanduser("~/Documents/Youtube-Subs")
        self.log_func = log_func
        self.download_process = None
        self.transcription_process = None
        self.is_running = False
        self.temp_dir = None
        
    def log(self, message):
        """Log message with timestamp."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.log_func(f"[{timestamp}] [LIVE] {message}")
    
    def download_stream(self, url, output_file):
        """Download live stream in background."""
        self.log(f"Starting live stream download from: {url}")
        
        download_opts = [
            'yt-dlp',
            '--live-from-start',
            '--no-part',  # Write directly to final file instead of .part
            '-f', 'bestaudio/best[height<=720]/best',  # Best audio or best video with max 720p
            '--audio-format', 'm4a',
            '--audio-quality', '0',
            url,
            '-o', output_file
        ]
        
        try:
            self.download_process = subprocess.Popen(
                download_opts,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            return True
        except Exception as e:
            self.log(f"Error starting download: {e}")
            return False
    
    def transcribe_in_background(self, audio_file, srt_file):
        """Start transcription in background while download continues."""
        def transcribe_worker():
            import transcribe  # Import here to avoid circular imports
            
            # Wait for some initial audio data
            initial_wait = 0
            max_initial_wait = 60  # Wait up to 60 seconds for initial data
            while initial_wait < max_initial_wait:
                if os.path.exists(audio_file) and os.path.getsize(audio_file) > 500_000:  # 500KB
                    break
                time.sleep(5)
                initial_wait += 5
            
            if not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
                self.log("Downloaded file is empty after waiting")
                return
                
            # Initial transcription
            self.log("Starting initial transcription...")
            success = transcribe.process_create(
                file=audio_file,
                model_name=self.model_name,
                srt_file=srt_file,
                device=self.device,
                compute_type=self.compute_type,
                force_device=False,
                write=self.log
            )
            
            if not success:
                self.log("Initial transcription failed")
                return
            
            self.log("Initial transcription completed")
            
            # Now continue with periodic updates as file grows
            last_size = os.path.getsize(audio_file)
            check_interval = 30  # seconds
            
            while self.is_running:
                time.sleep(check_interval)
                
                if not os.path.exists(audio_file):
                    self.log("Audio file disappeared, stopping")
                    break
                    
                current_size = os.path.getsize(audio_file)
                
                if current_size > last_size * 1.1:  # File grew significantly
                    self.log(f"Audio file grew from {last_size} to {current_size}, updating transcription...")
                    
                    # Update transcription with new audio
                    success = transcribe.process_create(
                        file=audio_file,
                        model_name=self.model_name,
                        srt_file=srt_file,
                        device=self.device,
                        compute_type=self.compute_type,
                        force_device=False,
                        write=self.log
                    )
                    
                    if success:
                        last_size = current_size
                        self.log("Transcription updated successfully")
                    else:
                        self.log("Transcription update failed")
        
        # Start transcription thread
        self.transcription_process = threading.Thread(target=transcribe_worker, daemon=True)
        self.transcription_process.start()
    
    def start_transcription(self, url):
        """Start live stream transcription."""
        if not url:
            raise ValueError("URL is required")
            
        self.is_running = True
        self.temp_dir = tempfile.mkdtemp(prefix="whisper_live_")
        
        try:
            # Create output files
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M')
            clean_title = self._clean_filename(url.split('/')[-1])  # Simple title from URL
            audio_file = os.path.join(self.temp_dir, f"live_{timestamp}_{clean_title}.m4a")
            srt_file = os.path.join(self.temp_dir, f"live_{timestamp}_{clean_title}.srt")
            
            # Start download in background
            if not self.download_stream(url, audio_file):
                raise Exception("Failed to start download")
            
            # Start transcription in background
            self.transcribe_in_background(audio_file, srt_file)
            
            # Wait for download process to complete
            self.log("Waiting for live stream to end...")
            stdout, stderr = self.download_process.communicate()
            
            if self.download_process.returncode != 0:
                self.log(f"Download process exited with code {self.download_process.returncode}")
                self.log(f"Error: {stderr.decode()}")
            
            # Wait a bit for final transcription
            time.sleep(10)
            self.is_running = False
            
            # Move final files to output directory
            final_srt = os.path.join(self.output_dir, os.path.basename(srt_file))
            final_audio = os.path.join(self.output_dir, os.path.basename(audio_file))
            
            if os.path.exists(srt_file):
                shutil.move(srt_file, final_srt)
                self.log(f"Final subtitles saved to: {final_srt}")
                
            if os.path.exists(audio_file):
                shutil.move(audio_file, final_audio)
                self.log(f"Final audio saved to: {final_audio}")
        
        except Exception as e:
            self.log(f"Error during live transcription: {e}")
        finally:
            # Cleanup
            self.stop()
    
    def stop(self):
        """Stop live transcription."""
        self.is_running = False
        
        # Kill download process if running
        if self.download_process and self.download_process.poll() is None:
            try:
                self.download_process.terminate()
                self.download_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.download_process.kill()
        
        # Cleanup temp directory
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                self.log(f"Error cleaning up temp directory: {e}")
    
    def _clean_filename(self, filename):
        """Clean filename of invalid characters."""
        import re
        # Remove invalid characters from filename
        filename = re.sub(r'[\\/*?:"<>|]', '_', str(filename))
        return filename.strip()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Live Stream Transcription")
    parser.add_argument("url", help="URL of the live stream")
    parser.add_argument("--model", default="base.en", help="Whisper model to use")
    parser.add_argument("--device", default="cpu", help="Device to use (cpu, cuda, mps)")
    parser.add_argument("--compute", default="int8", help="Compute type (int8, float16)")
    parser.add_argument("--output-dir", help="Output directory for subtitles")
    
    args = parser.parse_args()
    
    transcriber = LiveStreamTranscriber(
        model_name=args.model,
        device=args.device,
        compute_type=args.compute,
        output_dir=args.output_dir,
        log_func=print
    )
    
    try:
        transcriber.start_transcription(args.url)
        print("Live stream transcription completed")
    except KeyboardInterrupt:
        print("\nStopping live stream transcription...")
        transcriber.stop()
    except Exception as e:
        print(f"Error: {e}")
        transcriber.stop()