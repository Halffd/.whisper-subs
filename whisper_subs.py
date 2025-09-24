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
import model  # Assuming model.py provides model_names
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
    """Loads transcription jobs from the JSON file."""
    if not os.path.exists(JOBS_FILE):
        return []
    try:
        with open(JOBS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_jobs(jobs):
    """Saves transcription jobs to the JSON file."""
    with open(JOBS_FILE, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=4)

def add_job(source, model_name, title):
    """Adds a new job to the jobs file."""
    jobs = get_jobs()
    job_id = len(jobs) + 1
    new_job = {
        "id": job_id,
        "date": datetime.datetime.now().isoformat(),
        "model": model_name,
        "title": title,
        "source": source,
        "status": "pending"
    }
    jobs.append(new_job)
    save_jobs(jobs)
    return job_id

def update_job_status(job_id, status, new_title=None):
    """Updates the status and optionally the title of a specific job."""
    jobs = get_jobs()
    for job in jobs:
        if job["id"] == job_id:
            job["status"] = status
            if new_title:
                job["title"] = new_title
            break
    save_jobs(jobs)

def get_last_unfinished_job():
    """Finds the most recent job that is not completed."""
    jobs = get_jobs()
    for job in reversed(jobs):
        if job["status"] not in ["completed", "failed", "skipped"]:
            return job
    return None

def list_jobs():
    """Prints a formatted list of all jobs."""
    jobs = get_jobs()
    if not jobs:
        print("No transcription jobs found.")
        return
    print(f"{'ID':<4} {'Date':<20} {'Model':<12} {'Status':<12} {'Title'}")
    print("-" * 80)
    for job in jobs:
        date_str = datetime.datetime.fromisoformat(job['date']).strftime('%Y-%m-%d %H:%M')
        title_str = job['title'][:40] + '...' if len(job['title']) > 40 else job['title']
        print(f"{job['id']:<4} {date_str:<20} {job['model']:<12} {job['status']:<12} {title_str}")

# --- Core Class ---

class WhisperSubs:
    def __init__(self, model_name, device, compute_type, force, ignore_subs, sub_lang):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.force = force
        self.ignore_subs = ignore_subs
        self.sub_lang = sub_lang
        self.log_file = None
        self.channel_name = "unknown_channel"
        self.delay = 30
        self.start_delay = 30

    def log(self, message):
        """Simple logger."""
        message_str = str(message)
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {message_str}")
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message_str}\n")

    def is_youtube(self, url):
        return url and 'youtu' in urlparse(url).netloc

    def is_twitch(self, url):
        return url and 'twitch.tv' in urlparse(url).netloc

    def is_local_file(self, path):
        return path and os.path.exists(path)
        
    def is_channel_or_playlist_url(self, url):
        if not self.is_youtube(url):
            return False
        if 'v=' in url and 'list=' in url:
            return False
        true_playlist_indicators = [
            '@', '/channel/', '/c/', '/user/',
            'youtube.com/playlist?list=', 'youtu.be/playlist?list=',
        ]
        return any(indicator in url for indicator in true_playlist_indicators)

    def is_twitch_channel(self, url):
        parsed = urlparse(url)
        if 'twitch.tv' in parsed.netloc:
            path_parts = [part for part in parsed.path.split('/') if part]
            if len(path_parts) == 1 or (len(path_parts) == 2 and path_parts[1] in ['videos', 'clips', 'about']):
                if path_parts[0] != 'videos': # Exclude direct VOD links
                    return path_parts[0]
        return None

    def get_video_info(self, url):
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'unknown_title')
                channel = info.get('channel') or info.get('uploader') or "unknown_channel"
                return title, channel
        except Exception:
            return os.path.basename(url), "unknown_channel"

    def clean_filename(self, filename):
        return re.sub(r'[<>:"/\\|?*]', '_', filename)

    def get_youtube_videos_from_url(self, url):
        self.log(f"Fetching video list from: {url}")
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'ignoreerrors': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    return [entry['url'] for entry in info['entries'] if entry]
                return []
        except Exception as e:
            self.log(f"Error fetching video list: {e}")
            return []
            
    def check_and_download_subs(self, url, output_dir, title):
        if self.ignore_subs:
            return False
        
        self.log(f"Checking for existing subtitles for '{title}'...")
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True, 'listsubtitles': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            video_lang = (info.get('language') or info.get('lang') or 'en').split('-')[0]
            target_langs = {video_lang}
            if self.sub_lang:
                target_langs.add(self.sub_lang)

            available_subs = info.get('subtitles', {})
            if not available_subs:
                self.log("No subtitles available.")
                return False

            best_sub_lang = None
            for lang in target_langs:
                if lang in available_subs:
                    for sub_info in available_subs[lang]:
                        if not sub_info.get('is_automatic'):
                            best_sub_lang = lang
                            break
                    if best_sub_lang: break
            
            if not best_sub_lang:
                self.log("No suitable human-made subtitles found.")
                return False

            self.log(f"Found human-made '{best_sub_lang}' subtitles. Downloading...")
            safe_title = self.clean_filename(title)
            sub_path_template = os.path.join(output_dir, f"{safe_title}.%(ext)s")
            
            ydl_opts_dl = {
                'quiet': True, 'no_warnings': True, 'writesubtitles': True,
                'subtitleslangs': [best_sub_lang], 'subtitlesformat': 'srt',
                'skip_download': True, 'outtmpl': sub_path_template,
            }
            with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl:
                ydl.download([url])

            expected_sub_file = os.path.join(output_dir, f"{safe_title}.{best_sub_lang}.srt")
            final_sub_file = os.path.join(output_dir, f"{safe_title}.srt")

            if os.path.exists(expected_sub_file):
                if os.path.exists(final_sub_file): os.remove(final_sub_file)
                os.rename(expected_sub_file, final_sub_file)
                self.log(f"Subtitle saved to {final_sub_file}")
                transcribe.make_files(final_sub_file, url=url)
                return True
            return False
        except Exception as e:
            self.log(f"Error checking subtitles: {e}")
            return False

    def download_audio(self, url, output_path):
        self.log(f"Downloading audio from {url}...")
        while True:
            try:
                ydl_opts = {
                    'format': 'bestaudio/best', 'outtmpl': output_path,
                    'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
                    'quiet': True, 'no_warnings': True
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                actual_file = os.path.splitext(output_path)[0] + ".mp3"
                if os.path.exists(actual_file): return actual_file
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

    def get_unique_id(self, source):
        if self.is_youtube(source):
            match = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', source)
            if match: return match.group(1)
        elif self.is_twitch(source):
             match = re.search(r'/videos/(\d+)', source)
             if match: return match.group(1)
        elif self.is_local_file(source):
            return os.path.basename(source)
        return source

    def is_processed(self, unique_id):
        if not os.path.exists(HISTORY_FILE): return False
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0] == unique_id and parts[1] == self.model_name:
                    return True
        return False

    def mark_as_processed(self, unique_id):
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{unique_id} {self.model_name}\n")

    def process_single_source(self, source):
        unique_id = self.get_unique_id(source)
        if not self.force and self.is_processed(unique_id):
            self.log(f"Skipping '{source}' - already processed with model '{self.model_name}'.")
            return
        
        job_id = add_job(source, self.model_name, "Initializing...")
        audio_file = None
        is_local = self.is_local_file(source)

        try:
            title, self.channel_name = self.get_video_info(source)
            if is_local: self.channel_name = "local_files"

            channel_dir = os.path.join(OUTPUT_DIR, self.clean_filename(self.channel_name))
            os.makedirs(channel_dir, exist_ok=True)
            update_job_status(job_id, "processing", new_title=title)
            
            if not is_local and self.check_and_download_subs(source, channel_dir, title):
                self.log(f"Downloaded existing subtitle for '{title}'. Skipping transcription.")
                self.mark_as_processed(unique_id)
                update_job_status(job_id, "skipped")
                return

            if is_local:
                audio_file = source
            else:
                safe_title = self.clean_filename(title)
                temp_audio_path = os.path.join(channel_dir, f"{safe_title}.%(ext)s")
                audio_file = self.download_audio(source, temp_audio_path)

            if not audio_file or not os.path.exists(audio_file):
                raise FileNotFoundError(f"Failed to obtain audio file for '{title}'.")

            update_job_status(job_id, "transcribing")
            self.log(f"Starting transcription for '{title}'")
            output_basename = self.clean_filename(os.path.splitext(os.path.basename(audio_file))[0])
            srt_file = os.path.join(channel_dir, f"{output_basename}.srt")
            
            success = transcribe.process_create(
                file=audio_file, model_name=self.model_name, srt_file=srt_file,
                language=None, device=self.device, compute_type=self.compute_type,
                force_device=False, auto=True, write=self.log
            )
            
            if success:
                self.log("Transcription successful.")
                update_job_status(job_id, "completed")
                self.mark_as_processed(unique_id)
            else:
                raise Exception("Transcription process failed.")
        except Exception as e:
            self.log(f"An error occurred for source '{source}': {e}")
            update_job_status(job_id, "failed")
        finally:
            if audio_file and not is_local and os.path.exists(audio_file):
                self.log(f"Removing temporary audio file: {audio_file}")
                try: os.remove(audio_file)
                except OSError as e: self.log(f"Error removing temp file: {e}")

    def process(self, source):
        twitch_username = self.is_twitch_channel(source)
        if twitch_username:
            self.log(f"Processing all VODs for Twitch channel: {twitch_username}")
            downloader = twitch_vod.StreamlinkVODDownloader()
            user_id = downloader.get_user_id_by_login(twitch_username)
            if not user_id:
                self.log(f"Could not find Twitch user: {twitch_username}"); return
            vods = downloader.get_all_vods(user_id)
            self.log(f"Found {len(vods)} VODs for {twitch_username}. Processing...")
            for vod in vods:
                self.process_single_source(f"https://www.twitch.tv/videos/{vod['id']}")
            return

        if self.is_channel_or_playlist_url(source):
            self.log(f"Processing YouTube channel/playlist: {source}")
            video_urls = self.get_youtube_videos_from_url(source)
            self.log(f"Found {len(video_urls)} videos. Processing...")
            for url in video_urls:
                self.process_single_source(url)
            return

        self.process_single_source(source)

