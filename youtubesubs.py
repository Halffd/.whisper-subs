import sys
import model
import argparse
from typing import Optional
from whisper_model_chooser import WhisperModelChooser
default = 'base'
device = 'cpu'
g = ['gpu', 'cuda', '-g']
for a in sys.argv:
    for b in g:
        if b in a:
            print("Using GPU")
            device = 'cuda'
            break
    if device == 'cuda':
        break
model_name = model.getName(sys.argv[1])
start_time = '00:00:00'
reverse = 0
import os
import subprocess
import yt_dlp
import re
import datetime
import urllib.parse
import time
import pyperclip
import twitch_vod
import shlex
from urllib.parse import urlparse
from html import unescape
from html import escape

channel_name = 'unknown'
video_title = 'none'
subs_dir = os.path.join("Documents", "Youtube-Subs")
log_dir = "Documents"
oldest = '--oldest' in sys.argv or reverse == 1
delay = 30
start_delay = delay

ytsubs = os.path.join(os.path.expanduser("~"), subs_dir)
start = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
progress_name = f'progress-{start}'
progress_file = os.path.join(ytsubs, f'{progress_name}.log')
history_file = os.path.join(ytsubs, 'history.txt')
urls_file = os.path.join(ytsubs, 'urls.txt')

def rename(name, repl = False):
    global progress_file, progress_name
    try:
        progress_name = name if repl else f'progress-{name}'
        new = os.path.join(ytsubs, f'{progress_name}.log')
        if os.path.exists(progress_file):
            os.rename(progress_file, new)
        progress_file = new
    except Exception as e:
        write(e)

def write(*text, mpv = 'err'):
    global progress_file
    text = [str(item) if not isinstance(item, re.Match) else item.group(0) for item in text] # Convert Match objects to strings
    text = ' '.join(text)

    if len(str(text)) < 100:
        print(text)
    else:
        print(str(text)[0:100])

    with open(file=progress_file, mode='a', encoding="utf-8") as f:
        try:
            f.write(f"{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')} :  {str(text)}\n")
            if mpv != 'err':
                f.write(f"{datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')} :  {str(mpv)}\n")
        except UnicodeEncodeError:
            print(f"Warning: Could not write all characters to the file. Skipping problematic characters.")
            f.write('\n' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ' : ' + mpv.encode('ascii', 'ignore').decode('ascii'))
        except Exception as e:
            print(e)
            f.write(e + '\n')
