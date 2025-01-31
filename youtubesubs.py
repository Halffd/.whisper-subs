import sys
import model
default = 'base'
device = 'cuda'
if 'cpu' in sys.argv:
    device = 'cpu'
model_name = model.getName(sys.argv, default)
start_time = '00:00:00'
reverse = 0
if len(sys.argv) > 2:
    reverse = int(sys.argv[2])
import pyperclip
url = pyperclip.paste()
print(url)
if '--reversed' in sys.argv:
    urls = list(url.replace('\r','').split('\n'))
else:
    urls = list(reversed(url.replace('\r','').split('\n')))

print(urls)
print("Video count: " + str(len(urls)))


import os
import subprocess
import yt_dlp
import re
import datetime
import urllib.parse
import transcribe
import time
import caption.log as log

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
def clean_filename(filename):
    # Remove leading/trailing spaces
    filename = filename.strip()
    
    # Remove leading/trailing periods
    filename = filename.strip('.')
    
    # Replace multiple consecutive periods with a single period
    filename = re.sub(r'\.+', '.', filename)
        
    # Remove other special characters
    cleaned_filename = re.sub(r"[<>!@#$%^&*(),/'?\|\"\-;:\[\]\{\}|\\]", "", filename)
    if cleaned_filename[-1] == ".":
        cleaned_filename = cleaned_filename[:-1]
    write(cleaned_filename)
    return cleaned_filename