def main():
    parser = argparse.ArgumentParser(
        description="Transcribe audio from YouTube, Twitch, other URLs, or local files.",
        usage="whisper_subs.py <model> [source] [options]"
    )
    parser.add_argument('model', nargs='?', help="Whisper model name (e.g., 'base'). Required unless using -l or -c.")
    parser.add_argument('source', nargs='?', help="URL or local file path. If empty, checks clipboard.")
    parser.add_argument('-l', '--list', action='store_true', help="List all transcription jobs and exit.")
    parser.add_argument('-c', '--continue', dest='continue_last', action='store_true', help="Continue the last unfinished job.")
    parser.add_argument('-g', '--gpu', action='store_true', help="Use GPU (CUDA) for transcription.")
    parser.add_argument('--device', default='cpu', help="Device to use ('cpu', 'cuda').")
    parser.add_argument('--compute', default='int8', help="Compute type (e.g., 'int8', 'float16').")
    parser.add_argument('-f', '--force', action='store_true', help="Force transcription even if already processed.")
    parser.add_argument('-i', '--ignore-subs', action='store_true', help="Ignore existing subtitles and transcribe anyway.")
    parser.add_argument('-lang', '--language', help="Language code (e.g., 'en', 'ja') for subtitle priority.")

    args = parser.parse_args()

    if args.list:
        list_jobs(); return

    source_to_process, model_to_use = args.source, args.model
    
    if args.continue_last:
        last_job = get_last_unfinished_job()
        if not last_job:
            print("No unfinished jobs to continue."); return
        print(f"Continuing job ID {last_job['id']}: {last_job['title']}")
        source_to_process, model_to_use = last_job['source'], last_job['model']
    
    if not model_to_use:
        parser.error("The 'model' argument is required unless using --list or --continue.")

    if not source_to_process:
        try:
            source_to_process = pyperclip.paste().strip()
            if not source_to_process:
                parser.error("No source provided and clipboard is empty.")
            print(f"Using source from clipboard: {source_to_process}")
        except Exception:
             parser.error("No source provided and could not read clipboard.")
    
    device = 'cuda' if args.gpu else args.device

    processor = WhisperSubs(
        model_name=model_to_use, device=device, compute_type=args.compute,
        force=args.force, ignore_subs=args.ignore_subs, sub_lang=args.language
    )
    processor.process(source_to_process)

if __name__ == "__main__":
    main()