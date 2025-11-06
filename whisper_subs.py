#!/usr/bin/env python3
import os
import sys
import json
import argparse
import datetime
import re
import subprocess
import time
from urllib.parse import urlparse
import pyperclip

# Assuming these modules are in the same directory or installed
import transcribe
import twitch_vod
import model
import yt_dlp

# --- Configuration ---
APP_NAME = "WhisperSubs"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs")
JOBS_FILE = os.path.join(CONFIG_DIR, "jobs.json")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "history.txt")

# Ensure config directories exist
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Job Management ---
def get_jobs():
    if not os.path.exists(JOBS_FILE): return []
    try:
        with open(JOBS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_jobs(jobs):
    with open(JOBS_FILE, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=4)

def add_job(source, model_name):
    jobs = get_jobs()
    job_id = len(jobs) + 1
    new_job = {
        "id": job_id,
        "date": datetime.datetime.now().isoformat(),
        "model": model_name,
        "source": source,
        "status": "initializing",
        "tasks": []
    }
    jobs.append(new_job)
    save_jobs(jobs)
    return new_job

def update_job(job_id, updates):
    jobs = get_jobs()
    job_updated = False
    for job in jobs:
        if job["id"] == job_id:
            job.update(updates)
            job_updated = True
            break
    if job_updated:
        save_jobs(jobs)

def update_task_status(job_id, task_source, status, title=None):
    jobs = get_jobs()
    job_found = False
    for job in jobs:
        if job["id"] == job_id:
            job_found = True
            for task in job["tasks"]:
                if task["source"] == task_source:
                    task["status"] = status
                    if title:
                        task["title"] = title
                    break
            break
    if job_found:
        save_jobs(jobs)

def get_last_unfinished_job():
    jobs = get_jobs()
    for job in reversed(jobs):
        if job["status"] not in ["completed", "failed"]:
            return job
    return None

def list_jobs():
    jobs = get_jobs()
    if not jobs:
        print("No transcription jobs found.")
        return
    print(f"{'ID':<4} {'Date':<20} {'Model':<15} {'Status':<12} {'Progress':<12} {'Source'}")
    print("-" * 100)
    for job in jobs:
        date_str = datetime.datetime.fromisoformat(job['date']).strftime('%Y-%m-%d %H:%M')
        source_str = job['source'][:40] + '...' if len(job['source']) > 40 else job['source']
        
        total_tasks = len(job.get('tasks', []))
        completed_tasks = len([t for t in job.get('tasks', []) if t.get('status') in ['completed', 'skipped']])
        progress_str = f"{completed_tasks}/{total_tasks}" if total_tasks > 0 else "N/A"

        print(f"{job['id']:<4} {date_str:<20} {job['model']:<15} {job['status']:<12} {progress_str:<12} {source_str}")

# --- Core Class ---
class WhisperSubs:
    def __init__(self, model_name, device, compute_type, force, ignore_subs, sub_lang, run_mpv=False, strict_language_tier=True):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.force = force
        self.ignore_subs = ignore_subs
        self.sub_lang = sub_lang
        self.run_mpv = run_mpv
        self.strict_language_tier = strict_language_tier
        self.log_file = None
        self.channel_name = "unknown_channel"
        self.delay = 30
        self.start_delay = 30
        self.specified_browser = 'chrome'

    def log(self, message):
        message_str = str(message)
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {message_str}")
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message_str}\n")

    def is_youtube(self, url): return url and 'youtu' in urlparse(url).netloc
    def is_twitch(self, url): return url and 'twitch.tv' in urlparse(url).netloc
    def is_local_file(self, path): return path and os.path.exists(path)
    def is_local_dir(self, path): return path and os.path.isdir(path)

    def is_channel_or_playlist_url(self, url):
        if not self.is_youtube(url) or ('v=' in url and 'list=' in url): return False
        return any(indicator in url for indicator in ['@', '/channel/', '/c/', '/user/', 'youtube.com/playlist?list=', 'youtu.be/playlist?list='])
    def is_twitch_channel(self, url):
        parsed = urlparse(url)
        if 'twitch.tv' in parsed.netloc:
            path_parts = [p for p in parsed.path.split('/') if p]
            if len(path_parts) == 1:
                return path_parts[0]
            elif len(path_parts) == 2 and path_parts[1] == 'videos':
                return path_parts[0]
        return None

    def get_video_info(self, url):
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True}
            if self.specified_browser:
                ydl_opts['cookiesfrombrowser'] = (self.specified_browser,)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get('title', 'unknown_title'), info.get('channel') or info.get('uploader') or "unknown_channel"
        except Exception:
            return os.path.basename(url), "unknown_channel"

    def clean_youtube_url(self, url):
        """Clean YouTube URLs by removing tracking parameters and extracting just the video ID.
        
        Handles:
        - Full URLs (youtube.com/watch?v=ID)
        - Short URLs (youtu.be/ID)
        - URLs with timestamps, playlists, etc.
        """
        if not isinstance(url, str) or not url.strip():
            return url
            
        url = url.strip()
        
        # Handle youtu.be short links
        if 'youtu.be/' in url:
            # Extract the video ID (the part after youtu.be/)
            video_id = url.split('youtu.be/')[-1].split('?')[0].split('&')[0].split('#')[0]
            if len(video_id) == 11:  # YouTube video IDs are always 11 characters
                return f"https://youtu.be/{video_id}"
            return url  # Return original if we can't extract a valid ID
            
        # Handle full YouTube URLs
        if 'youtube.com/watch' in url or 'youtube.com/embed/' in url:
            from urllib.parse import urlparse, parse_qs, urlunparse
            
            try:
                # Parse the URL
                parsed = urlparse(url)
                
                # Extract video ID from the query parameters
                if 'youtube.com/watch' in url:
                    query = parse_qs(parsed.query)
                    if 'v' in query:
                        video_id = query['v'][0].split('&')[0]  # Get just the ID part
                        if len(video_id) == 11:  # Validate it's a proper YouTube ID
                            # Rebuild URL with just the video ID
                            clean_query = f"v={video_id}"
                            return urlunparse(parsed._replace(query=clean_query, fragment=''))
                
                # Handle embed URLs
                elif 'youtube.com/embed/' in url:
                    path_parts = parsed.path.split('/')
                    if len(path_parts) >= 3:
                        video_id = path_parts[2].split('?')[0]
                        if len(video_id) == 11:
                            return f"https://youtu.be/{video_id}"
                            
            except Exception as e:
                self.log(f"Error cleaning URL {url}: {e}")
        
        # Return original URL if we couldn't clean it
        return url

    def clean_filename(self, filename):
        # If it's a YouTube URL, clean it first
        if isinstance(filename, str) and ('youtube.com' in filename or 'youtu.be' in filename):
            filename = self.clean_youtube_url(filename)
            
        # Remove invalid characters from filename
        filename = re.sub(r'[\\/*?:"<>|]', '_', str(filename))
        return filename.strip()

    def resolve_source_to_tasks(self, source):
        """Resolve source to tasks (eager loading, kept for backward compatibility)."""
        self.log(f"[DEPRECATED] Using eager loading for source: {source}")
        return list(self.resolve_source_to_tasks_lazy(source))

    def resolve_source_to_tasks_lazy(self, source):
        """Generator that yields tasks one at a time instead of resolving all upfront."""
        self.log(f"Resolving source (lazy): {source}")
        
        # Clean YouTube URLs
        if "youtu" in source and '&llst=' in source:
            source = source[:source.find('&llst=')]
        
        # Local directory - yield files one by one
        if self.is_local_dir(source):
            self.log(f"Source is a local directory.")
            for root, _, files in os.walk(source):
                for file in files:
                    if file.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.ogg', '.mkv')):
                        file_path = os.path.join(root, file)
                        yield {
                            "source": file_path,
                            "status": "pending",
                            "title": os.path.basename(file_path)
                        }
        
        # Single local file
        elif self.is_local_file(source):
            self.log("Source is a single local file.")
            yield {
                "source": source,
                "status": "pending",
                "title": os.path.basename(source)
            }
        
        # Twitch channel - yield VODs one by one
        elif twitch_username := self.is_twitch_channel(source):
            self.log(f"Source is Twitch channel: {twitch_username}")
            downloader = twitch_vod.StreamlinkVODDownloader()
            user_id = downloader.get_user_id_by_login(twitch_username)
            if user_id:
                vods = downloader.get_all_vods(user_id)
                for vod in vods:
                    vod_url = f"https://www.twitch.tv/videos/{vod['id']}"
                    yield {
                        "source": vod_url,
                        "status": "pending",
                        "title": vod.get('title', f"VOD {vod['id']}")
                    }
        
        # YouTube channel/playlist - yield videos one by one using pagination
        elif self.is_channel_or_playlist_url(source):
            self.log(f"Source is YouTube channel/playlist (streaming entries).")
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,  # Don't download full metadata
                'ignoreerrors': True,
                'playlistend': None,  # Process all videos
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    # extract_info returns a generator if extract_flat is True
                    info = ydl.extract_info(source, download=False)
                    
                    if info and 'entries' in info:
                        for i, entry in enumerate(info['entries'], 1):
                            if entry and entry.get('url'):
                                self.log(f"Discovered video {i}: {entry.get('title', 'Unknown')}")
                                yield {
                                    "source": entry['url'],
                                    "status": "pending",
                                    "title": entry.get('title', 'Unknown')
                                }
                            else:
                                self.log(f"Skipping invalid entry {i}")
                except Exception as e:
                    self.log(f"Error resolving playlist/channel: {e}")
        
        # Single URL
        else:
            self.log("Source is a single URL.")
            yield {
                "source": source,
                "status": "pending",
                "title": os.path.basename(source)
            }
    def check_and_download_subs(self, url, output_dir, title):
        if self.ignore_subs: 
            return False
        self.log(f"Checking for existing subtitles for '{title}'...")
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'listsubtitles': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl: 
                info = ydl.extract_info(url, download=False)
            
            if info is None:
                self.log(f"Failed to get video info for '{title}'")
                return False
                
            video_lang = (info.get('language') or 'en').split('-')[0]
            target_langs = {video_lang, self.sub_lang} if self.sub_lang else {video_lang}
            best_sub_lang = next((lang for lang in target_langs 
                                if any(not s.get('is_automatic') 
                                    for s in info.get('subtitles', {}).get(lang, []))), None)
            
            if not best_sub_lang:
                self.log("No suitable human-made subtitles found.")
                return False

            self.log(f"Found human-made '{best_sub_lang}' subtitles. Downloading...")
            
            # Get timestamp from video info if available
            timestamp = info.get('timestamp', '')
            date_time = datetime.datetime.fromtimestamp(timestamp) if timestamp else datetime.datetime.now()
            timeday = date_time.strftime('%Y-%m-%d_%H-%M')
            
            # Create base filename with timestamp and cleaned title
            safe_title = f"{timeday}_{self.clean_filename(title)}"
            
            # Use proper template in output directory
            sub_template = os.path.join(output_dir, f"{safe_title}.%(ext)s")
            ydl_opts_dl = {
                'quiet': True, 
                'no_warnings': True, 
                'writesubtitles': True, 
                'subtitleslangs': [best_sub_lang], 
                'subtitlesformat': 'srt', 
                'skip_download': True, 
                'outtmpl': sub_template
            }
            
            with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl: 
                ydl.download([url])
            
            # Look for the downloaded subtitle with language code
            expected_file = os.path.join(output_dir, f"{safe_title}.{best_sub_lang}.srt")
            final_file = os.path.join(output_dir, f"{safe_title}.srt")
            
            if os.path.exists(expected_file):
                if os.path.exists(final_file): 
                    os.remove(final_file)
                os.rename(expected_file, final_file)
                self.log(f"Subtitle saved to {final_file}")
                transcribe.make_files(final_file, url=url)
                return True
            else:
                self.log(f"Expected subtitle file not found: {expected_file}")
                
        except Exception as e: 
            self.log(f"Error checking subtitles: {e}")
        
        return False
    def download_audio(self, url, output_path):
        """Downloads audio and returns the actual file path."""
        self.log(f"Downloading audio from {url}...")
        
        # Ensure output directory exists
        os.makedirs(output_path, exist_ok=True)
        
        title = None
        # Clean the URL first to remove playlist parameters
        clean_url = self.clean_youtube_url(url) if self.is_youtube(url) else url
        
        # Quick check for existing files before attempting download
        if not self.force:
            try:
                ydl_opts = {'quiet': True, 'no_warnings': True}
                if self.specified_browser:
                    ydl_opts['cookiesfrombrowser'] = (self.specified_browser,)
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(clean_url, download=False)
                    if info is None:
                        self.log(f"Failed to get video info for {clean_url}")
                        return None
                        
                    # Get timestamp and format it
                    timestamp = info.get('timestamp', '')
                    date_time = datetime.datetime.fromtimestamp(timestamp) if timestamp else datetime.datetime.now()
                    timeday = date_time.strftime('%Y-%m-%d_%H-%M')
                    
                    # Clean and format the title
                    clean_title = self.clean_filename(info.get('title', 'unknown'))
                    base_title = f"{timeday}_{clean_title}"
                    
                    # Check for existing files with various extensions
                    for ext in ['.mp3', '.m4a', '.webm', '.ogg']:
                        # Check both with and without model name for backward compatibility
                        for pattern in [f"{base_title}.{self.model_name}{ext}", f"{base_title}{ext}"]:
                            existing_file = os.path.join(output_path, pattern)
                            if os.path.exists(existing_file):
                                self.log(f"File already exists: {existing_file}")
                                return existing_file
            except Exception:
                pass  # If we can't check, just proceed with download
        
        # Change to output directory like the old version
        original_cwd = os.getcwd()
        os.chdir(output_path)
        
        try:
            while True:
                try:
                    # Get video info to build the output filename
                    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                        info = ydl.extract_info(clean_url, download=False)
                        if info is None:
                            self.log(f"Failed to get video info for {clean_url}")
                            return None
                            
                        # Get timestamp and format it
                        timestamp = info.get('timestamp', '')
                        date_time = datetime.datetime.fromtimestamp(timestamp) if timestamp else datetime.datetime.now()
                        timeday = date_time.strftime('%Y-%m-%d_%H-%M')
                        
                        # Clean and format the title
                        clean_title = self.clean_filename(info.get('title', 'unknown'))
                        base_title = f"{timeday}_{clean_title}"
                        output_template = f"{base_title}.{self.model_name}.%(ext)s"
                        
                        ydl_opts = {
                            'outtmpl': output_template,
                            'format': 'bestaudio[ext=m4a]/bestaudio/best[height<=720]/best',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'm4a',
                                'preferredquality': '192',
                            }],
                            'writethumbnail': True,
                            'quiet': True,
                            'no_warnings': True,
                        'ignoreerrors': True,
                        'sleep_interval': 10,
                        'max_sleep_interval': 30,
                        'sleep_interval_requests': 5,
                        'retries': 3,
                        'fragment_retries': 3,
                    }
                    
                    if self.specified_browser:
                        ydl_opts['cookiesfrombrowser'] = (self.specified_browser,)
                        
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        # Get title if we don't have it yet
                        if not title:
                            info = ydl.extract_info(url, download=False)
                            if info is None:
                                self.log(f"Failed to get video info for {url}")
                                return None
                            timestamp = info.get('timestamp', '')
                            date_time = datetime.datetime.fromtimestamp(timestamp) if timestamp else datetime.datetime.now()
                            timeday = date_time.strftime('%Y-%m-%d_%H-%M')
                            title = timeday + '_' + self.clean_filename(info.get('title', 'unknown'))
                            title = f"{title}.{self.model_name}"
                        
                        ydl.download([url])
                    
                    # Look for the downloaded file
                    for ext in ['.mp3', '.m4a', '.webm', '.ogg']:
                        predicted_path = f"{title}{ext}"
                        full_path = os.path.join(output_path, predicted_path)
                        if os.path.exists(full_path):
                            self.log(f"Successfully downloaded: {full_path}")
                            return full_path
                    
                    # Fallback: find any new audio file in the directory
                    for file in os.listdir('.'):
                        if file.endswith(('.mp3', '.m4a', '.webm', '.ogg')):
                            full_path = os.path.join(output_path, file)
                            self.log(f"Found audio file: {full_path}")
                            return full_path
                    
                    self.log(f"Expected file not found: {title}")
                    return None
                    
                except Exception as e:
                    error_str = str(e).lower()
                    if 'rate' in error_str or 'unavailable' in error_str:
                        self.delay = min(self.delay * 1.5, 3600)
                        self.log(f"Download failed (rate limit?). Retrying in {self.delay:.0f}s...")
                        time.sleep(self.delay)
                        continue
                    else:
                        self.log(f"Audio download failed: {e}")
                        return None
                        
        finally:
            # Always restore original working directory
            os.chdir(original_cwd)
    def get_unique_id(self, source):
        if self.is_youtube(source): return (re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', source) or [None, None])[1]
        if self.is_twitch(source): return (re.search(r'/videos/(\d+)', source) or [None, None])[1]
        if self.is_local_file(source): return os.path.basename(source)
        return source


    def is_processed(self, unique_id):
        """
        Check if a video has been processed with this model or a better one.
        
        Logic:
        - If processed with exact same model → skip
        - If processed with a larger/better model → skip
        - If processed with smaller/worse model → re-process
        
        Model hierarchy:
        - tiny < base < small < medium < large < large-v2 < large-v3
        - English models (.en) are separate: tiny.en < base.en < small.en < medium.en
        - Distil models are treated as their base equivalents
        
        Args:
            unique_id: Video identifier to check
            
        Controlled by --cross-tier flag:
        - False (default): Strict separation - only compare within same language tier
        - True: Allow cross-tier comparison using normalized indices
        (removes .en offset so large-v3 > medium.en works correctly)
        """
        if not os.path.exists(HISTORY_FILE):
            return False
        
        # Get current model info
        current_model_index = model.getIndex(self.model_name)
        if current_model_index == -1:
            return False
        
        current_is_english = '.en' in self.model_name
        
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                
                history_id = parts[0]
                history_model = parts[1]
                
                if history_id != unique_id:
                    continue
                
                history_model_index = model.getIndex(history_model)
                if history_model_index == -1:
                    continue
                
                history_is_english = '.en' in history_model
                
                # === IMPROVED CROSS-TIER LOGIC ===
                if self.strict_language_tier:
                    # STRICT MODE: Can only compare models of same language type
                    if current_is_english != history_is_english:
                        continue
                    
                    # Same tier: Direct comparison
                    if history_model_index >= current_model_index:
                        return True
                else:
                    # PERMISSIVE MODE: Normalize indices for fair comparison
                    # Remove the .en offset (indices 7-10 become 0-3)
                    current_normalized = current_model_index - 7 if current_is_english else current_model_index
                    history_normalized = history_model_index - 7 if history_is_english else history_model_index
                    
                    # Now compare normalized values
                    # large-v3 (6) vs medium.en (10 -> 3): 6 >= 3 → large-v3 wins ✅
                    # medium.en (10 -> 3) vs large-v3 (6): 3 >= 6 → re-process ✅
                    if history_normalized >= current_normalized:
                        return True
                # ==================================
        
        return False
    def mark_as_processed(self, unique_id):
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{unique_id} {self.model_name}\n")
    def process_task(self, job_id, task):
        task_source = task['source']
        unique_id = self.get_unique_id(task_source)
        if not self.force and self.is_processed(unique_id):
            self.log(f"Skipping task '{task_source}' - already processed.")
            update_task_status(job_id, task_source, 'skipped', task['title'])
            return

        audio_file, is_local = None, self.is_local_file(task_source)
        try:
            title, self.channel_name = self.get_video_info(task_source)
            if is_local: 
                self.channel_name = "local_files"
            update_task_status(job_id, task_source, 'processing', title)

            channel_dir = os.path.join(OUTPUT_DIR, self.clean_filename(self.channel_name))
            os.makedirs(channel_dir, exist_ok=True)

            if not is_local and self.check_and_download_subs(task_source, channel_dir, title):
                self.log(f"Downloaded existing subtitle for '{title}'.")
                self.mark_as_processed(unique_id)
                update_task_status(job_id, task_source, 'skipped')
                return

            # FIX: Just pass the directory, not a template path
            audio_file = task_source if is_local else self.download_audio(task_source, channel_dir)
            if not audio_file or not os.path.exists(audio_file):
                # Log what files exist in the directory to debug
                self.log(f"Audio file not found: {audio_file}")
                self.log(f"Files in {channel_dir}: {os.listdir(channel_dir) if os.path.exists(channel_dir) else 'Directory does not exist'}")
                return

            update_task_status(job_id, task_source, 'transcribing')
            # Get base filename without extension and ensure it includes the model name
            base_name = os.path.splitext(os.path.basename(audio_file))[0]
            if not base_name.endswith(f".{self.model_name}"):
                base_name = f"{base_name}.{self.model_name}"
            srt_file = os.path.join(channel_dir, f"{base_name}.srt")
            
            # Create helper files (bash, bat, thumbnail) before transcription
            transcribe.make_files(srt_file.replace('.srt', '.unfinished.srt'), url=task_source)
            
            if transcribe.process_create(file=audio_file, model_name=self.model_name, srt_file=srt_file, device=self.device, compute_type=self.compute_type, write=self.log):
                self.log("Transcription successful.")
                # Update the SRT filename in case it was changed during processing
                if os.path.exists(srt_file):
                    base_name = os.path.splitext(srt_file)[0]
                    new_srt_file = f"{base_name}.srt"
                    if new_srt_file != srt_file and os.path.exists(new_srt_file):
                        srt_file = new_srt_file
                transcribe.make_files(srt_file, url=task_source)
                update_task_status(job_id, task_source, 'completed')
                self.mark_as_processed(unique_id)
                
                # Launch mpv in background if --run option is specified
                if hasattr(self, 'run_mpv') and self.run_mpv:
                    self.launch_mpv(audio_file, srt_file, task_source)
            else:
                raise Exception("Transcription process failed.")
                
        except Exception as e:
            self.log(f"Error on task '{task_source}': {e}")
            update_task_status(job_id, task_source, 'failed')
            
        finally:
            if audio_file and not is_local and os.path.exists(audio_file):
                try:
                    self.log(f"Removing temp audio: {audio_file}")
                    os.remove(audio_file)
                except OSError as e:
                    self.log(f"Error removing temp file: {e}")

    def launch_mpv(self, audio_file, srt_file, task_source):
        """Launch mpv with the audio file, subtitles, and --pause flag."""
        import subprocess
        try:
            # Determine the media source to use - prefer the original source if it's a URL
            # If it's a local file, use the audio file directly
            is_local = self.is_local_file(task_source)
            media_source = audio_file if is_local else task_source
            
            # Create the mpv command with --pause and input-ipc-server
            cmd = [
                'mpv',
                media_source,
                '--pause',
                '--input-ipc-server=/tmp/mpvsocket',
                f'--sub-file={srt_file}'
            ]
            
            self.log(f"Launching mpv: {' '.join(cmd)}")
            
            # Run mpv in the background
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log("mpv launched in background with --pause and mpvsocket")
            
        except Exception as e:
            self.log(f"Error launching mpv: {e}")
    
    def process_with_lazy_resolution(self, job):
        """Process a job using lazy task resolution.
        
        Tasks are resolved and processed one at a time, with progress saved after each.
        """
        self.log(f"Starting job {job['id']} with lazy resolution")
        
        # Handle multiple sources
        sources = job['source'] if isinstance(job['source'], list) else [job['source']]
        
        # Get existing tasks to know where to resume from
        existing_tasks = job.get('tasks', [])
        processed_sources = {task['source'] for task in existing_tasks 
                           if task['status'] in ['completed', 'skipped', 'failed']}
        
        total_processed = len(processed_sources)
        total_discovered = len(existing_tasks)
        
        update_job(job['id'], {"status": "processing"})
        
        # Process each source
        for source in sources:
            self.log(f"Processing source: {source}")
            
            # Use lazy generator to get tasks one by one
            for task in self.resolve_source_to_tasks_lazy(source):
                total_discovered += 1
                
                # Skip if already processed
                if task['source'] in processed_sources:
                    self.log(f"Skipping already processed: {task['title']}")
                    continue
                
                # Add task to job
                existing_tasks.append(task)
                update_job(job['id'], {"tasks": existing_tasks})
                
                # Process the task
                self.log(f"Processing [{total_processed + 1}/{total_discovered}]: {task['title']}")
                self.process_task(job['id'], task)
                
                # Update progress
                total_processed += 1
                processed_sources.add(task['source'])
                
                # Update job status after each task
                updated_jobs = get_jobs()
                current_job = next((j for j in updated_jobs if j['id'] == job['id']), None)
                if current_job:
                    self.log(f"Progress: {total_processed}/{total_discovered} tasks completed")
        
        # Mark job as completed
        final_status = "completed"
        update_job(job['id'], {"status": final_status})
        self.log(f"Job {job['id']} finished with status: {final_status}")

    def process(self, job_or_source):
        """Main processing entry point."""
        # Create or resume job
        if isinstance(job_or_source, dict):
            job = job_or_source
        else:
            job = add_job(job_or_source, self.model_name)
        
        # Normalize source to list
        if isinstance(job['source'], str):
            if "\n" in job['source']:
                job['source'] = job['source'].split('\n')
            else:
                job['source'] = [job['source']]
        
        # Use lazy resolution for better performance and resume capability
        self.process_with_lazy_resolution(job)
def read_sources_from_file(filename):
    """Read sources from a file, one per line, ignoring empty lines and comments."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f 
                   if line.strip() and not line.strip().startswith('#')]
    except FileNotFoundError:
        print(f"Error: File not found: {filename}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file {filename}: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Transcribe audio from various sources.",
        usage="""whisper_subs.py <model> [source] [options]
           whisper_subs.py -p [file.txt]
           whisper_subs.py -l | --list
           whisper_subs.py -c | --continue
        """
    )
    
    # Model and source arguments
    model_group = parser.add_argument_group('Source and Model')
    model_group.add_argument('model', nargs='?', 
                           help="Whisper model name/index. Required unless using -l, -c, or -p.")
    model_group.add_argument('source', nargs='?', 
                           help="URL, local file/directory path, or multiple paths/URLs separated by newlines.")
    
    # Action arguments
    action_group = parser.add_argument_group('Actions')
    action_group.add_argument('-l', '--list', action='store_true', 
                            help="List all jobs and exit.")
    action_group.add_argument('-c', '--continue', dest='continue_last', 
                            action='store_true', 
                            help="Continue the last unfinished job.")
    action_group.add_argument('-p', '--process-file', nargs='?', const='Youtube-Subs/process.txt',
                            help="Read sources from a file (one per line). If no file is specified, uses 'Youtube-Subs/process.txt'.")
    
    # Processing options
    process_group = parser.add_argument_group('Processing Options')
    process_group.add_argument('-g', '--gpu', action='store_true', 
                             help="Use GPU (CUDA).")
    process_group.add_argument('--device', default='cpu', 
                             help="Device to use ('cpu', 'cuda').")
    process_group.add_argument('--compute', default='int8', 
                             help="Compute type ('int8', 'float16').")
    process_group.add_argument('-f', '--force', action='store_true', 
                             help="Force transcription even if already processed.")
    process_group.add_argument('-i', '--ignore-subs', action='store_true', 
                             help="Ignore existing subtitles.")
    process_group.add_argument('-lang', '--language', 
                             help="Language code for subtitle priority.")
    process_group.add_argument('-r', '--run', action='store_true', 
                             help="Run mpv in background after transcription.")
    parser.add_argument('--cross-tier', action='store_true', dest='strict_language_tier',
                       help="Allow comparison between multilingual and English-only models. "
                            "By default, large-v3 and medium.en are treated as incomparable. "
                            "Use this flag to compare them by raw model index.")
    args = parser.parse_args()

    if args.list: 
        list_jobs()
        return

    # Handle continue case first
    if args.continue_last:
        job_or_source = get_last_unfinished_job()
        if not job_or_source: 
            print("No unfinished jobs to continue.")
            return
        print(f"Continuing job ID {job_or_source['id']}: {job_or_source['source']}")
        model_to_use = job_or_source['model']
    # Handle process file case
    elif args.process_file is not None:
        print(f"Reading sources from file: {args.process_file}")
        sources = read_sources_from_file(args.process_file)
        if not sources:
            print(f"No valid sources found in {args.process_file}")
            return
        job_or_source = '\n'.join(sources)
        model_to_use = args.model
    else:
        # Handle normal source input
        job_or_source = args.source
        model_to_use = args.model
        
        # If no source provided, check clipboard
        if not job_or_source:
            try:
                job_or_source = pyperclip.paste().strip()
                if not job_or_source: 
                    parser.error("No source provided and clipboard is empty.")
                print(f"Using source from clipboard: {job_or_source}")
            except Exception as e: 
                parser.error(f"No source provided and could not read clipboard: {e}")
    
    if not model_to_use: 
        parser.error("Model argument is required unless using --list or --continue.")
    
    processor = WhisperSubs(
        model_name=model.getName(model_to_use), 
        device='cuda' if args.gpu else args.device, 
        compute_type=args.compute, 
        force=args.force, 
        ignore_subs=args.ignore_subs, 
        sub_lang=args.language,
        run_mpv=args.run,
        strict_language_tier=args.strict_language_tier
    )
    processor.process(job_or_source)

if __name__ == "__main__":
    main()
