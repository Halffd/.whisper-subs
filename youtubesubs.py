import sys
import model
default = 'base'
model_name = model.getName(sys.argv, default)
 
import os
import pyperclip
import subprocess
import faster_whisper
import torch
import yt_dlp
import logging
import re
import datetime

channel_name = 'unknown'
subs_dir = "Documents\\Youtube-Subs"
logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)
def transcribe_audio(audio_file, model_name):
    """
    Transcribes the audio from the given file using the specified Whisper model.

    Args:
        audio_file (str): Path to the audio file.
        model_name (str): The name of the Whisper model to use.

    Returns:
        The transcription result.
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = faster_whisper.WhisperModel(model_name, device=device, compute_type="int16")
    segments, info = model.transcribe(audio_file,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500,max_speech_duration_s=8000))
    return segments

def format_timestamp(timestamp):
    """
    Formats a timestamp in seconds to the HH:MM:SS.xxx format.

    Args:
        timestamp (float): The timestamp in seconds.

    Returns:
        The formatted timestamp.
    """
    hours = int(timestamp // 3600)
    minutes = int(timestamp % 3600 // 60)
    seconds = timestamp % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
def clean_filename(filename):
    # Remove leading/trailing spaces
    filename = filename.strip()
    
    # Remove leading/trailing periods
    filename = filename.strip('.')
    
    # Replace multiple consecutive periods with a single period
    filename = re.sub(r'\.+', '.', filename)
        
    # Remove other special characters
    cleaned_filename = re.sub(r"[<>!@#$%^&*(),/'?\"-;:\[\]\{\}|\\]", "", filename)
    
    return cleaned_filename
def download_audio(url):
    global model_name, channel_name
    ydl_opts = {
        'outtmpl': '%(title)s.%(ext)s',
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        video_title = clean_filename(info.get('title', 'unknown'))
        # Get the channel name
        channel_name = info.get('channel', '')

        #video_title = info.get('title', 'unknown')
        audio_file = os.path.join(os.getcwd(), f"{video_title}.{model_name}.mp3")
    command = ["yt-dlp", "--extract-audio", "--audio-format", "mp3", "-o", audio_file, url]
    subprocess.run(command, check=True)

    return audio_file
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
    return new_url
def get_youtube_videos(url):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': '%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if 'entries' in info:
            # This is a playlist
            video_urls = [entry['webpage_url'] for entry in info['entries']]
            video_urls.reverse()  # Sort from newest to oldest
            return video_urls
        else:
            # This is a single video
            return [info['webpage_url']]
if __name__ == "__main__":
    # Get the YouTube URL from the clipboard
    url = pyperclip.paste()
    if '@' in url:
        urls = get_youtube_videos(url)
    else:
        urls = url.replace('\r','').split('\n')
    print(urls)
    for i, url in enumerate(urls):
        try:
            url = remove_time_param(url)
            print(f"Downloading {i+1}/{len(urls)}: {url}")
            # Download the audio
            try:
                audio_file = download_audio(url)

                # Transcribe the audio
                segments = transcribe_audio(audio_file, model_name)
            except Exception as e:
                print(f"Error: {e}")
                continue
            # Create the SRT file
            srt_dir = os.path.join(os.path.expanduser("~"), subs_dir)
            os.makedirs(srt_dir, exist_ok=True)
            # Create a folder for the channel name
            folder_name = os.path.join(srt_dir, channel_name)
            if not os.path.exists(folder_name):
                os.makedirs(folder_name)    
            srt_file = os.path.join(folder_name, os.path.splitext(os.path.basename(audio_file))[0] + ".srt")
            with open(srt_file, "w", encoding="utf-8") as f:
                for i, segment in enumerate(segments, start=1):
                    start_time = segment.start
                    end_time = segment.end
                    text = segment.text.strip()
                    f.write(f"{i}\n")
                    f.write(f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}\n")
                    f.write(f"{text}\n\n")
            print(f"SRT file saved: {srt_file}")

            # Delete the audio file
            os.remove(audio_file)
            
            # Get the path to the subtitle file
            sub_file = srt_file.replace("\\", "/")

            # Open the video and subtitle file with MPV
            mpv = ["mpv", url, "--pause", f'--sub-file="{sub_file}"']

            current_time = datetime.datetime.now()
            current_hour = current_time.hour

            #if 12 <= current_hour < 18:
                #subprocess.Popen(mpv)
            mpv = ' '.join(mpv)
            print(mpv)
            pyperclip.copy(mpv)
            bat = os.path.join(folder_name, os.path.splitext(os.path.basename(audio_file))[0] + ".bat")
            with open(file=bat, mode='w', encoding="utf-8") as f:
                try:
                    f.write(mpv)
                except UnicodeEncodeError:
                    print(f"Warning: Could not write all characters to the file. Skipping problematic characters.")
                    f.write(mpv.encode('ascii', 'ignore').decode('ascii'))
            with open(file='mpvs.txt', mode='a', encoding="utf-8") as f:
                try:
                    f.write('\n' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ' : ' + mpv)
                except UnicodeEncodeError:
                    print(f"Warning: Could not write all characters to the file. Skipping problematic characters.")
                    f.write('\n' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S') + ' : ' + mpv.encode('ascii', 'ignore').decode('ascii'))
        except Exception as e:
            print(f"Error : {e}")                    