class YoutubeSubs:
    def __init__(self, model_name='base', device='cpu', compute='int8_float32', force_device=False, subs_dir=None, enable_logging=True, use_cookies=True, browser='chrome'):
        self.model_name = model_name
        self.device = device
        self.compute = compute
        self.force_device = force_device
        self.channel_name = 'unknown'
        self.video_title = 'none'
        self.delay = 30
        self.start_delay = 30
        self.enable_logging = enable_logging
        self.start_time = None
        self.end_time = None
        self.use_cookies = use_cookies
        self.specified_browser = browser
        
        # Setup directories
        self.subs_dir = subs_dir or os.path.join("Documents", "Youtube-Subs")
        self.ytsubs = os.path.join(os.path.expanduser("~"), self.subs_dir)
        self.localsubs = os.path.join(self.ytsubs, "local")
        os.makedirs(self.ytsubs, exist_ok=True)
        os.makedirs(self.localsubs, exist_ok=True)
        
        # Setup logging
        self.start = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        self.progress_name = f'progress-{self.start}'
        self.progress_file = os.path.join(self.ytsubs, f'{self.progress_name}.log')
        self.history_file = os.path.join(self.ytsubs, 'history.txt')
        self.urls_file = os.path.join(self.ytsubs, 'urls.txt')
        self.channel_progress_file = os.path.join(self.ytsubs, 'channel_progress.json')

        self.clean_dirs()
    def write(self, *text, mpv='err'):
        """Log messages to file and through callback"""
        if not self.enable_logging:
            return
            
        text = [str(item) if not isinstance(item, re.Match) else item.group(0) for item in text]
        text = ' '.join(text)
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        log_text = f"{timestamp} :  {str(text)}"

        with open(file=self.progress_file, mode='a', encoding="utf-8") as f:
            try:
                f.write(f"{log_text}\n")
                if mpv != 'err':
                    f.write(f"{timestamp} :  {str(mpv)}\n")
            except UnicodeEncodeError:
                f.write(f"Warning: Could not write all characters. Skipping problematic characters.\n")
                f.write(text.encode('ascii', 'ignore').decode('ascii') + '\n')
            except Exception as e:
                f.write(f"Error writing to log: {str(e)}\n")
    def clean_dirs(self):
        """Clean up directories"""
        try:
            scriptDir = os.path.dirname(os.path.abspath(__file__))
            files = os.listdir(scriptDir) + os.listdir(self.ytsubs)
            mediaFiles = [file for file in files if file.endswith('.mp3') or file.endswith('.mp4') or file.endswith('.webm') or file.endswith('.m4a')]
            for file in mediaFiles:
                # check date, minimum 1h
                if os.path.getmtime(os.path.join(scriptDir, file)) < time.time() - 3600:
                    os.remove(os.path.join(scriptDir, file))
            self.write("Cleaned up directories")
        except Exception as e:
            self.write(str(e))
    def rename_log(self, name, repl=False):
        """Rename the progress log file"""
        try:
            self.progress_name = name if repl else f'progress-{name}'
            new = os.path.join(self.ytsubs, f'{self.progress_name}.log')
            if os.path.exists(self.progress_file):
                os.rename(self.progress_file, new)
            self.progress_file = new
        except Exception as e:
            self.write(str(e))

    def clean_filename(self, filename):
        """Clean filename of invalid characters"""
        filename = filename.strip().strip('.')
        filename = re.sub(r'\.+', '.', filename)
        cleaned = re.sub(r"[<>!@#$%^&*(),/'?\|\"\-;:\[\]\{\}|\\]", "", filename)
        if cleaned[-1] == ".":
            cleaned = cleaned[:-1]
        return cleaned

    def get_channel_id(self, url):
        """Extract channel ID from URL"""
        # Handle different channel URL formats
        if '/channel/' in url:
            # Format: https://www.youtube.com/channel/UC...
            match = re.search(r'/channel/([a-zA-Z0-9_-]+)', url)
            if match:
                return match.group(1)
        elif '/c/' in url:
            # Format: https://www.youtube.com/c/ChannelName
            match = re.search(r'/c/([a-zA-Z0-9_-]+)', url)
            if match:
                return f"c_{match.group(1)}"
        elif '@' in url:
            # Format: https://www.youtube.com/@Username
            match = re.search(r'/@([a-zA-Z0-9_-]+)', url)
            if match:
                return f"@{match.group(1)}"
        elif '/user/' in url:
            # Format: https://www.youtube.com/user/Username
            match = re.search(r'/user/([a-zA-Z0-9_-]+)', url)
            if match:
                return f"user_{match.group(1)}"
        # For playlist URLs
        elif 'list=' in url:
            match = re.search(r'list=([a-zA-Z0-9_-]+)', url)
            if match:
                return f"playlist_{match.group(1)}"

        # If none of the above, return a hash of the URL
        return f"url_hash_{hash(url) % 1000000}"

    def load_channel_progress(self):
        """Load channel progress from file"""
        import json
        try:
            if os.path.exists(self.channel_progress_file):
                with open(self.channel_progress_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            self.write(f"Error loading channel progress: {str(e)}")
        return {}

    def save_channel_progress(self, progress_data):
        """Save channel progress to file"""
        import json
        try:
            with open(self.channel_progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, indent=2)
        except Exception as e:
            self.write(f"Error saving channel progress: {str(e)}")

    def get_channel_progress(self, channel_id):
        """Get progress for a specific channel"""
        progress_data = self.load_channel_progress()
        return progress_data.get(channel_id, {
            'total_videos': 0,
            'completed_videos': [],
            'last_check_count': 0
        })

    def update_channel_progress(self, channel_id, total_videos, completed_video_ids):
        """Update progress for a specific channel"""
        progress_data = self.load_channel_progress()
        channel_info = progress_data.get(channel_id, {})

        # Update the channel info
        channel_info['total_videos'] = total_videos
        channel_info['completed_videos'] = list(set(completed_video_ids))  # Ensure uniqueness
        channel_info['last_check_count'] = total_videos

        progress_data[channel_id] = channel_info
        self.save_channel_progress(progress_data)

    def should_process_channel(self, channel_id, current_video_count):
        """Determine if channel should be processed based on progress"""
        channel_progress = self.get_channel_progress(channel_id)

        # If no previous record, process the channel
        if not channel_progress or channel_progress['total_videos'] == 0:
            return True

        # If the video count has increased, process the channel
        if current_video_count > channel_progress['last_check_count']:
            self.write(f"Channel {channel_id} has new videos ({current_video_count} > {channel_progress['last_check_count']})")
            return True

        # If all previously known videos are completed, but count is the same,
        # check if there are new videos we didn't know about
        completed_count = len(channel_progress['completed_videos'])
        if completed_count >= channel_progress['total_videos'] and current_video_count == channel_progress['total_videos']:
            # All known videos are done and no new videos added
            self.write(f"Channel {channel_id} already fully processed with {current_video_count} videos")
            return False

        # Otherwise, process the channel
        return True

    def download_audio(self, url, rec=False):
        """Download audio from YouTube URL"""
        oldest = '--oldest' in sys.argv or reverse == 1 or '-o' in sys.argv
        force = '-f' in sys.argv or "--force" in sys.argv

        if not rec or self.delay > 3600:
            self.delay = self.start_delay
        os.chdir(self.ytsubs)

        # Initialize the list to capture downloaded files
        downloaded_files = []

        def progress_hook(d):
            if d['status'] == 'finished':
                if 'filename' in d:
                    downloaded_files.append(d['filename'])

        try:
            ydl_opts = {
                'outtmpl': '%(title)s.%(ext)s',
                # More flexible format selection
                'format': 'bestaudio[ext=m4a]/bestaudio/best[height<=720]/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'm4a',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': False,
                'progress_hooks': [progress_hook],
                # Add these for rate limiting
                'sleep_interval': 10,
                'max_sleep_interval': 30,
                'sleep_interval_requests': 5,
                'sleep_interval_subtitles': 5,
                # Retry settings
                'retries': 3,
                'fragment_retries': 3,
            }

            # Add cookies if available
            if self.use_cookies and self.specified_browser:
                 ydl_opts['cookiesfrombrowser'] = (self.specified_browser,)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                # Check for existing subtitles
                try:
                    if info['subtitles'] != {} and not force:
                        if not('live_chat' in info['subtitles'] and len(info['subtitles']) < 2):
                            return None
                        elif any(lang in info['subtitles'] for lang in ['en', 'pt', 'pt-BR']):
                            return None
                except:
                    self.write('No subs info')

                # Get video info
                self.channel_name = info.get('channel', '')
                timestamp = info.get('timestamp', '')
                date_time = datetime.datetime.fromtimestamp(timestamp)
                timeday = date_time.strftime('%Y-%m-%d')
                self.video_title = timeday + '_' + self.clean_filename(info.get('title', 'unknown'))

                # Update outtmpl to include model name and use proper format
                ydl_opts['outtmpl'] = f"{self.video_title}.{self.model_name}.%(ext)s"

                self.write(' '.join([str(self.delay), self.channel_name, str(timestamp),
                                   str(date_time), self.video_title]))

            # Add time range options if needed
            if self.start_time or self.end_time:
                ydl_opts['postprocessor_args'] = {
                    'ffmpeg': []
                }
                if self.start_time:
                    ydl_opts['postprocessor_args']['ffmpeg'].extend(['-ss', self.start_time])
                if self.end_time:
                    ydl_opts['postprocessor_args']['ffmpeg'].extend(['-to', self.end_time])

            # Download using yt_dlp directly with updated options
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Return the actual downloaded file
            if downloaded_files:
                return downloaded_files[0]
            return None

        except Exception as e:
            self.delay *= 2
            self.write(f"Download error: {str(e)}")
            if "Sign in to confirm your age" in str(e) and not self.use_cookies:
                self.write("Age-restricted video detected. Enable cookie support to download")
            time.sleep(self.delay)
            return self.download_audio(url, True)

    def get_youtube_videos(self, url, rec=False, sort_order='newest'):
        """Get list of video URLs from channel/playlist"""
        oldest = '--oldest' in sys.argv or reverse == 1 or '-o' in sys.argv
        if not rec:
            self.delay = 120  # Start with 2 minutes minimum
        else:
            # Exponential backoff that actually works
            self.delay = min(self.delay * 1.5, 7200)  # Cap at 2 hours

        self.write(f"Waiting {self.delay}s before request...")
        time.sleep(self.delay) if self.use_cookies else 0

        try:
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': '%(title)s.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': False,
                'sleep_interval': 3,  # Built-in delay between requests
                'max_sleep_interval': 10,
            }
            if self.use_cookies and self.specified_browser:
                 ydl_opts['cookiesfrombrowser'] = (self.specified_browser,)

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                # Get channel ID for progress tracking
                channel_id = self.get_channel_id(url)

                if 'entries' in info:
                    video_entries = []
                    for entry in info['entries']:
                        try:
                            if entry and entry.get('subtitles') == {}:
                                video_entries.append(entry)
                        except (KeyError, TypeError):
                            continue

                    # Get video URLs
                    video_urls = [entry['webpage_url'] for entry in video_entries]

                    # Apply sorting based on sort_order parameter
                    if sort_order == 'oldest':
                        # Reverse to get oldest first
                        video_urls.reverse()
                    elif sort_order == 'popular':
                        # For popular sorting, we need to get additional info about each video
                        # This requires a more complex approach to get view counts
                        try:
                            # Create a mapping of URL to view count
                            video_info_map = {}
                            for entry in video_entries:
                                video_url = entry.get('webpage_url')
                                view_count = entry.get('view_count', 0) or 0
                                video_info_map[video_url] = view_count

                            # Sort URLs by view count (descending for most popular first)
                            video_urls.sort(key=lambda url: video_info_map.get(url, 0), reverse=True)
                        except:
                            # If we can't sort by popularity, fall back to default order
                            pass

                    # Check if we should process this channel based on progress
                    if not self.should_process_channel(channel_id, len(video_urls)):
                        self.write(f"Skipping channel {channel_id} - already processed")
                        return []

                    # Update channel progress with current state
                    video_ids = [self.get_video_id(url) for url in video_urls]
                    self.update_channel_progress(channel_id, len(video_urls), video_ids)

                    return video_urls
                else:
                    return [info['webpage_url']]

        except Exception as e:
            error_msg = str(e).lower()
            if 'rate' in error_msg or 'limit' in error_msg or 'unavailable' in error_msg:
                self.delay = min(self.delay * 2, 3600)  # Cap at 1 hour
                self.write(f"Rate limited. Next retry in {self.delay}s")
                return self.get_youtube_videos(url, True, sort_order)
            else:
                self.write(f"Error: {str(e)}")
                return []


    def update_history(self, video_id):
        """Update history file with processed video"""
        try:
            with open(self.history_file, 'a', encoding="utf-8") as f:
                f.write(f"{video_id} {self.model_name}\n")
        except Exception as e:
            self.write(f"Error updating history: {str(e)}")

    @staticmethod
    def remove_time_param(url):
        """Remove time parameters from YouTube URL"""
        if "youtu.be" in url:
            video_id = url.split('/')[-1]
            return f"https://www.youtube.com/watch?v={video_id}"
        else:
            v_index = url.find('v=')
            if v_index == -1:
                return url
            
            start_index = v_index + 2
            end_index = url.find('&', start_index)
            video_id = url[start_index:end_index] if end_index != -1 else url[start_index:]
            return f"https://www.youtube.com/watch?v={video_id}"

    @staticmethod
    def get_video_id(url):
        """Extract video ID from YouTube URL"""
        pattern = r'(?:https?://)?(?:www\.)?(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|v/|user/\S+|[^/]+\?v=))([^&"\'<>\s]+)'
        match = re.search(pattern, url)
        return match.group(1) if match else None

    def sort_by_date(self, urls):
        """Sort URLs by video upload date"""
        video_dates = []
        
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                for url in urls:
                    try:
                        info = ydl.extract_info(url, download=False)
                        timestamp = info.get('timestamp', 0)
                        video_dates.append((timestamp, url))
                    except:
                        video_dates.append((0, url))
                        
            # Sort by timestamp
            video_dates.sort()
            return [url for _, url in video_dates]
            
        except Exception as e:
            self.write(f"Error sorting videos: {str(e)}")
            return urls
    def remove_from_urls(self, url):
        urls = []
        with open(self.urls_file, 'r', encoding='utf-8') as f:
            urls = f.read().splitlines()
        with open(self.urls_file, 'w', encoding='utf-8') as f:
            for u in urls:
                if u != url:
                    f.write(u + '\n')
    @staticmethod
    def is_url(url):
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False
    @staticmethod
    def is_file(text):
        return YoutubeSubs.file(text) is not None
    @staticmethod
    def is_dir(text):
        file = YoutubeSubs.file(text)
        if not file:
            return False
        return os.path.isdir(file)
    @staticmethod
    def file(text):
        try:
            # Let shlex handle the unescaping like a shell would
            unescaped = shlex.split(text)[0] if text else ""
            full_path = os.path.expanduser(unescaped)
            if os.path.isfile(full_path):
                return full_path
            return None
        except ValueError:
            return None
    def process_file(self, file_path, callback=print):
        """Process multiple URLs from file or audio file"""
        import transcribe
        ext = os.path.splitext(os.path.basename(file_path))[1].lower()
        callback(f"{file_path} extension: {ext}")
        if any(ext in s for s in ['.mp3', '.wav', '.flac', '.m4a', '.ogg']):
            srt_file = os.path.splitext(file_path)[0] + '.srt' if not 'downloads' in file_path else os.path.join(self.localsubs, os.path.splitext(file_path)[0] + '.srt')
            callback(f"Processing file: {file_path} to {srt_file}")
            success = transcribe.process_create(
                    file=file_path, 
                    model_name=self.model_name,
                    srt_file=srt_file,
                    language=None,
                    device=self.device,
                    compute_type=self.compute,
                    force_device=self.force_device,
                    write=callback
                )
            if success:
                print(f"Transcribed {file_path}")
            else:
                print(f"Failed to transcribe {file_path}")
            return
        callback(f"Processing URLs from file: {file_path}")
        with open(file_path, 'r', encoding='utf-8') as f:
            urls = f.read().splitlines()
        self.process_urls('\n'.join(urls), callback)
    def process_twitch_channel(self, channel, callback=print):
        downloader = twitch_vod.StreamlinkVODDownloader()
    def process_urls(self, urls_text, callback=print, sort_order='newest', shuffle_tasks=False):
        """Process multiple URLs from text input"""
        callback(f"Processing URLs: {urls_text}")
        # Fix the urls_file issue
        if not hasattr(self, 'urls_file') or not self.urls_file:
            self.urls_file = os.path.join(os.getcwd(), 'urls.txt')
        # Clean and filter URLs
        urls = urls_text.replace('\r', '').split('\n')
        urls = [url.strip() for url in urls if url and 'youtu' in url]
        file_path = self.file(urls_text)

        if file_path:
            if self.is_dir(urls_text):
                files = os.listdir(urls_text)
                callback(f"Found {len(files)} files in directory: {urls_text}")
                for file in files:
                    callback(f"Processing file: {file}")
                    if file.endswith('.mp3') or file.endswith('.wav') or file.endswith('.flac') or file.endswith('.m4a') or file.endswith('.ogg'):
                        self.process_file(file, callback)
                return
            callback(f"File path: {file_path}")
            self.process_file(file_path, callback)
            return

        if not urls:
            callback("⚠️ No YouTube URLs found!")
            return

        callback(f"📋 Found {len(urls)} YouTube URLs to process")

        # Shuffle tasks if requested
        if shuffle_tasks:
            import random
            random.shuffle(urls)
            callback(f"🔀 Tasks shuffled")

        processed_videos = []  # Track what we actually process
        # lambda writer, no duplicates
        duplicates = set()
        with open(self.urls_file, 'w+', encoding='utf-8') as f:
            for line in f:
                if line.strip() not in duplicates:
                    f.write(line)
                duplicates.add(line.strip())
        with open(self.urls_file, 'a', encoding='utf-8') as f:
            for url in urls:
                if url not in duplicates:
                    f.write(url + ' ' + self.model_name + '\n')
                    duplicates.add(url)
        for i, url in enumerate(urls, 1):
            try:
                callback(f"🔄 Processing {i}/{len(urls)}: {url}")

                # Better channel/playlist detection
                if self.is_channel_or_playlist_url(url):
                    callback(f"📺 Detected channel/playlist URL")
                    video_urls = self.get_youtube_videos(url, sort_order=sort_order)
                    if video_urls:
                        callback(f"📹 Found {len(video_urls)} videos in channel/playlist")
                        with open(self.urls_file + '.tmp', 'a', encoding='utf-8') as f:
                            for video_url in video_urls:
                                if video_url not in duplicates:
                                    f.write(video_url + '\n')
                                    duplicates.add(video_url)
                        # Process each video
                        for j, video_url in enumerate(video_urls, 1):
                            callback(f"  🎬 Processing video {j}/{len(video_urls)}")
                            self.process_single_url(video_url, callback)
                            processed_videos.append(video_url)
                        self.remove_from_urls(url)
                    else:
                        callback(f"⚠️ No videos found in channel/playlist")

                else:
                    # Single video URL
                    self.process_single_url(url, callback)
                    processed_videos.append(url)
                    self.remove_from_urls(url)
            except Exception as e:
                callback(f"❌ Error processing {url}: {str(e)}")

        callback(f"✅ Finished! Processed {len(processed_videos)} videos total")
    def is_channel_or_playlist_url(self, url):
        """only TRUE playlists/channels, not videos in playlists"""
        
        # If it has a specific video ID (v=), it's a single video regardless of list parameter
        if 'v=' in url:
            return False  # It's a specific video, even if it has &list=
        
        # These are definitely channels/playlists
        true_playlist_indicators = [
            '@',  # @username channels
            '/channel/',
            '/c/',
            '/user/',
            'youtube.com/playlist?list=',  # Direct playlist URLs
            'youtu.be/playlist?list=',     # Short playlist URLs
        ]
        
        return any(indicator in url for indicator in true_playlist_indicators)
    def process_single_url(self, url, callback=print):
        """Process a single YouTube URL"""
        import transcribe
        try:
            url = self.remove_time_param(url)
            video_id = self.get_video_id(url)
            
            # Check history first
            try:
                if os.path.exists(self.history_file):
                    with open(self.history_file, "r", encoding='utf-8') as f:
                        history = f.readlines()
                        for line in history:
                            parts = line.strip().split()
                            if len(parts) >= 2:
                                hist_id, hist_model = parts[0], parts[1]
                                if hist_id == video_id and hist_model == self.model_name:
                                    callback(f"Skipping {url} - already processed with model {self.model_name}")
                                    return
            except Exception as e:
                callback(f"Error checking history: {str(e)}")
            
            # Download and process audio
            audio_file = self.download_audio(url)
            if audio_file is None:
                raise FileNotFoundError("No audio file, subtitles may be available")
    
            # Setup output paths - ensure using Documents/Youtube-Subs
            folder_name = os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs", self.channel_name)
            os.makedirs(folder_name, exist_ok=True)
            
            name = os.path.splitext(os.path.basename(audio_file))[0]
            srt_file = os.path.join(folder_name, name + ".srt")
            
            # Create unfinished SRT file and helper files at start  
            unfinished_srt = srt_file.replace('.srt', '.unfinished.srt')
            os.makedirs(os.path.dirname(unfinished_srt) or '.', exist_ok=True)
            with open(unfinished_srt, 'w', encoding='utf-8') as f:
                f.write('')
            # Pass the URL to make_files for the unfinished version
            transcribe.make_files(unfinished_srt, url=url)  # Pass URL for helper files
            try:
                print(f"File: {audio_file}\nModel: {self.model_name}\nDevice: {self.device}\nCompute: {self.compute}\nForce Device: {self.force_device}\nSrt file: {srt_file}")
                # Transcribe
                success = transcribe.process_create(
                    file=audio_file, 
                    model_name=self.model_name,
                    srt_file=srt_file,
                    language=None,
                    device=self.device,
                    compute_type=self.compute,
                    force_device=self.force_device,
                    auto=True,
                    write=callback
                )

                if success:
                    # Create helper files for completed transcription
                    transcribe.make_files(srt_file, url=url)
                    # Update history
                    self.update_history(video_id)
                    
                    # Clean up unfinished files
                    try:
                        if os.path.exists(unfinished_srt):
                            os.remove(unfinished_srt)
                            # Remove any helper files for the unfinished version
                            base_name = os.path.splitext(unfinished_srt)[0]
                            for ext in ['.sh', '.bat', '.htm']:
                                helper_file = f"{base_name}{ext}"
                                if os.path.exists(helper_file):
                                    os.remove(helper_file)
                    except Exception as e:
                        callback(f"Warning: Could not clean up temporary files: {str(e)}")
                    # Remove url from urls file
                    with open(urls_file, 'r+', encoding='utf-8') as f:
                        lines = f.readlines()
                        f.seek(0)
                        f.writelines(line for line in lines if line.strip() != url.strip())
                        f.truncate()
            except Exception as e:
                callback(f"Error: {str(e)}")    
            # Cleanup
            try:
                for ext in ['.sh', '.bat', '.htm']:
                    helper_file = f"{os.path.splitext(unfinished_srt)[0]}{ext}"
                    if os.path.exists(helper_file):
                        os.remove(helper_file)
            except Exception as e:
                callback(f"Warning: Could not clean up temporary files: {str(e)}")
            if os.path.exists(audio_file):
                os.remove(audio_file)
            
        except Exception as e:
            callback(f"Error: {str(e)}")

