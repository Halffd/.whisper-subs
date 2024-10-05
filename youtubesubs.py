import sys
import model
default = 'base'
device = 'cuda'
if 'cpu' in sys.argv:
    device = 'cpu'
model_name = model.getName(sys.argv, default)


import pyperclip
url = pyperclip.paste()
print(url)
urls = url.replace('\r','').split('\n')
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
subs_dir = "Documents\\Youtube-Subs"
log_dir = "Documents"
oldest = '--oldest' in sys.argv
delay = 30
start_delay = delay

ytsubs =  os.path.join(os.path.expanduser("~"), subs_dir)
start = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
progress_name = f'progress-{start}'
progress_file = os.path.join(ytsubs, f'{progress_name}.log')
history_file = os.path.join(ytsubs, 'history.txt')

def rename(name, repl = False):
    global progress_file, progress_name
    try:
        vprogress_name = name if repl else f'progress-{name}'
        new = os.path.join(ytsubs, f'{progress_name}.log')
        if os.path.exists(progress_file):
            os.rename(progress_file, new)
        progress_file = new
    except Exception as e:
        write(e)
def write(text, mpv = 'err'):
    global progress_file
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
    cleaned_filename = re.sub(r"[<>!@#$%^&*(),/'?\"\-;:\[\]\{\}|\\]", "", filename)
    if cleaned_filename[-1] == ".":
        cleaned_filename = cleaned_filename[:-1]
    write(cleaned_filename)
    return cleaned_filename
def download_audio(url, rec = False):
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
            write(info)
            if info['subtitles'] != {}:
                if not('live_chat' in info['subtitles'] and len(info['subtitles']) < 2):
                    return None
                elif any(lang in info['subtitles'] for lang in ['en', 'pt', 'pt-BR']):
                    return None
            # Get the channel name
            channel_name = info.get('channel', '')
            timestamp = info.get('timestamp', '')
            # Convert the timestamp to a datetime object
            date_time = datetime.datetime.fromtimestamp(timestamp)

            # Format the datetime object as a date string
            timeday = date_time.strftime('%Y-%m-%d')
            video_title = timeday + '_' + clean_filename(info.get('title', 'unknown'))
            #video_title = info.get('title', 'unknown')
            audio_file = os.path.join(os.getcwd(), f"{video_title}.{model_name}.mp3")
            write(' '.join([str(delay), channel_name, str(timestamp), str(date_time), video_title, audio_file]))
        command = ["yt-dlp", "--extract-audio", "--audio-format", "mp3", "-o", audio_file, url]
        subprocess.run(command, check=True)

        return audio_file
    except Exception as e:
        delay *= 2
        write(delay, e)
        time.sleep(delay)
        download_audio(url, True)
def remove_time_param(url):
    """
    Removes the '&t=' parameter from a given URL.
    
    Args:
        url (str): The URL to be processed.
        
    Returns:
        str: The modified URL with the '&t=' parameter removed.
    """
    t_index = url.find('&t=')
    if t_index == -1:
        return url
    
    end_index = lambda x: url.find('&', x + 1) if x != -1 else len(url)
    new_url = url[:t_index] + url[end_index(t_index):]
    write(url + ' = ' + new_url)
    return new_url
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
            write(info)
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
  with open(filename, "w") as f:
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
    global history_file, progress_file
    url = remove_time_param(url)
    id = get_video_id(url)
    write(url, id)
    try:
        history = open(history_file, "r").readlines()
        for h in history:
            sep = h.replace('\n','').split(' ')
            if sep[0] == id and sep[1] == model_name:
                continue
    except Exception as e:
        write(e)    
    # Download the audio
    try:
        audio_file = download_audio(url)
        progress_file = progress_file.replace("___", video_title)
        rename(progress_file, True)
        if audio_file is None:
            raise FileNotFoundError("No audio file, subtitles may be available")
        # Transcribe the audio
        # Create the SRT file
        srt_dir = os.path.join(os.path.expanduser("~"), subs_dir)
        # Create a folder for the channel name
        folder_name = os.path.join(srt_dir, channel_name)
        name = os.path.splitext(os.path.basename(audio_file))[0]
        srt_file = os.path.join(folder_name, name + ".srt")
        segments = transcribe.process_create(audio_file, model_name, write=write)
        #transcribe_audio(audio_file, model_name)
        srt_dir = os.path.join(os.path.expanduser("~"), subs_dir)
        os.makedirs(srt_dir, exist_ok=True)
        # Create a folder for the channel name
        folder_name = os.path.join(srt_dir, channel_name)
        if not os.path.exists(folder_name):
            os.makedirs(folder_name)    
        name = os.path.splitext(os.path.basename(audio_file))[0]
        srt_file = os.path.join(folder_name, name + ".srt")
        with open(srt_file, "w", encoding="utf-8") as f:
            for i, segment in enumerate(segments, start=1):
                start_time = segment.start
                end_time = segment.end
                text = segment.text.strip()
                f.write(f"{i}\n")
                f.write(f"{transcribe.format_timestamp(start_time)} --> {transcribe.format_timestamp(end_time)}\n")
                f.write(f"{text}\n\n")
        write(f"SRT file saved: {srt_file}")

        #transcribe_audio(audio_file, model_name)
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
if __name__ == "__main__":
    # Get the YouTube URL from the clipboard
    for i, url in enumerate(urls):
        try:
            rename(f'{str(i)}-___-{start}')
            if not 'youtu' in url:
                continue
            if '@' in url:
                urls2 = get_youtube_videos(url)
                write(urls2, len(urls2))
                for j, u in enumerate(urls):
                    rename(f'{str(i)}-{str(j)}-{url.split('/')[-1][1:]}-___-{start}')
                    write(f"Downloading {i+1}/{j+1}/{len(urls2)}/{len(urls)}: {u}")
                    generate(u)
            else:
                write(f"Downloading {i+1}/{len(urls)}: {url}")
                generate(url)            
        except Exception as e:
            write(f"Error : {e}")                    
