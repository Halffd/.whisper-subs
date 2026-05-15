#!/usr/bin/env python3
"""
WhisperSubs - Automated Video Transcription Tool

Transcribes audio from YouTube, Twitch, and local files using Whisper AI.
"""
import os
import sys
import json
import argparse
import datetime
import re
import subprocess
import time
import shutil
import threading
import glob
import pyperclip
import yt_dlp
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any, Tuple, Union

# Lazy imports - only import when needed
_transcribe_module = None
_twitch_vod_module = None
_model_module = None
_livestream_transcriber_module = None

def _get_transcribe():
    """Lazy import for transcribe module"""
    global _transcribe_module
    if _transcribe_module is None:
        import transcribe as _transcribe_module
    return _transcribe_module

def _get_twitch_vod():
    """Lazy import for twitch_vod module"""
    global _twitch_vod_module
    if _twitch_vod_module is None:
        import twitch_vod as _twitch_vod_module
    return _twitch_vod_module

def _get_model():
    """Lazy import for model module"""
    global _model_module
    if _model_module is None:
        import model as _model_module
    return _model_module

def _get_livestream_transcriber():
    """Lazy import for livestream_transcriber module"""
    global _livestream_transcriber_module
    if _livestream_transcriber_module is None:
        import livestream_transcriber as _livestream_transcriber_module
    return _livestream_transcriber_module