def convert_to_seconds(time_str):
    """Convert hh:mm:ss format to seconds."""
    if not time_str:
        return 0
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def download_audio(url, rec=False, audio_start_time='00:00:00'):
    global model_name, channel_name, delay, start_delay, video_title
    if not rec or delay > 3600:
        delay = start_delay
    try:
        ydl_opts = {
            'outtmpl': '%(title)s.%(ext)s',
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'cookies': 'media/cookies.txt',  # Replace with the actual path to your cookies file
            'ignoreerrors': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            try:
                if info['subtitles'] != {}:
                    if not('live_chat' in info['subtitles'] and len(info['subtitles']) < 2):
                        return None
                    elif any(lang in info['subtitles'] for lang in ['en', 'pt', 'pt-BR']):
                        return None
            except:
                print('No subs info')
            # Get the channel name
            channel_name = info.get('channel', '')
            timestamp = info.get('timestamp', '')
            date_time = datetime.datetime.fromtimestamp(timestamp)
            timeday = date_time.strftime('%Y-%m-%d')
            video_title = timeday + '_' + clean_filename(info.get('title', 'unknown'))
            audio_file = os.path.join(os.getcwd(), f"{video_title}.{model_name}.mp3")

            write(' '.join([str(delay), channel_name, str(timestamp), str(date_time), video_title, audio_file]))

        command = ["yt-dlp", "--extract-audio", "--audio-format", "mp3", "-o", audio_file, url]
        subprocess.run(command, check=True)

        # Convert the audio start time from hh:mm:ss to seconds
        start_time_seconds = convert_to_seconds(audio_start_time)

        # Use ffmpeg to mute the audio before the specified start time
        if start_time_seconds > 0:
            muted_audio_file = os.path.join(os.getcwd(), f"{video_title}_muted.mp3")
            ffmpeg_command = [
                'ffmpeg', '-i', audio_file,
                '-af', f"volume=0:enable='between(t,0,{start_time_seconds})'",
                muted_audio_file,
                '-y'  # Overwrite output file if it exists
            ]
            subprocess.run(ffmpeg_command, check=True)

            # Replace original audio file with the muted version
            os.replace(muted_audio_file, audio_file)

        return audio_file
    except Exception as e:
        delay *= 2
        write(delay, e)
        time.sleep(delay)
        download_audio(url, True, audio_start_time)
def remove_time_param(url):
    """
    Simplifies a YouTube URL to include only the base URL and the video ID,
    supporting both 'youtube.com' and 'youtu.be' formats.
    
    Args:
        url (str): The YouTube URL to be processed.
        
    Returns:
        str: The simplified URL containing only the base URL and video ID.
    """
    if "youtu.be" in url:
        # Extract video ID from youtu.be format
        video_id = url.split('/')[-1]
        return f"https://www.youtube.com/watch?v={video_id}"
    else:
        # Extract video ID from youtube.com format
        v_index = url.find('v=')
        if v_index == -1:
            return url  # Return original if 'v=' not found
        
        start_index = v_index + 2
        end_index = url.find('&', start_index)
        video_id = url[start_index:end_index] if end_index != -1 else url[start_index:]
        
        return f"https://www.youtube.com/watch?v={video_id}"
def get_youtube_videos(url, rec = False):
    global oldest, delay, start_delay
    if not rec or delay > 3600:
        delay = start_delay
    try:
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': '%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,            
            'cookies': 'media/cookies.txt'  # Replace with the actual path to your cookies file
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info:
                # This is a playlist
                # print(info['entries'], len(info['entries']),end="\n")
                video_urls = []
                for entry in info['entries']:
                    try:
                        if entry['subtitles'] == {}:
                            video_urls.append(entry['webpage_url'])
                    except Exception as err:
                        write(err)
                if oldest:
                    video_urls.reverse()  # Sort from newest to oldest
                write(' '.join([str(rec), str(oldest), str(delay), str(video_urls)]))
                return video_urls
            else:
                # This is a single video
                return [info['webpage_url']]
    except Exception as e:
        write(delay + ' ' + e)
        time.sleep(delay)
        delay *= 2
        get_youtube_videos(url, False)
def get_playlist(current_url):
    # Check if the URL includes "youtube.com/watch?v="
    if "youtube.com/watch?v=" in current_url:
        # Parse the URL
        url = urllib.parse.urlparse(current_url)
        
        # Update the query parameters
        query_params = urllib.parse.parse_qs(url.query)
        query_params["list"] = ["ULcxqQ59vzyTk"]
        
        # Rebuild the URL with the updated query parameters
        updated_url = urllib.parse.urlunparse((
            url.scheme,
            url.netloc,
            url.path,
            url.params,
            urllib.parse.urlencode(query_params, doseq=True),
            url.fragment
        ))
        return updated_url
    return '[]'

def get_video_id(url):
    """
    Extracts the YouTube video ID from a given URL.
    """
    # Define a regular expression pattern to match the video ID
    pattern = r'(?:https?://)?(?:www\.)?(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|v/|user/\S+|[^/]+\?v=))([^&"\'<>\s]+)'
    
    # Use the pattern to search for the video ID in the URL
    match = re.search(pattern, url)
    write(match)
    if match:
        return match.group(1)
    else:
        return None
def create_redirect_html_file(filename, url):
  """Creates an HTML file with a meta refresh tag to redirect to the specified URL.

  Args:
    filename: The name of the HTML file to create.
    url: The URL to redirect to.
  """
  write(filename)
  with open(filename, "w", encoding='utf-8') as f:
    f.write(f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta http-equiv="refresh" content="0; URL='{url}'" />
    </head>
    <body>
    </body>
    </html>
    """)
def generate(url, i = 0):
    global history_file, progress_file, model_name
    
    # Set CPU-specific settings
    os.environ['OMP_NUM_THREADS'] = '8'  # Use more CPU threads
    os.environ['KMP_BLOCKTIME'] = '1'
    os.environ['KMP_AFFINITY'] = 'granularity=fine,compact,1,0'
    
    # Start with CPU for large models
    if any(large_model in model_name for large_model in ['large', 'medium']):
        device = 'cpu'
        compute = 'int8'
        write(f"Using CPU for {model_name} model")
    
    url = remove_time_param(url)
    id = get_video_id(url)
    write(url, id)
    
    # Start with smaller model
    original_model = model_name
    model_name = "small"  # Start with small model
    
    try:
        history = open(history_file, "r", encoding='utf-8').readlines()
        for h in history:
            sep = h.replace('\n','').split(' ')
            if sep[0] == id:
                if sep[1] >= model.getIndex(model_name):
                    continue
    except Exception as e:
        write(e)    
    # Download the audio
    try:
        audio_file = download_audio(url, False, start_time)
        progress_file = progress_file.replace("___", video_title)
        rename(progress_file, True)
        if audio_file is None:
            raise FileNotFoundError("No audio file, subtitles may be available")
        # Transcribe the audio
        # Create the SRT file
        srt_dir = os.path.join(os.path.expanduser("~"), subs_dir)
        # Create a folder for the channel name
        folder_name = os.path.join(srt_dir, channel_name)
        os.makedirs(folder_name, exist_ok=True)
        name = os.path.splitext(os.path.basename(audio_file))[0]
        srt_file = os.path.join(folder_name, name + ".srt")
        segments = 'segments-0.json'
        cd = os.getcwd()
        s = 0
        while os.path.exists(os.path.join(ytsubs, segments)):
            segments = f'segments-{s}.json'
            s += 1
        segments = os.path.join(ytsubs, segments)
        
        # Try with small model first
        try:
            transcribe.process_create(audio_file, model_name, srt_file, segments, write=write)
        except Exception as e:
            if "CUDA out of memory" in str(e):
                # Fall back to CPU
                write("Falling back to CPU due to memory issues")
                transcribe.process_create(audio_file, model_name, srt_file, segments, device='cpu', write=write)
            else:
                raise e
                
        # If successful with small model, try with original model
        if original_model != model_name:
            try:
                model_name = original_model
                transcribe.process_create(audio_file, model_name, srt_file, segments, write=write)
            except:
                # If fails, keep using small model
                model_name = "small"
                write("Could not use larger model, keeping small model results")
        
        # Delete the audio file
        os.remove(audio_file)
    except Exception as e:
        write(f"Error: {e}")
        return
    
    # Get the path to the subtitle file
    sub_file = srt_file.replace("\\", "/")

    # Open the video and subtitle file with MPV
    mpv = ["mpv", url, "--pause", f'--sub-file="{sub_file}"']

    current_time = datetime.datetime.now()
    current_hour = current_time.hour

    #if 12 <= current_hour < 18:
        #subprocess.Popen(mpv)
    mpv = ' '.join(mpv)
    pyperclip.copy(mpv)
    create_redirect_html_file(os.path.join(folder_name, name + ".htm"), url)
    bat = os.path.join(folder_name, name + ".bat")
    write(bat)
    with open(file=bat, mode='w', encoding="utf-8") as f:
        try:
            f.write(mpv)
        except UnicodeEncodeError:
            write(f"Warning: Could not write all characters to the file. Skipping problematic characters.")
            f.write(mpv.encode('ascii', 'ignore').decode('ascii'))
    with open(file=history_file, mode='a', encoding="utf-8") as f:
        try:
            f.write(id + ' ' + model_name + '\n')
        except UnicodeEncodeError:
            write(f"Warning: Could not write all characters to the file. Skipping problematic characters.")
            f.write('\n' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ' : ' + mpv.encode('ascii', 'ignore').decode('ascii'))
    write(f'{i}: {name} {url}', mpv)

class YoutubeSubs:
    def __init__(self, model_name='base', device='cuda', compute='int8_float32', force_device=False, subs_dir=None, enable_logging=True):
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
        
        # Setup directories
        self.subs_dir = subs_dir or os.path.join("Documents", "Youtube-Subs")
        self.ytsubs = os.path.join(os.path.expanduser("~"), self.subs_dir)
        os.makedirs(self.ytsubs, exist_ok=True)
        
        # Setup logging
        self.start = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        self.progress_name = f'progress-{self.start}'
        self.progress_file = os.path.join(self.ytsubs, f'{self.progress_name}.log')
        self.history_file = os.path.join(self.ytsubs, 'history.txt')

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

    def download_audio(self, url, rec=False):
        """Download audio from YouTube URL"""
        if not rec or self.delay > 3600:
            self.delay = self.start_delay
            
        try:
            ydl_opts = {
                'outtmpl': '%(title)s.%(ext)s',
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'cookies': 'media/cookies.txt',
                'ignoreerrors': True
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Check for existing subtitles
                try:
                    if info['subtitles'] != {}:
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
                audio_file = os.path.join(os.getcwd(), f"{self.video_title}.{self.model_name}.mp3")

                self.write(' '.join([str(self.delay), self.channel_name, str(timestamp), 
                                   str(date_time), self.video_title, audio_file]))

            # Add time range to ffmpeg command if specified
            command = ["yt-dlp", "--extract-audio", "--audio-format", "mp3"]
            
            if self.start_time or self.end_time:
                time_args = []
                if self.start_time:
                    time_args.extend(["-ss", self.start_time])
                if self.end_time:
                    time_args.extend(["-to", self.end_time])
                command.extend(["--postprocessor-args", f"ffmpeg: {' '.join(time_args)}"])
            
            command.extend(["-o", audio_file, url])
            
            # Download audio
            subprocess.run(command, check=True)
            return audio_file

        except Exception as e:
            self.delay *= 2
            self.write(self.delay, str(e))
            time.sleep(self.delay)
            return self.download_audio(url, True)

    def get_youtube_videos(self, url, rec=False):
        """Get list of video URLs from channel/playlist"""
        if not rec or self.delay > 3600:
            self.delay = self.start_delay
            
        try:
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': '%(title)s.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,            
                'cookies': 'media/cookies.txt'
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    video_urls = []
                    for entry in info['entries']:
                        try:
                            if entry['subtitles'] == {}:
                                video_urls.append(entry['webpage_url'])
                        except Exception as err:
                            self.write(str(err))
                    return video_urls
                else:
                    return [info['webpage_url']]
                    
        except Exception as e:
            self.write(f"{self.delay} {str(e)}")
            time.sleep(self.delay)
            self.delay *= 2
            return self.get_youtube_videos(url, True)

    def create_helper_files(self, folder_name, name, url):
        """Create helper files (HTML redirect, batch file)"""
        # Create HTML redirect
        html_file = os.path.join(folder_name, f"{name}.htm")
        with open(html_file, "w", encoding='utf-8') as f:
            f.write(f"""
            <!DOCTYPE html>
            <html>
            <head>
              <meta http-equiv="refresh" content="0; URL='{url}'" />
            </head>
            <body>
            </body>
            </html>
            """)

        # Create MPV batch file
        sub_file = os.path.join(folder_name, f"{name}.srt").replace("\\", "/")
        mpv_command = f'mpv "{url}" --pause --sub-file="{sub_file}"'
        bat_file = os.path.join(folder_name, f"{name}.bat")
        
        with open(bat_file, 'w', encoding="utf-8") as f:
            try:
                f.write(mpv_command)
            except UnicodeEncodeError:
                self.write("Warning: Could not write all characters to batch file")
                f.write(mpv_command.encode('ascii', 'ignore').decode('ascii'))

        # Copy MPV command to clipboard
        pyperclip.copy(mpv_command)

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

    def process_urls(self, urls_text, callback=print):
        """Process multiple URLs from text input"""
        urls = urls_text.replace('\r','').split('\n')
        urls = [url.strip() for url in urls if 'youtu' in url.strip()]
        
        for i, url in enumerate(urls):
            try:
                callback(f"Processing {i+1}/{len(urls)}: {url}")
                if '@' in url:
                    # Handle channel/playlist
                    video_urls = self.get_youtube_videos(url)
                    for j, video_url in enumerate(video_urls):
                        callback(f"Processing video {j+1}/{len(video_urls)} from channel")
                        self.process_single_url(video_url, callback)
                else:
                    # Handle single video
                    self.process_single_url(url, callback)
            except Exception as e:
                callback(f"Error processing {url}: {str(e)}")

    def process_single_url(self, url, callback=print):
        """Process a single YouTube URL"""
        try:
            url = self.remove_time_param(url)
            video_id = self.get_video_id(url)
            
            # Download and process audio
            audio_file = self.download_audio(url)
            if audio_file is None:
                raise FileNotFoundError("No audio file, subtitles may be available")

            # Setup output paths - ensure using Documents/Youtube-Subs
            folder_name = os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs", self.channel_name)
            os.makedirs(folder_name, exist_ok=True)
            
            name = os.path.splitext(os.path.basename(audio_file))[0]
            srt_file = os.path.join(folder_name, name + ".srt")
            
            # Transcribe
            success = transcribe.process_create(
                file=audio_file, 
                model_name=self.model_name,
                srt_file=srt_file,
                language=None,
                device=self.device,
                compute_type=self.compute,
                force_device=self.force_device,
                write=callback
            )

            if success:
                # Create helper files
                self.create_helper_files(folder_name, name, url)
                # Update history
                self.update_history(video_id)
                
            # Cleanup
            if os.path.exists(audio_file):
                os.remove(audio_file)
            
        except Exception as e:
            callback(f"Error: {str(e)}")

if __name__ == "__main__":
    # Example usage
    yt = YoutubeSubs(model_name="small", device="cpu")
    urls = pyperclip.paste().replace('\r','').split('\n')
    yt.process_urls('\n'.join(urls))