def get_clipboard_content():
    """Get clipboard content from either pyperclip or the clipboard file"""
    try:
        # Try native clipboard first
        return pyperclip.paste()
    except:
        # Fall back to clipboard file
        clipboard_file = os.getenv('CLIPBOARD_FILE')
        if clipboard_file and os.path.exists(clipboard_file):
            try:
                with open(clipboard_file, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                write(f"Error reading clipboard file: {e}")
    return ""

def get_video_url() -> str:
    """Get video URL from clipboard or command line arguments"""
    urls = []
    # Try clipboard if no URL in arguments
    clipboard_content = get_clipboard_content()
    if clipboard_content and len(clipboard_content.strip()) > 0:
        urls = clipboard_content.replace('\r','').split('\n')
        urls = [url.strip() for url in urls if url.strip()]
    
    # If still no URLs, prompt user
    if not urls:
        url = input("Enter video URL/path: ")
        urls = [url]
    if not YoutubeSubs.is_url(urls[0]) and not YoutubeSubs.is_file(urls[0]):
        urls = [sys.argv[-1]]
    print("Video count:", len(urls))
    return urls

def main():
    try:
        # Check for new command line arguments manually to avoid interfering with existing logic
        oldest = '--oldest' in sys.argv or '-o' in sys.argv
        popular = '--popular' in sys.argv
        shuffle = '--shuffle' in sys.argv
        reverse = '--reverse' in sys.argv or '-r' in sys.argv

        # Get browser from command line (default to brave)
        browser = 'brave'  # default
        for i, arg in enumerate(sys.argv):
            if arg == '--browser' and i + 1 < len(sys.argv):
                browser = sys.argv[i + 1]
                break

        # Determine sort order based on arguments
        sort_order = 'newest'  # default
        if oldest:
            sort_order = 'oldest'
        elif popular:
            sort_order = 'popular'

        # Get URLs from clipboard or command line
        reverse_flag = True
        if reverse:
            reverse_flag = False
        urls = get_video_url()
        if reverse_flag:
            temp = urls.copy()
            for i in range(len(urls)):
                urls[i] = temp[len(urls) - 1 - i]

        # Create YouTube subs instance with specified browser
        yt = YoutubeSubs(model_name, device=device, browser=browser)
        print(f"Model: {model_name}")
        print(f"Device: {device}")
        print(f"Browser: {browser}")
        print(f"Sort order: {sort_order}")
        if shuffle:
            print("Tasks will be shuffled")

        yt.process_urls('\n'.join(urls), sort_order=sort_order, shuffle_tasks=shuffle)
    except Exception as e:
        write(f"Error in main: {e}")

if __name__ == "__main__":
    main()