# --- Configuration ---
APP_NAME = "WhisperSubs"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs")
JOBS_FILE = os.path.join(CONFIG_DIR, "jobs.json")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "history.txt")
PROCESS_FILE = os.path.join(OUTPUT_DIR, "process.txt")
# Ensure config directories exist
os.makedirs(CONFIG_DIR, exist_ok=True)
# Ensure OUTPUT_DIR exists (handle case where parent might be a file)
try:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
except (FileNotFoundError, FileExistsError):
    # If OUTPUT_DIR can't be created, use fallback
    OUTPUT_DIR = os.path.join(os.getcwd(), "Youtube-Subs")
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
    def __init__(
        self,
        model_name: str = 'large',
        device: str = 'cpu',
        compute_type: str = 'int8',
        force: bool = False,
        ignore_subs: bool = False,
        sub_lang: Optional[str] = None,
        run_mpv: bool = False,
        browser: str = "chrome",
        strict_language_tier: bool = False,
        force_retry: bool = False,
        vad_filter: Optional[bool] = None,
        vad_min_silence_duration: Optional[int] = None,
        diarization: bool = False,
        min_speakers: int = 1,
        max_speakers: int = 2,
        temperature: Optional[float] = None,
        merge_lines: bool = False,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        mpv_ipc: bool = False,
        mpv_socket: Optional[str] = None,
        cpu_threads: Optional[int] = None,
        save_video: bool = False,
        save_thumbnail: bool = True
    ):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.force = force
        self.force_retry = force_retry
        self.ignore_subs = ignore_subs
        self.sub_lang = sub_lang
        self.run_mpv = run_mpv
        self.specified_browser = browser
        self.force_cookies = True if browser else False
        self.strict_language_tier = strict_language_tier
        self.save_video = save_video
        self.save_thumbnail = save_thumbnail
        self.model = None
        self.log_file = os.path.join(os.path.expanduser("~/.config/WhisperSubs"), 'whisper_subs.log')
        self.info_cache: Dict[str, Tuple[str, str]] = {}  # Cache for video info to avoid re-fetching
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        self.delay = 30
        self.start_delay = 30

        # Threading primitives for synchronization
        self._lock: threading.Lock = threading.Lock()
        self._stop_event: threading.Event = threading.Event()
        self._process_lock: threading.Lock = threading.Lock()

        # VAD settings (disabled by default)
        self.vad_filter = vad_filter
        self.vad_min_silence_duration = vad_min_silence_duration
        # Diarization settings
        self.diarization = diarization
        self.min_speakers = min_speakers
        self.max_speakers = max_speakers
        # Transcription settings
        self.temperature = temperature
        self.merge_lines = merge_lines
        # Time range settings
        self.start_time = start_time
        self.end_time = end_time
        # MPV IPC settings
        self.mpv_ipc = mpv_ipc
        self.mpv_socket = mpv_socket or '/tmp/mpvsocket'
        # CPU threads setting
        self.cpu_threads = cpu_threads

    def _get_ytdlp_base_opts(self, **extra_opts) -> Dict[str, Any]:
        """Get base yt-dlp options with cookies from browser (required for YouTube)."""
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 10,
            'no_check_certificate': True,
        }
        # Always include cookies from browser for YouTube (now required)
        if self.specified_browser:
            base_opts['cookiesfrombrowser'] = (self.specified_browser,)
        base_opts.update(extra_opts)
        return base_opts

    def log(self, message: str) -> None:
        message_str = str(message)
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {message_str}")
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{timestamp}] {message_str}\n")

    def is_youtube(self, url: str) -> bool:
        return bool(url and 'youtu' in urlparse(url).netloc)

    def is_twitch(self, url: str) -> bool:
        return bool(url and 'twitch.tv' in urlparse(url).netloc)

    def is_local_file(self, path: str) -> bool:
        return bool(path and os.path.exists(path))

    def is_local_dir(self, path: str) -> bool:
        return bool(path and os.path.isdir(path))

    def _safe_model_filename(self) -> str:
        """Return model name sanitized for use in filenames (colons -> underscores)."""
        return self.model_name.replace(':', '_')

    def _strip_model_from_filename(self, filename: str) -> str:
        """Strip any existing model name from filename to prevent duplicate model suffixes."""
        import model
        title = filename
        for model_name in _get_model().ALL_MODEL_NAMES:
            safe_name = model_name.replace(':', '_')
            title = re.sub(rf'\.{re.escape(safe_name)}(?=\.\w+$|$)', '', title)
            title = re.sub(rf'\.{re.escape(model_name)}(?=\.\w+$|$)', '', title)
        return title

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

    def get_video_info(self, url: str) -> Tuple[str, str]:
        """Get video title and channel name."""
        # For local files, just return the filename
        if self.is_local_file(url):
            return os.path.basename(url), "local_files"
        
        # For YouTube/Twitch, fetch info
        try:
            ydl_opts = self._get_ytdlp_base_opts(skip_download=True)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                return "unknown_title", "unknown_channel"

            title = info.get("title", "unknown_title")
            channel = info.get("channel") or info.get("uploader") or "unknown_channel"
            return title, channel

        except Exception:
            return os.path.basename(url), "unknown_channel"

    def get_video_info_cached(self, url):
        """Get video info with caching to avoid re-fetching the same URL."""
        # Clean URL first for consistent cache keys
        clean_url = self.clean_youtube_url(url) if self.is_youtube(url) else url

        if clean_url in self.info_cache:
            self.log(f"Using cached info for {clean_url[:50]}...")
            return self.info_cache[clean_url]

        info = self.get_video_info(clean_url)
        self.info_cache[clean_url] = info
        return info

    def clean_youtube_url(self, url: str) -> str:
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

    def resolve_source_to_tasks_lazy(self, source):
        """Lazy resolution with parallel metadata fetching for playlists."""
        self.log(f"Resolving source (lazy): {source}")

        # Clean YouTube URLs for consistent processing
        if self.is_youtube(source):
            clean_source = self.clean_youtube_url(source)
            if clean_source != source:
                self.log(f"Cleaned URL: {clean_source}")
                source = clean_source

        if isinstance(source, list):
            self.log(f"Source is a list of {len(source)} items.")
            for item in source:
                if not item.strip():
                    continue
                try:
                    if self.is_youtube(item) or self.is_twitch(item):
                        title, _ = self.get_video_info_cached(item)
                    else:
                        title = os.path.basename(item)
                    if self.is_youtube(item):
                        title = self.clean_filename(title)
                    yield {"source": item, "status": "pending", "title": title}
                except Exception as e:
                    self.log(f"Error processing {item}: {e}")
                    yield {"source": item, "status": "pending", "title": os.path.basename(item)}

        elif self.is_local_dir(source):
            self.log(f"Source is a local directory: {source}")
            for root, _, files in os.walk(source):
                for file in files:
                    if file.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.ogg', '.mkv')):
                        file_path = os.path.join(root, file)
                        yield {
                            "source": file_path,
                            "status": "pending",
                            "title": os.path.splitext(file)[0]
                        }

        elif self.is_channel_or_playlist_url(source):
            self.log("Source is YouTube channel/playlist (flat extract).")
            
            # Load history for filtering
            processed_count = 0
            skipped_count = 0

            ydl_opts = self._get_ytdlp_base_opts(extract_flat=True, skip_download=True)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source, download=False)

            if not info or "entries" not in info:
                return

            urls = [
                entry.get("url")
                for entry in info["entries"]
                if entry and entry.get("url")
            ]
            
            self.log(f"Found {len(urls)} videos in channel/playlist")

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(self.get_video_info_cached, url): url
                    for url in urls
                }

                for future in as_completed(futures):
                    url = futures[future]
                    try:
                        # Skip already processed videos
                        if self.is_already_processed(url):
                            processed_count += 1
                            self.log(f"Skipping already processed: {url}")
                            continue
                        
                        title, _ = future.result()
                        skipped_count += 1
                        yield {
                            "source": url,
                            "status": "pending",
                            "title": self.clean_filename(title),
                        }
                    except Exception:
                        # Still try to process even if we can't get title
                        if not self.is_already_processed(url):
                            yield {
                                "source": url,
                                "status": "pending",
                                "title": os.path.basename(url),
                            }
            
            if processed_count > 0:
                self.log(f"Skipped {processed_count} already processed videos, processing {skipped_count} new ones")
        # Check for Twitch channel videos page specifically
        elif self.is_twitch(source) and '/videos' in source and '/videos/' not in source:
            # This is a Twitch channel videos page (e.g., twitch.tv/channel/videos)
            self.log(f"Detected Twitch channel VOD page: {source}")

            # Extract channel name from URL
            import re
            channel_match = re.search(r'twitch\.tv/([^/]+)/videos', source)
            if channel_match:
                channel_name = channel_match.group(1)
                self.log(f"Fetching all VODs for channel: {channel_name}")

                try:
                    downloader = _get_twitch_vod().StreamlinkVODDownloader()
                    user_id = downloader.get_user_id_by_login(channel_name)

                    if not user_id:
                        self.log(f"Could not find Twitch user: {channel_name}")
                        # Fallback to single source if API fails
                        title, _ = self.get_video_info_cached(source)
                        title = self.clean_filename(title)
                        yield {"source": source, "status": "pending", "title": title}
                        return

                    vods = downloader.get_all_vods(user_id)
                    self.log(f"Found {len(vods)} VODs")
                    
                    # Filter already processed VODs
                    processed_count = 0
                    skipped_count = 0

                    # Yield each VOD as a task
                    for vod in vods:
                        vod_url = f"https://www.twitch.tv/videos/{vod['id']}"
                        
                        # Skip already processed VODs
                        if self.is_already_processed(vod_url):
                            processed_count += 1
                            self.log(f"Skipping already processed VOD: {vod_url}")
                            continue
                        
                        skipped_count += 1
                        title = self.clean_filename(vod['title'])
                        yield {"source": vod_url, "status": "pending", "title": title}
                    
                    if processed_count > 0:
                        self.log(f"Skipped {processed_count} already processed VODs, processing {skipped_count} new ones")

                    return  # Early exit after yielding all VODs

                except Exception as e:
                    self.log(f"Error fetching Twitch VODs: {e}")
                    # Fallback to single source if API fails
                    title, _ = self.get_video_info_cached(source)
                    title = self.clean_filename(title)
                    yield {"source": source, "status": "pending", "title": title}
                    return

        else:
            self.log("Source is a single URL or file.")
            try:
                if self.is_youtube(source) or self.is_twitch(source):
                    title, _ = self.get_video_info_cached(source)
                else:
                    title = os.path.basename(source)
                if self.is_youtube(source):
                    title = self.clean_filename(title)
                yield {"source": source, "status": "pending", "title": title}
            except Exception as e:
                self.log(f"Error getting video info: {e}")
                yield {"source": source, "status": "pending", "title": os.path.basename(source)}

    def _convert_to_audio(self, video_path: str) -> Optional[str]:
        """Convert video file to audio-only M4A for transcription.

        This is needed for time cutting (--start/--end) to work properly,
        as cutting video files requires video encoding which may fail.
        """
        if not os.path.exists(video_path):
            return None

        video_exts = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm'}
        if os.path.splitext(video_path)[1].lower() not in video_exts:
            return video_path

        audio_path = os.path.splitext(video_path)[0] + ".m4a"

        if os.path.exists(audio_path):
            self.log(f"Using existing audio file: {os.path.basename(audio_path)}")
            return audio_path

        try:
            import audio_cache
            cached = audio_cache.get(video_path)
            if cached and os.path.exists(cached):
                import shutil
                shutil.copy2(cached, audio_path)
                self.log(f"Using cached conversion: {os.path.basename(audio_path)}")
                return audio_path
        except Exception:
            pass

        self.log(f"Extracting audio from {os.path.basename(video_path)}...")

        import subprocess
        ffmpeg_cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-vn',
            '-acodec', 'aac',
            '-b:a', '128k',
            '-ac', '1',
            '-ar', '16000',
            audio_path
        ]

        result = subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False
        )

        if result.returncode == 0 and os.path.exists(audio_path):
            self.log(f"Audio extracted: {os.path.basename(audio_path)}")
            try:
                import audio_cache
                audio_cache.put(video_path, audio_path)
                audio_path = audio_cache.get(video_path) or audio_path
            except Exception:
                pass
            return audio_path
        else:
            self.log(f"Audio extraction failed, using original file")
            return video_path
        
    def check_and_download_subs(self, url, output_dir, title):
        """Check for subs with minimal overhead."""
        if self.ignore_subs:
            return False

        self.log("Checking for existing subtitles...")

        try:
            # Ultra-minimal options for just checking subs
            ydl_opts = self._get_ytdlp_base_opts(
                skip_download=True,
                writesubtitles=False,
                listsubtitles=False,
            )

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if info is None:
                return False

            # Quick check for human-made subs
            subtitles = info.get('subtitles', {})
            if not subtitles:
                self.log("No subtitles available.")
                return False

            video_lang = (info.get('language') or 'en').split('-')[0]
            target_langs = {video_lang, self.sub_lang} if self.sub_lang else {video_lang}

            best_sub_lang = None
            for lang in target_langs:
                lang_subs = subtitles.get(lang, [])
                if any(not s.get('is_automatic') for s in lang_subs):
                    best_sub_lang = lang
                    break

            if not best_sub_lang:
                self.log("No human-made subtitles found.")
                return False

            self.log(f"Found '{best_sub_lang}' subs. Downloading...")

            # Now actually download with minimal overhead
            timestamp = info.get('timestamp', '')
            if timestamp:
                date_time = datetime.datetime.fromtimestamp(timestamp)
                timeday = date_time.strftime('%Y-%m-%d_%H-%M')
            else:
                timeday = ''

            safe_title = f"{timeday}_{self.clean_filename(title)}" if timeday else self.clean_filename(title)
            sub_template = os.path.join(output_dir, f"{safe_title}.%(ext)s")

            ydl_opts_dl = self._get_ytdlp_base_opts(
                skip_download=True,
                writesubtitles=True,
                subtitleslangs=[best_sub_lang],
                subtitlesformat='srt',
                outtmpl=sub_template,
            )

            with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl:
                ydl.download([url])

            expected_file = os.path.join(output_dir, f"{safe_title}.{best_sub_lang}.srt")
            final_file = os.path.join(output_dir, f"{safe_title}.srt")

            if os.path.exists(expected_file):
                if os.path.exists(final_file):
                    os.remove(final_file)
                os.rename(expected_file, final_file)
                self.log(f"Subtitle saved to {final_file}")
                _get_transcribe().make_files(final_file, url=url)
                return True

        except Exception as e:
            self.log(f"Subtitle check failed: {e}")

        return False

    def download_audio(self, url: str, output_path: str) -> Optional[str]:
        """Download audio and return the actual file path."""
        self.log(f"Downloading audio from {url}...")

        expected_base = None
        os.makedirs(output_path, exist_ok=True)

        # Clean the URL first
        clean_url = self.clean_youtube_url(url) if self.is_youtube(url) else url

        # Special handling for Twitch VODs (individual videos) using twitch_vod module
        if self.is_twitch(url) and '/videos/' in url:
            self.log(f"Detected Twitch VOD: {url}, using twitch_vod module")

            # Extract VOD ID from URL
            import re
            vod_match = re.search(r'twitch\.tv/videos/(\d+)', url)
            if vod_match:
                vod_id = vod_match.group(1)
                self.log(f"Extracted VOD ID: {vod_id}")

                try:
                    downloader = _get_twitch_vod().StreamlinkVODDownloader()
                    # Get VOD info for the title
                    vod_info = downloader.get_vod_info(vod_id)
                    if not vod_info:
                        self.log(f"Could not get info for VOD ID: {vod_id}")
                        # Fall back to yt-dlp
                        pass
                    else:
                        title = vod_info.get('title', f'vod_{vod_id}')
                        # Use the twitch_vod module to download the VOD audio
                        output_file = downloader.download_vod_audio(vod_id, title, vod_info.get('duration', 0))
                        if output_file and os.path.exists(output_file):
                            self.log(f"Successfully downloaded Twitch VOD: {output_file}")
                            return output_file
                        else:
                            self.log(f"Twitch VOD download failed for ID: {vod_id}")
                            # Fall back to yt-dlp
                            pass
                except Exception as e:
                    self.log(f"Error downloading Twitch VOD with twitch_vod module: {e}")
                    # Fall back to yt-dlp
                    pass  # Continue with regular yt-dlp flow below

        # === STEP 1: Check for existing files (fast) ===
        if not self.force:
            try:
                ydl_opts = self._get_ytdlp_base_opts(
                    skip_download=True,
                    socket_timeout=5,
                )

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(clean_url, download=False)

                    if info:
                        timestamp = info.get('timestamp', '')
                        if timestamp:
                            date_time = datetime.datetime.fromtimestamp(timestamp)
                            timeday = date_time.strftime('%Y-%m-%d_%H-%M')
                        else:
                            timeday = ''

                        clean_title = self.clean_filename(info.get('title', 'unknown'))
                        # Strip any existing model suffix to avoid duplicate model names
                        title_without_model = self._strip_model_from_filename(clean_title)
                        base_title = f"{timeday}_{title_without_model}" if timeday else title_without_model

                        # Check for existing files with current model name only
                        for ext in ['.mp3', '.m4a', '.webm', '.ogg']:
                            pattern = f"{base_title}.{self._safe_model_filename()}{ext}"
                            existing_file = os.path.join(output_path, pattern)
                            if os.path.exists(existing_file):
                                self.log(f"File already exists: {existing_file}")
                                return existing_file
            except Exception as e:
                self.log(f"Quick check failed: {e}")

        # === STEP 1.5: Check audio cache ===
        if not self.force:
            try:
                import audio_cache
                cached = audio_cache.get(clean_url)
                if cached and os.path.exists(cached):
                    self.log(f"Using cached audio: {cached}")
                    dest = os.path.join(output_path, os.path.basename(cached))
                    if dest != cached and not os.path.exists(dest):
                        import shutil
                        shutil.copy2(cached, dest)
                        return dest
                    return cached
            except Exception as e:
                self.log(f"Cache lookup failed: {e}")

        # === STEP 2: Download the file ===
        original_cwd = os.getcwd()
        os.chdir(output_path)

        # Define progress hook once outside the loop
        def progress_hook(d):
            """Show clean progress updates."""
            if d['status'] == 'downloading':
                if 'total_bytes' in d or 'total_bytes_estimate' in d:
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)

                    if total > 0:
                        percent = (downloaded / total) * 100
                        last_percent = getattr(progress_hook, 'last_percent', -1)

                        # Show at 10%, 20%, 30%... milestones
                        if int(percent) % 10 == 0 and int(percent) != last_percent:
                            speed = d.get('speed', 0)
                            speed_mb = speed / (1024 * 1024) if speed else 0
                            self.log(f"Download: {int(percent)}% ({speed_mb:.1f} MB/s)")
                            progress_hook.last_percent = int(percent)

            elif d['status'] == 'finished':
                filename = os.path.basename(d.get('filename', 'unknown'))
                self.log(f"Download complete: {filename}")

        progress_hook.last_percent = -1

        try:
            attempt = 0
            max_attempts = 3
            fallback_format = None

            while attempt < max_attempts:
                attempt += 1

                try:
                    # Get video info once
                    info_opts = self._get_ytdlp_base_opts(skip_download=True)

                    with yt_dlp.YoutubeDL(info_opts) as ydl:
                        info = ydl.extract_info(clean_url, download=False)

                    if info is None:
                        self.log(f"Failed to get video info for {clean_url}")
                        return None

                    # Build filename
                    timestamp = info.get('timestamp', '')
                    if timestamp:
                        date_time = datetime.datetime.fromtimestamp(timestamp)
                        timeday = date_time.strftime('%Y-%m-%d_%H-%M')
                    else:
                        timeday = ''

                    clean_title = self.clean_filename(info.get('title', 'unknown'))
                    # Strip any existing model suffix to avoid duplicate model names
                    title_without_model = self._strip_model_from_filename(clean_title)
                    expected_base = f"{timeday}_{title_without_model}.{self._safe_model_filename()}" if timeday else f"{title_without_model}.{self._safe_model_filename()}"

                    # Download with proper template
                    download_opts = self._get_ytdlp_base_opts(
                        outtmpl=f'{expected_base}.%(ext)s',
                        noplaylist=True,
                        writethumbnail=self.save_thumbnail,
                        noprogress=False,
                        retries=5,
                        continuedl=True,
                        progress_hooks=[progress_hook],
                        ignoreerrors=False,
                        socket_timeout=30,
                        extractor_retries=3,
                        fragment_retries=3,
                        extractor_args={
                            'youtube': {
                                'player_client': ['android', 'web']
                            }
                        },
                        http_chunk_size=10485760,
                        concurrent_fragment_downloads=5,
                    )

                    if fallback_format:
                        download_opts['format'] = fallback_format
                    elif not self.save_video:
                        download_opts.update({
                            'format': 'bestaudio[ext=m4a]/bestaudio/best',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'm4a',
                                'preferredquality': '192',
                            }]
                        })
                    else:
                        download_opts.update({
                            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                            'merge_output_format': 'mp4',
                        })

                    self.log(f"Starting download (attempt {attempt}/{max_attempts})...")
                    with yt_dlp.YoutubeDL(download_opts) as ydl:
                        ydl.download([clean_url])

                    # Find the downloaded file based on expected name
                    for ext in ['.m4a', '.mp4', '.mp3', '.webm', '.ogg']:
                        predicted_path = f"{expected_base}{ext}"
                        full_path = os.path.join(output_path, predicted_path)
                        if os.path.exists(full_path):
                            self.log(f"Successfully downloaded: {full_path}")
                            return full_path

                    self.log(f"Download completed but expected file not found: {expected_base}")
                    return None

                except Exception as e:
                    error_str = str(e).lower()

                    if ('rate' in error_str or 'unavailable' in error_str or '429' in error_str) and attempt < max_attempts:
                        delay = min(30 * (2 ** attempt), 3600)
                        self.log(f"Rate limited. Retrying in {delay}s... (attempt {attempt}/{max_attempts})")
                        time.sleep(delay)
                        continue
                    elif ('requested format is not available' in error_str or 'format not available' in error_str) and attempt < max_attempts:
                        self.log(f"Format not available. Trying fallback format... (attempt {attempt}/{max_attempts})")
                        if attempt == 1:
                            fallback_format = 'bestaudio[ext=m4a]/bestaudio/best'
                        elif attempt == 2:
                            fallback_format = 'bestaudio/best'
                        else:
                            fallback_format = 'best'
                        continue
                    else:
                        self.log(f"Download failed: {e}")
                        return None

        finally:
            os.chdir(original_cwd)
            # Clean up leftover .part files from interrupted/failed downloads
            if expected_base:
                for part_file in glob.glob(os.path.join(output_path, f"{expected_base}*.part")):
                    try:
                        os.remove(part_file)
                        self.log(f"Cleaned up partial download: {os.path.basename(part_file)}")
                    except OSError:
                        pass
                # Clean up thumbnails unless saving video
                if not self.save_video:
                    for thumb_ext in ['.webp', '.jpg', '.jpeg', '.png']:
                        thumb_path = os.path.join(output_path, f"{expected_base}{thumb_ext}")
                        if os.path.exists(thumb_path):
                            try:
                                os.remove(thumb_path)
                            except OSError:
                                pass
    def get_unique_id(self, source):
        """Extract a unique identifier from various source types.

        For YouTube: Just the video ID (11 characters)
        For Twitch: Just the VOD number
        For local files: MD5 hash of file content (first 1MB for speed)
        """
        if not source:
            return str(source)

        # Clean the source first (especially important for YouTube URLs)
        clean_source = self.clean_youtube_url(source) if self.is_youtube(source) else source

        # Handle YouTube URLs
        if self.is_youtube(clean_source):
            # Try to extract from youtu.be/ID format first
            if 'youtu.be/' in clean_source:
                video_id = clean_source.split('youtu.be/')[-1].split('?')[0].split('&')[0].split('#')[0]
                if len(video_id) == 11:  # Validate it's a proper YouTube ID
                    return video_id

            # Try to extract from youtube.com/watch?v=ID format
            if 'youtube.com/watch' in clean_source:
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(clean_source)
                if 'v' in parse_qs(parsed.query):
                    video_id = parse_qs(parsed.query)['v'][0].split('&')[0]
                    if len(video_id) == 11:  # Validate it's a proper YouTube ID
                        return video_id

            # Try to extract from youtube.com/embed/ID format
            if 'youtube.com/embed/' in clean_source:
                parts = clean_source.split('youtube.com/embed/')[-1].split('/')
                if parts and len(parts[0]) == 11:
                    return parts[0]

        # Handle Twitch VODs
        if self.is_twitch(clean_source):
            match = re.search(r'(?:videos?|clip)/(\d+)', clean_source)
            if match:
                return f"twitch_{match.group(1)}"

        # Handle local files - use file hash for reliable tracking
        if self.is_local_file(clean_source):
            return self._get_file_hash(clean_source)

        # Fallback: use a hash of the source string
        return f"hash_{hash(clean_source) & 0xffffffff}"
    
    def _get_file_hash(self, file_path: str) -> str:
        """Generate MD5 hash of file content (first 1MB for speed)."""
        import hashlib
        
        if not os.path.exists(file_path):
            return f"file_{os.path.basename(file_path)}"
        
        try:
            md5 = hashlib.md5()
            # Read first 1MB for speed - enough to detect same file
            with open(file_path, 'rb') as f:
                chunk = f.read(1024 * 1024)  # 1MB
                md5.update(chunk)
            return f"file_{md5.hexdigest()[:16]}"  # Use first 16 chars of hash
        except Exception as e:
            self.log(f"Warning: Could not hash file {file_path}: {e}")
            # Fallback to basename if hashing fails
            return f"file_{os.path.basename(file_path)}"


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
        current_model_index = _get_model().getIndex(self.model_name)
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

                history_model_index = _get_model().getIndex(history_model)
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
    
    def is_already_processed(self, url: str) -> bool:
        """Check if a URL has already been processed by checking history file."""
        if not os.path.exists(HISTORY_FILE):
            return False
        
        # Clean URL for consistent comparison
        clean_url = self.clean_youtube_url(url) if self.is_youtube(url) else url
        
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = set(line.strip().split()[0] for line in f if line.strip())
            
            # Check both original and cleaned URL
            return url in history or clean_url in history
        except Exception:
            return False
    
    def process_task(self, job_id, task):
        task_source = task['source']
        unique_id = self.get_unique_id(task_source)
        if not self.force_retry and self.is_processed(unique_id):
            self.log(f"Skipping task '{task_source}' - already processed.")
            update_task_status(job_id, task_source, 'skipped', task['title'])
            return

        audio_file, is_local = None, self.is_local_file(task_source)
        try:
            title, self.channel_name = self.get_video_info(task_source)
            if is_local:
                self.channel_name = "local_files"
            update_task_status(job_id, task_source, 'processing', title)
            self.model_name = _get_model().getName(self.model_name)
            channel_dir = os.path.join(OUTPUT_DIR, self.clean_filename(self.channel_name))
            os.makedirs(channel_dir, exist_ok=True)

            if not is_local and self.check_and_download_subs(task_source, channel_dir, title) and not self.force:
                self.log(f"Downloaded existing subtitle for '{title}'.")
                self.mark_as_processed(unique_id)
                update_task_status(job_id, task_source, 'skipped')
                return

            # FIX: Just pass the directory, not a template path
            if is_local:
                # Convert video to audio if needed (for time cutting to work properly)
                audio_file = self._convert_to_audio(task_source)
                if not audio_file:
                    self.log(f"Failed to convert video to audio: {task_source}")
                    return
            else:
                audio_file = self.download_audio(task_source, channel_dir)
            
            if not audio_file or not os.path.exists(audio_file):
                self.log(f"Audio file not found: {audio_file}")
                return

            update_task_status(job_id, task_source, 'transcribing')
            # Get base filename without extension and ensure it includes the model name
            base_name = os.path.splitext(os.path.basename(audio_file))[0]
            safe_model = self._safe_model_filename()
            if not base_name.endswith(f".{safe_model}"):
                base_name = f"{base_name}.{safe_model}"

            # Write to both locations: video folder AND Documents/Youtube-Subs/local_files
            if is_local:
                # Primary: video file's folder
                srt_file = os.path.join(os.path.dirname(audio_file), f"{base_name}.srt")
                # Secondary: Documents/Youtube-Subs/local_files
                local_files_dir = os.path.join(OUTPUT_DIR, "local_files")
                os.makedirs(local_files_dir, exist_ok=True)
                srt_file_secondary = os.path.join(local_files_dir, f"{base_name}.srt")
                
                # Check for existing unfinished transcription to resume
                unfinished_srt = srt_file.replace('.srt', '.unfinished.srt')
                if os.path.exists(unfinished_srt) and os.path.getsize(unfinished_srt) > 10:
                    self.log(f"Found unfinished transcription: {unfinished_srt}")
                    self.log("Will resume from where it left off...")
            else:
                channel_dir = os.path.join(OUTPUT_DIR, self.clean_filename(self.channel_name))
                os.makedirs(channel_dir, exist_ok=True)
                srt_file = os.path.join(channel_dir, f"{base_name}.srt")
                srt_file_secondary = None

            # Create helper files (bash, bat, thumbnail) before transcription
            _get_transcribe().make_files(srt_file.replace('.srt', '.unfinished.srt'), url=task_source)

            # Launch mpv FIRST if --run option is specified (before transcription starts)
            mpv_process = None
            if hasattr(self, 'run_mpv') and self.run_mpv:
                mpv_process = self.launch_mpv(audio_file if is_local else task_source, srt_file, task_source)
                # Wait a moment for mpv to start
                time.sleep(1)

            # Start auto-reload thread if mpv_ipc is enabled
            reload_stop_event = threading.Event()
            reload_thread = None
            if hasattr(self, 'mpv_ipc') and self.mpv_ipc and mpv_process:
                reload_thread = self.start_mpv_auto_reload(srt_file, reload_stop_event)

            # Build VAD parameters if enabled
            vad_params = None
            if hasattr(self, 'vad_filter') and self.vad_filter:
                vad_params = dict(min_silence_duration_ms=self.vad_min_silence_duration) if self.vad_min_silence_duration else None

            # Build diarization parameters if enabled
            diarization_params = None
            if hasattr(self, 'diarization') and self.diarization:
                diarization_params = dict(min_speakers=self.min_speakers, max_speakers=self.max_speakers)

            if _get_transcribe().process_create(
                file=audio_file,
                model_name=self.model_name,
                srt_file=srt_file,
                device=self.device,
                compute_type=self.compute_type,
                force_device=False,
                auto=True,
                write=self.log,
                cpu_threads=getattr(self, 'cpu_threads', None),
                vad_filter=self.vad_filter if hasattr(self, 'vad_filter') else False,
                vad_params=vad_params,
                diarization=self.diarization if hasattr(self, 'diarization') else False,
                diarization_params=diarization_params,
                temperature=self.temperature if hasattr(self, 'temperature') else None,
                merge_lines=self.merge_lines if hasattr(self, 'merge_lines') else False,
                start_time=getattr(self, 'start_time', None),
                end_time=getattr(self, 'end_time', None)
            ):
                self.log("Transcription successful.")
                # Update the SRT filename in case it was changed during processing
                if os.path.exists(srt_file):
                    base_name = os.path.splitext(srt_file)[0]
                    new_srt_file = f"{base_name}.srt"
                    if new_srt_file != srt_file and os.path.exists(new_srt_file):
                        srt_file = new_srt_file
                _get_transcribe().make_files(srt_file, url=task_source)

                # Copy to secondary location if applicable
                if srt_file_secondary and os.path.exists(srt_file):
                    try:
                        import shutil
                        shutil.copy2(srt_file, srt_file_secondary)
                        self.log(f"Copied subtitle to: {srt_file_secondary}")
                    except Exception as copy_err:
                        self.log(f"Warning: Could not copy to secondary location: {copy_err}")

                # Stop auto-reload thread
                if reload_thread:
                    reload_stop_event.set()
                    reload_thread.join(timeout=2)

                # Final subtitle reload
                if hasattr(self, 'mpv_ipc') and self.mpv_ipc and mpv_process:
                    self.mpv_reload_subtitles(srt_file)

                update_task_status(job_id, task_source, 'completed')
                self.mark_as_processed(unique_id)
            else:
                raise Exception("Transcription process failed.")

        except Exception as e:
            self.log(f"Error on task '{task_source}': {e}")
            update_task_status(job_id, task_source, 'failed')

        finally:
            if audio_file and not is_local and os.path.exists(audio_file):
                if not self.save_video:
                    try:
                        import audio_cache
                        cached_path = audio_cache.put(task_source, audio_file)
                        if cached_path:
                            self.log(f"Cached audio: {cached_path}")
                        else:
                            os.remove(audio_file)
                            self.log(f"Removed temp audio (cache failed): {audio_file}")
                    except OSError as e:
                        self.log(f"Error handling temp file: {e}")
                else:
                    self.log(f"Keeping media file: {audio_file}")

    def launch_mpv(self, audio_file, srt_file, task_source):
        """Launch mpv with the audio file, subtitles, and --pause flag."""
        import subprocess
        try:
            # Determine the media source to use - prefer the original source if it's a URL
            # If it's a local file, use the audio file directly
            is_local = self.is_local_file(task_source)
            media_source = audio_file if is_local else task_source

            # Create the mpv command with --pause and input-ipc-server
            mpv_socket = self.mpv_socket if self.mpv_socket else '/tmp/mpvsocket'
            cmd = [
                'mpv',
                media_source,
                '--pause',
                f'--input-ipc-server={mpv_socket}',
                f'--sub-file={srt_file}'
            ]

            self.log(f"Launching mpv: {' '.join(cmd)}")

            # Run mpv in the background
            process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log("mpv launched in background with --pause and mpvsocket")

            return process

        except Exception as e:
            self.log(f"Error launching mpv: {e}")
            return None

    def start_mpv_auto_reload(self, srt_file, stop_event):
        """Start background thread to auto-reload subtitles every minute."""
        def auto_reload_worker():
            reload_count = 0
            while not stop_event.is_set():
                # Wait 60 seconds or until stop event
                if stop_event.wait(timeout=60):
                    break

                # Reload subtitles
                reload_count += 1
                if self.mpv_reload_subtitles(srt_file):
                    self.log(f"Auto-reloaded subtitles (#{reload_count})")
                else:
                    self.log(f"Auto-reload failed (#{reload_count}) - mpv may not be running")

        thread = threading.Thread(target=auto_reload_worker, daemon=True)
        thread.start()
        self.log("Started MPV auto-reload thread (60s interval)")
        return thread

    def mpv_reload_subtitles(self, srt_file):
        """Send IPC command to MPV to reload subtitle file."""
        if not self.mpv_ipc:
            return False

        try:
            import socket
            import json

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.mpv_socket)

            # Command to reload subtitle file
            command = {
                "command": ["sub-reload"]
            }
            sock.sendall(json.dumps(command).encode() + b'\n')

            # Read response
            response = sock.recv(4096).decode()
            sock.close()

            self.log(f"MPV IPC response: {response.strip()}")
            return True

        except FileNotFoundError:
            self.log("MPV socket not found - is MPV running with IPC?")
            return False
        except Exception as e:
            self.log(f"Error sending MPV IPC command: {e}")
            return False

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

    def process(self, job_or_source: Union[Dict[str, Any], str]) -> None:
        """Main processing entry point."""
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
    """
    Read sources from a file, one per line, with optional model specifications.

    Format:
    <url> [model_name_or_index]

    Example:
    https://www.youtube.com/watch?v=example1 large-v3
    https://www.youtube.com/watch?v=example2 10
    https://www.youtube.com/watch?v=example3
    """
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            sources = []
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # Split on whitespace, but keep URLs with spaces together
                parts = line.split()
                if not parts:
                    continue

                # The first part is the URL, the rest is optional model name
                url = parts[0]
                model = parts[1] if len(parts) > 1 else None

                # Basic URL validation
                if not (url.startswith('http') or url.startswith('www.')):
                    print(f"Warning: Line {i} doesn't appear to be a valid URL: {url}", file=sys.stderr)
                    continue

                sources.append({
                    'url': url,
                    'model': model
                })

            if not sources:
                print(f"Error: No valid sources found in {filename}", file=sys.stderr)
                sys.exit(1)

            print(f"Found {len(sources)} valid sources to process")
            return sources

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
           whisper_subs.py --file/-d [file_or_directory]
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a single video
  whisper_subs.py large https://youtu.be/DfU6llvIMcM

  # Process multiple videos from clipboard (one per line)
  whisper_subs.py large

  # Process from a file containing URLs (one per line)
  whisper_subs.py large -p my_videos.txt

  # Continue the last unfinished job
  whisper_subs.py --continue

  # Process a local file
  whisper_subs.py large --file /path/to/audio.mp3

  # Process a local directory
  whisper_subs.py large -d /path/to/directory/

  # List all jobs
  whisper_subs.py --list
"""
    )

    # Model and source arguments
    model_group = parser.add_argument_group('Source and Model')
    model_group.add_argument('model', nargs='?',
                           help="Whisper model name/index (e.g., 'tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3')")
    model_group.add_argument('source', nargs='?',
                           help="URL, local file/directory path, or multiple paths/URLs separated by newlines.")

    # Source type arguments (explicit source specification)
    source_group = parser.add_argument_group('Source Specification')
    source_group.add_argument('--url', '-u', dest='url_source',
                           help="YouTube/Twitch URL to transcribe (overrides positional source)")
    source_group.add_argument('--file', '-F', dest='file_source',
                           help="Local audio/video file to transcribe (overrides positional source)")
    source_group.add_argument('--dir', '-d', dest='dir_source',
                           help="Local directory to transcribe all media files (overrides positional source)")

    # Action arguments
    action_group = parser.add_argument_group('Actions')
    action_group.add_argument('-l', '--list', action='store_true',
                            help="List all jobs and exit.")
    action_group.add_argument('-c', '--continue', dest='continue_last',
                            action='store_true',
                            help="Continue the last unfinished job.")
    action_group.add_argument('-p', '--process-file', nargs='?', const=PROCESS_FILE,
                            help="Read sources from a file (one per line). If no file is specified, uses 'Youtube-Subs/process.txt'.")

    # Processing options
    process_group = parser.add_argument_group('Processing Options')
    process_group.add_argument('-g', '--gpu', action='store_true',
                             help="Use GPU (CUDA) if available.")
    process_group.add_argument('--device', default='cpu',
                             help="Device to use ('cpu', 'cuda', 'mps'). Default: 'cpu'")
    process_group.add_argument('--compute', default='int8',
                             help="Compute type ('int8', 'float16'). Default: 'int8'")
    process_group.add_argument('--cpu-threads', type=int, default=None,
                             help="Number of CPU threads for transcription (default: auto-detect)")
    process_group.add_argument('-f', '--force', action='store_true',
                             help="Force transcription even if already processed.")
    process_group.add_argument('-r', '--force-retry', action='store_true', help="Force retry transcription even if already completed (ignores existing subtitles).")
    process_group.add_argument('-i', '--ignore-subs', action='store_true',
                             help="Ignore existing subtitles.")
    process_group.add_argument('-lang', '--language',
                             help="Language code for subtitle priority.")
    process_group.add_argument('--cross-tier', action='store_true',
                             help="Allow comparison between multilingual and English-only models.")
    process_group.add_argument('-m', '--run', action='store_true', help="Run player in background.")
    process_group.add_argument('--live', action='store_true', help="Transcribe live streams in real-time (for Twitch/YouTube live streams).")
    process_group.add_argument('--video', action='store_true', help="Save the video file (default: False/audio-only).")
    process_group.add_argument('--no-thumbnail', action='store_false', dest='save_thumbnail', help="Do not save the video thumbnail.")
    process_group.set_defaults(save_thumbnail=True)

    # Advanced transcription options
    advanced_group = parser.add_argument_group('Advanced Transcription Options')
    advanced_group.add_argument('--vad', action='store_false',
                              help="Disable Voice Activity Detection (VAD) filter.")
    advanced_group.add_argument('--vad-silence', type=int, default=500,
                              help="VAD minimum silence duration in ms (default: 500).")
    advanced_group.add_argument('--diarization', action='store_true',
                              help="Enable speaker diarization.")
    advanced_group.add_argument('--min-speakers', type=int, default=1,
                              help="Minimum number of speakers for diarization (default: 1).")
    advanced_group.add_argument('--max-speakers', type=int, default=2,
                              help="Maximum number of speakers for diarization (default: 2).")
    advanced_group.add_argument('--temperature', type=float, default=0,
                              help="Sampling temperature for transcription (default: 0).")
    advanced_group.add_argument('--merge-lines', action='store_true',
                              help="Merge adjacent subtitle lines.")
    advanced_group.add_argument('--start-time', '--start', type=str, default=None,
                              help="Start time to transcribe (format: HH:MM:SS or seconds).")
    advanced_group.add_argument('--end-time', '--end', type=str, default=None,
                              help="End time to transcribe (format: HH:MM:SS or seconds).")
    advanced_group.add_argument('--mpv-ipc', action='store_true',
                              help="Enable MPV IPC subtitle reload during transcription (updates subtitles in real-time).")
    advanced_group.add_argument('--mpv-socket', type=str, default='/tmp/mpvsocket',
                              help="MPV IPC socket path (default: /tmp/mpvsocket).")
    args = parser.parse_args()

    if args.list:
        list_jobs()
        return

    # Handle continue case first
    if args.continue_last:
        job = get_last_unfinished_job()
        if not job:
            print("No unfinished jobs to continue.")
            return 1  # Exit with error code

        tasks = job.get('tasks', [])
        completed = len([t for t in tasks if t['status'] in ['completed', 'skipped', 'failed']])
        total = len(tasks)

        print(f"Continuing job ID {job['id']}")
        print(f"Source: {job['source']}")
        print(f"Progress: {completed}/{total} tasks completed")
        print(f"Model: {job['model']}")

        model_to_use = job['model']
        job_or_source = job
    elif args.process_file is not None:
        try:
            # Expand ~ in the file path
            process_file = os.path.expanduser(args.process_file)
            print(f"Reading sources from file: {process_file}")
            sources = read_sources_from_file(process_file)
            if not sources:
                print(f"No valid sources found in {process_file}", file=sys.stderr)
                return 1

            # For process files, handle each source individually with its model
            for source_info in sources:
                # Use the model from source_info if present, otherwise use the default args.model
                source_model = source_info['model'] or args.model
                if source_model is None:
                    print("Error: No model specified for source and no default model provided. Either specify a model in your process file or provide a model argument (e.g., 'wsub large -p').", file=sys.stderr)
                    return 1
                model_for_this_source = _get_model().getName(source_model)
                processor = WhisperSubs(
                    model_name=model_for_this_source,
                    device='cuda' if args.gpu else args.device,
                    compute_type=args.compute,
                    force=args.force,
                    ignore_subs=args.ignore_subs,
                    sub_lang=args.language,
                    run_mpv=args.run,
                    strict_language_tier=args.cross_tier,
                    force_retry=args.force_retry,
                    vad_filter=args.vad,
                    vad_min_silence_duration=args.vad_silence,
                    diarization=args.diarization,
                    min_speakers=args.min_speakers,
                    max_speakers=args.max_speakers,
                    temperature=args.temperature,
                    merge_lines=args.merge_lines,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    mpv_ipc=args.mpv_ipc,
                    mpv_socket=args.mpv_socket,
                    cpu_threads=args.cpu_threads,
                    save_video=args.video,
                    save_thumbnail=args.save_thumbnail
                )
                processor.process(source_info['url'])

            return 0  # Exit early since we processed all files
        except Exception as e:
            print(f"Error reading process file: {e}", file=sys.stderr)
            return 1
    else:
        # Handle normal source input
        # Priority: --url/--file/--dir > positional source > clipboard
        job_or_source = None

        # Check explicit source arguments first
        if args.url_source:
            job_or_source = args.url_source
            print(f"Using URL: {job_or_source}")
        elif args.file_source:
            if not os.path.exists(args.file_source):
                parser.error(f"File not found: {args.file_source}")
            job_or_source = args.file_source
            print(f"Using file: {job_or_source}")
        elif args.dir_source:
            if not os.path.isdir(args.dir_source):
                parser.error(f"Directory not found: {args.dir_source}")
            job_or_source = args.dir_source
            print(f"Using directory: {job_or_source}")
        elif args.source:
            job_or_source = args.source

        model_to_use = args.model
        print(f"Model: {model_to_use} {_get_model().getName(model_to_use)}")
        model_to_use = _get_model().getName(model_to_use)

        # If no source provided, check clipboard
        if not job_or_source:
            try:
                clipboard_content = pyperclip.paste().strip()
                if not clipboard_content:
                    parser.error("No source provided and clipboard is empty.")

                # Process clipboard content
                sources = [line.strip() for line in clipboard_content.split('\n') if line.strip()]
                if len(sources) == 1:
                    print(f"Using source from clipboard: {sources[0]}")
                    job_or_source = sources[0]
                else:
                    print(f"Found {len(sources)} sources in clipboard:")
                    for i, src in enumerate(sources[:5], 1):
                        print(f"  {i}. {src[:80]}{'...' if len(src) > 80 else ''}")
                    if len(sources) > 5:
                        print(f"  ... and {len(sources) - 5} more"
                              " (processing all in a single batch)")
                    job_or_source = '\n'.join(sources)
            except Exception as e:
                parser.error(f"No source provided and could not read clipboard: {e}")

    # Handle model selection
    if args.continue_last:
        model_to_use = _get_model().getName(job['model'])
    elif args.process_file:
        # For process file, we'll get the model from the file or use default
        # This will be handled in the process file loop
        pass
    elif not args.model and not any([args.list, args.continue_last, args.url_source, args.file_source, args.dir_source]):
        parser.error("Model argument is required unless using --list, --continue, --url, --file, or --dir.")
    else:
        model_to_use = _get_model().getName(args.model)

    # Handle live stream transcription separately
    if args.live:
        if not job_or_source or (isinstance(job_or_source, str) and not job_or_source.strip()):
            print("Error: Live stream mode requires a URL", file=sys.stderr)
            return 1

        # Extract URL if it's a string (might be a list if multiple sources)
        source_url = job_or_source
        if isinstance(job_or_source, list):
            if len(job_or_source) != 1:
                print("Error: Live stream mode requires exactly one URL", file=sys.stderr)
                return 1
            source_url = job_or_source[0]
        elif "\n" in job_or_source:
            # Handle multi-line input
            sources = [line.strip() for line in job_or_source.split('\n') if line.strip()]
            if len(sources) != 1:
                print("Error: Live stream mode requires exactly one URL", file=sys.stderr)
                return 1
            source_url = sources[0]

        # Create live stream transcriber and start transcription
        live_transcriber = livestream_transcriber.LiveStreamTranscriber(
            model_name=model_to_use,
            device='cuda' if args.gpu else args.device,
            compute_type=args.compute,
            output_dir=OUTPUT_DIR,
            log_func=lambda msg: print(f"[LIVE] {msg}")
        )

        try:
            live_transcriber.start_transcription(source_url)
            print("Live stream transcription completed")
        except KeyboardInterrupt:
            print("\nStopping live stream transcription...")
            live_transcriber.stop()
        except Exception as e:
            print(f"Error during live stream transcription: {e}")
            live_transcriber.stop()
            return 1

        return 0  # Exit successfully after live transcription

    # Only create processor for non-process-file cases (file processing handled in loop above)
    if not args.process_file:
        processor = WhisperSubs(
            model_name=model_to_use,
            device='cuda' if args.gpu else args.device,
            compute_type=args.compute,
            force=args.force,
            ignore_subs=args.ignore_subs,
            sub_lang=args.language,
            run_mpv=args.run,
            strict_language_tier=args.cross_tier,
            force_retry=args.force_retry,
            vad_filter=args.vad,
            vad_min_silence_duration=args.vad_silence,
            diarization=args.diarization,
            min_speakers=args.min_speakers,
            max_speakers=args.max_speakers,
            temperature=args.temperature,
            merge_lines=args.merge_lines,
            start_time=args.start_time,
            end_time=args.end_time,
            mpv_ipc=args.mpv_ipc,
            mpv_socket=args.mpv_socket,
            cpu_threads=args.cpu_threads,
            save_video=args.video,
            save_thumbnail=args.save_thumbnail
        )
        processor.process(job_or_source)

if __name__ == "__main__":
    main()
