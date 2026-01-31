import os
import sys
import datetime
import subprocess
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gdk, Gio
import threading
import pymkv
import transcribe
import time
from youtubesubs import YoutubeSubs
import pyperclip

# Initialize GTK
if not Gtk.init_check()[0]:
    print("Unable to initialize GTK. Make sure you have a display server running.")
    sys.exit(1)

MODEL_NAMES = [
    "distil-whisper/distil-large-v2",  # Distilled version of large-v2
    "distil-whisper/distil-medium.en",  # English-only models
    "Systran/faster-distil-large-v2",  # Optimized for CPU
    "small", "medium",  # Original Whisper models
    "large-v2", "large-v3"  # For CPU-only use
]

class TranscriptionThread(threading.Thread):
    def __init__(self, files_to_process, model_name, log_callback, youtube_urls=None, youtube_subs=None):
        super().__init__()
        self.files_to_process = files_to_process
        self.model_name = model_name
        self.log_callback = log_callback
        self.youtube_urls = youtube_urls
        self.youtube_subs = youtube_subs
        self.daemon = True

    def run(self):
        try:
            # Process YouTube URLs if any
            if self.youtube_urls and self.youtube_subs:
                self.youtube_subs.process_urls(self.youtube_urls, self.log_callback)
                
            # Process local files if any
            for i, file_path in enumerate(self.files_to_process, 1):
                GLib.idle_add(self.log_callback, f"Processing file {i}/{len(self.files_to_process)}: {file_path}")
                
                if file_path.lower().endswith('.mkv'):
                    file_path = self.convertMKVtoMP3(file_path)
                    if not file_path:
                        GLib.idle_add(self.log_callback, f"Failed to convert {file_path}")
                        continue
                    
                if file_path:
                    self.processFile(file_path, self.model_name)
            
            GLib.idle_add(self.log_callback, "Transcription completed!")
        except Exception as e:
            GLib.idle_add(self.log_callback, f"Error: {str(e)}")

    def convertMKVtoMP3(self, mkv_path):
        output_mp3 = os.path.splitext(mkv_path)[0] + ".mp3"
        try:
            mkv = pymkv.MKVFile(mkv_path)
            
            # Try to find Japanese audio track first, then undefined, then any audio track
            audio_track_id = next(
                (track.track_id for track in mkv.tracks 
                 if track.track_type == 'audio' and track.language in ['jpn', 'und']),
                next(
                    (track.track_id for track in mkv.tracks if track.track_type == 'audio'),
                    None
                )
            )

            if audio_track_id is None:
                raise ValueError("No audio tracks found")

            command = [
                "ffmpeg", "-y", "-i", mkv_path,
                "-map", f"0:{audio_track_id}",
                "-c:a", "libmp3lame",
                output_mp3
            ]
            
            subprocess.run(command, check=True)
            GLib.idle_add(self.log_callback, f"Converted {mkv_path} to {output_mp3}")
            return output_mp3
            
        except Exception as e:
            GLib.idle_add(self.log_callback, f"Error converting {mkv_path}: {str(e)}")
            return None

    def processFile(self, file_path, model_name):
        try:
            dir_path = os.path.dirname(file_path)
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            
            # Extract video ID from HTML file if it exists
            html_file = os.path.join(dir_path, f"{base_name}.htm")
            video_id = None
            if os.path.exists(html_file):
                try:
                    with open(html_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        import re
                        match = re.search(r'watch\?v=([^&"\'\s]+)', content)
                        if match:
                            video_id = match.group(1)
                except Exception as e:
                    GLib.idle_add(self.log_callback, f"Error reading HTML file: {str(e)}")

            # Create filenames with video ID if available
            file_suffix = f"_{video_id}" if video_id else ""
            srt_file = os.path.join(dir_path, f"{base_name}{file_suffix}.{model_name}.srt")
            log_file = os.path.join(dir_path, f"{base_name}{file_suffix}.{model_name}.log")
            
            # Get device and compute settings from the UI
            device = 'cuda' if self.gpu_radio.get_active() else 'cpu'
            compute_type = self.compute_combo.get_active_text().split(' ')[0]
            
            # Create script content
            script_content = f'''
import faster_whisper
import os
import sys
import threading
import queue
import time
import logging
logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)

# Set device and compute type from parameters
device = "{device}"
compute_type = "{compute_type}"

def format_timestamp(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds % 1) * 1000)
    seconds = int(seconds)
    return f"{{hours:02d}}:{{minutes:02d}}:{{seconds:02d}},{{milliseconds:03d}}"

# Setup logging with immediate flush
log_file = r"{log_file}"
def log_message(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{{timestamp}}] {{msg}}\\n")
        f.flush()  # Ensure immediate write
    print(msg)

# Create unfinished srt file with immediate writing
unfinished_srt = r"{srt_file}.unfinished.srt"
segment_queue = queue.Queue(maxsize=100)  # Limit queue size to manage memory
write_event = threading.Event()
stop_event = threading.Event()

def write_segments():
    current_index = 1
    with open(unfinished_srt, "w", encoding="utf-8") as f:
        while not stop_event.is_set() or not segment_queue.empty():
            try:
                # Wait for new segments with timeout
                segment = segment_queue.get(timeout=0.5)
                start_time = format_timestamp(segment.start)
                end_time = format_timestamp(segment.end)
                
                # Write segment immediately
                f.write(f"{{current_index}}\\n")
                f.write(f"{{start_time}} --> {{end_time}}\\n")
                f.write(f"{{segment.text.strip()}}\\n\\n")
                f.flush()  # Force write to disk
                
                current_index += 1
                segment_queue.task_done()
                write_event.set()  # Signal that we wrote something
                
                if current_index % 10 == 0:
                    log_message(f"Written {{current_index}} segments")
                    
            except queue.Empty:
                continue
            except Exception as e:
                log_message(f"Error writing segment: {{e}}")

# Start writer thread
writer_thread = threading.Thread(target=write_segments, daemon=True)
writer_thread.start()

try:
    log_message("Starting transcription...")
    model = faster_whisper.WhisperModel("{model_name}", device=device, compute_type=compute_type)
    
    # Process segments as they come
    segments, info = model.transcribe(r"{file_path}")
    
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
    writer_thread.join(timeout=30)  # Wait up to 30 seconds
    
    if os.path.exists(unfinished_srt) and os.path.getsize(unfinished_srt) > 10:
        if os.path.exists(r"{srt_file}"):
            os.remove(r"{srt_file}")
        os.rename(unfinished_srt, r"{srt_file}")
        log_message("Transcription completed successfully")
        
        # Create helper files
        dir_path = os.path.dirname(r"{srt_file}")
        base_name = os.path.splitext(os.path.basename(r"{srt_file}"))[0]
        
        # Try to find corresponding HTML file to get URL
        html_file = os.path.join(dir_path, f"{base_name}.htm")
        url = None
        if os.path.exists(html_file):
            try:
                with open(html_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    import re
                    match = re.search(r'URL=\'([^\']+)\'', content)
                    if match:
                        url = match.group(1)
            except:
                pass
                
        if url:
            create_helper_files(dir_path, os.path.join(dir_path, f"{base_name}.srt"), url)
            
        return True
    else:
        log_message("Output file is empty or too small")
        exit(1)
        
except Exception as e:
    log_message(f"Error during transcription: {{str(e)}}")
    import traceback
    traceback.print_exc(file=sys.stderr)
    exit(1)
finally:
    stop_event.set()  # Ensure writer thread stops
    writer_thread.join(timeout=5)  # Give it 5 seconds to finish
'''
            
            # Create shell script for Linux
            sh_file = os.path.join(dir_path, f"{base_name}{file_suffix}.{model_name}.sh")
            with open(sh_file, 'w', encoding='utf-8') as f:
                f.write('#!/bin/bash\n')
                f.write(f'python3 -c """{script_content}"""\n')
            os.chmod(sh_file, 0o755)  # Make executable
            
            # Create batch file for Windows
            bat_file = os.path.join(dir_path, f"{base_name}{file_suffix}.{model_name}.bat")
            with open(bat_file, 'w', encoding='utf-8') as f:
                # Convert paths to Windows format
                win_script = script_content.replace('/', '\\')
                win_script = win_script.replace(r'\\', r'\\\\')  # Escape backslashes
                if win_script.startswith(r'\home'):
                    win_script = 'C:\\Users' + win_script[5:]
                f.write('@echo off\n')
                f.write(f'python -c """{win_script}"""\n')
            
            # Write script to temporary file and run
            script_file = os.path.join(dir_path, f"temp_whisper_{os.getpid()}.py")
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(script_content)
            
            try:
                GLib.idle_add(self.log_callback, f"Starting transcription of {file_path}...")
                process = subprocess.Popen(
                    [sys.executable, script_file],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    encoding='utf-8',
                    errors='replace',
                    text=True
                )

                while process.poll() is None:
                    stdout = process.stdout.readline()
                    if stdout:
                        GLib.idle_add(self.log_callback, stdout.strip())
                    stderr = process.stderr.readline()
                    if stderr:
                        GLib.idle_add(self.log_callback, f"Error: {stderr.strip()}")
                    time.sleep(0.1)
                
                exit_code = process.returncode
                if exit_code == 0 and os.path.exists(srt_file):
                    GLib.idle_add(self.log_callback, f"Successfully created {srt_file}")
                    
                    # Create helper files
                    dir_path = os.path.dirname(srt_file)
                    base_name = os.path.splitext(os.path.basename(srt_file))[0]
                    
                    # Try to find corresponding HTML file to get URL
                    html_file = os.path.join(dir_path, f"{base_name}.htm")
                    url = None
                    if os.path.exists(html_file):
                        try:
                            with open(html_file, 'r', encoding='utf-8') as f:
                                content = f.read()
                                import re
                                match = re.search(r'URL=\'([^\']+)\'', content)
                                if match:
                                    url = match.group(1)
                        except:
                            pass
                        
                    if url:
                        create_helper_files(dir_path, base_name, url)
                    
                    return True
                
                GLib.idle_add(self.log_callback, f"Process exited with code {exit_code}")
                return False
                
            finally:
                try:
                    os.remove(script_file)
                except:
                    pass
            
        except Exception as e:
            GLib.idle_add(self.log_callback, f"Error processing {file_path}: {str(e)}")
            return False

class TranscriptionApp(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.log_file = None
        self.selected_files = []
        self.selected_directory = None
        self.youtube_subs = None
        self.last_clipboard = ""
        self.clipboard_monitoring = True
        self.force_device = False
        
        self.setup_ui()
        
        # Setup clipboard monitoring
        GLib.timeout_add(1000, self.check_clipboard)

    def setup_ui(self):
        self.set_title("Transcription App")
        self.set_default_size(800, 600)
        
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_child(main_box)
        
        # Clipboard monitoring section
        clipboard_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.clipboard_toggle = Gtk.ToggleButton(label="Clipboard Monitoring: ON")
        self.clipboard_toggle.set_active(True)
        self.clipboard_toggle.connect("toggled", self.on_clipboard_toggle)
        clipboard_box.append(self.clipboard_toggle)
        
        clear_urls_button = Gtk.Button(label="Clear URLs")
        clear_urls_button.connect("clicked", self.on_clear_urls)
        clipboard_box.append(clear_urls_button)
        
        main_box.append(clipboard_box)
        
        # Options section
        options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        
        # Sort options
        sort_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.sort_oldest_check = Gtk.CheckButton(label="Sort by Oldest")
        self.sort_oldest_check.connect("toggled", self.resort_urls)
        sort_box.append(self.sort_oldest_check)
        
        self.reverse_order_check = Gtk.CheckButton(label="Reverse Order")
        self.reverse_order_check.connect("toggled", self.resort_urls)
        sort_box.append(self.reverse_order_check)
        
        options_box.append(sort_box)
        
        # Time range
        time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        time_box.append(Gtk.Label(label="Start Time:"))
        self.start_time = Gtk.Entry()
        self.start_time.set_placeholder_text("HH:MM:SS")
        time_box.append(self.start_time)
        
        time_box.append(Gtk.Label(label="End Time:"))
        self.end_time = Gtk.Entry()
        self.end_time.set_placeholder_text("HH:MM:SS")
        time_box.append(self.end_time)
        
        options_box.append(time_box)
        
        # Enable logging
        self.enable_logging_check = Gtk.CheckButton(label="Enable File Logging")
        self.enable_logging_check.set_active(True)
        options_box.append(self.enable_logging_check)
        
        main_box.append(options_box)
        
        # Model selection
        model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        model_box.append(Gtk.Label(label="Model:"))
        
        self.model_combo = Gtk.DropDown()
        model_store = Gtk.StringList()
        for model in MODEL_NAMES:
            model_store.append(model)
        self.model_combo.set_model(model_store)
        model_box.append(self.model_combo)
        
        main_box.append(model_box)
        
        # Device selection
        device_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        device_label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        device_label_box.append(Gtk.Label(label="Processing Device:"))
        
        self.gpu_radio = Gtk.CheckButton(label="GPU (CUDA)")
        self.gpu_radio.set_active(True)
        self.cpu_radio = Gtk.CheckButton(label="CPU")
        self.cpu_radio.set_group(self.gpu_radio)
        
        device_radio_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        device_radio_box.append(self.gpu_radio)
        device_radio_box.append(self.cpu_radio)
        device_label_box.append(device_radio_box)
        
        self.force_device_check = Gtk.CheckButton(label="Force Device (Don't Auto-Switch)")
        device_label_box.append(self.force_device_check)
        
        device_box.append(device_label_box)
        
        # Compute type selection
        compute_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        compute_box.append(Gtk.Label(label="Compute Type:"))
        
        self.compute_combo = Gtk.DropDown()
        compute_store = Gtk.StringList()
        compute_types = [
            "int8_float32 (Balanced)",
            "int8 (Fast/Low Memory)",
            "float16 (GPU Only)",
            "float32 (High Accuracy)"
        ]
        for compute_type in compute_types:
            compute_store.append(compute_type)
        self.compute_combo.set_model(compute_store)
        compute_box.append(self.compute_combo)
        
        device_box.append(compute_box)
        main_box.append(device_box)
        
        # YouTube URLs
        main_box.append(Gtk.Label(label="YouTube URLs (one per line):"))
        self.url_count_label = Gtk.Label(label="0 URLs")
        main_box.append(self.url_count_label)
        
        self.youtube_input = Gtk.TextView()
        self.youtube_input.set_wrap_mode(Gtk.WrapMode.WORD)
        self.youtube_input.get_buffer().connect("changed", self.update_url_count)
        
        youtube_scroll = Gtk.ScrolledWindow()
        youtube_scroll.set_vexpand(True)
        youtube_scroll.set_child(self.youtube_input)
        main_box.append(youtube_scroll)
        
        # File selection
        file_button = Gtk.Button(label="Select Audio Files")
        file_button.connect("clicked", self.on_file_button_clicked)
        main_box.append(file_button)
        
        self.file_label = Gtk.Label(label="Selected files: None")
        main_box.append(self.file_label)
        
        # Directory selection
        dir_button = Gtk.Button(label="Select Directory")
        dir_button.connect("clicked", self.on_dir_button_clicked)
        main_box.append(dir_button)
        
        self.dir_label = Gtk.Label(label="Selected directory: None")
        main_box.append(self.dir_label)
        
        # Run button
        self.run_button = Gtk.Button(label="Run Transcription")
        self.run_button.connect("clicked", self.on_run_button_clicked)
        main_box.append(self.run_button)
        
        # Log output
        main_box.append(Gtk.Label(label="Log Output:"))
        
        self.log_output = Gtk.TextView()
        self.log_output.set_editable(False)
        self.log_output.set_wrap_mode(Gtk.WrapMode.WORD)
        
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_vexpand(True)
        log_scroll.set_child(self.log_output)
        main_box.append(log_scroll)

    def on_clipboard_toggle(self, button):
        self.clipboard_monitoring = button.get_active()
        button.set_label(f'Clipboard Monitoring: {"ON" if self.clipboard_monitoring else "OFF"}')

    def on_clear_urls(self, button):
        buffer = self.youtube_input.get_buffer()
        buffer.set_text("", 0)
        self.update_url_count()

    def on_file_button_clicked(self, button):
        dialog = Gtk.FileChooserDialog(
            title="Select Audio Files",
            parent=self,
            action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Open", Gtk.ResponseType.ACCEPT
        )
        dialog.set_select_multiple(True)
        
        filter_audio = Gtk.FileFilter()
        filter_audio.set_name("Audio files")
        filter_audio.add_pattern("*.mkv")
        filter_audio.add_pattern("*.mp3")
        filter_audio.add_pattern("*.wav")
        filter_audio.add_pattern("*.flac")
        filter_audio.add_pattern("*.ogg")
        dialog.add_filter(filter_audio)
        
        response = dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            self.selected_files = dialog.get_filenames()
            self.file_label.set_text(f"Selected files: {len(self.selected_files)} files")
            
            if not self.log_file and self.selected_files:
                self.log_file = os.path.splitext(self.selected_files[0])[0] + '.log'
        
        dialog.destroy()

    def on_dir_button_clicked(self, button):
        dialog = Gtk.FileChooserDialog(
            title="Select Directory",
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Open", Gtk.ResponseType.ACCEPT
        )
        
        response = dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            self.selected_directory = dialog.get_filename()
            self.dir_label.set_text(f"Selected directory: {self.selected_directory}")
            
            if not self.log_file:
                self.log_file = os.path.join(self.selected_directory, 'transcription.log')
        
        dialog.destroy()

    def on_run_button_clicked(self, button):
        model_name = self.model_combo.get_selected_item().get_string()
        
        # Get device settings
        device = 'cuda' if self.gpu_radio.get_active() else 'cpu'
        force_device = self.force_device_check.get_active()
        
        # Get compute type
        compute = self.compute_combo.get_selected_item().get_string().split(' ')[0]
        
        # Get time range
        start_time = self.start_time.get_text().strip() or None
        end_time = self.end_time.get_text().strip() or None
        
        # Initialize YouTube handler if needed
        if self.youtube_subs is None:
            self.youtube_subs = YoutubeSubs(
                model_name=model_name,
                device=device,
                compute=compute,
                force_device=force_device,
                subs_dir="Youtube-Subs",
                enable_logging=self.enable_logging_check.get_active()
            )
        else:
            self.youtube_subs.enable_logging = self.enable_logging_check.get_active()
            self.youtube_subs.device = device
            self.youtube_subs.compute = compute
            self.youtube_subs.force_device = force_device
            
        # Update time range
        self.youtube_subs.start_time = start_time
        self.youtube_subs.end_time = end_time
        
        # Get YouTube URLs
        buffer = self.youtube_input.get_buffer()
        youtube_urls = buffer.get_text(
            buffer.get_start_iter(),
            buffer.get_end_iter(),
            True
        ).strip()
        
        if youtube_urls:
            self.run_button.set_sensitive(False)
            
            # Create thread for YouTube processing
            thread = TranscriptionThread(
                files_to_process=[],
                model_name=model_name,
                log_callback=self.log,
                youtube_urls=youtube_urls,
                youtube_subs=self.youtube_subs
            )
            thread.start()
            return
            
        # Process local files
        files_to_process = self.selected_files.copy()
        if self.selected_directory:
            files_to_process.extend([
                os.path.join(self.selected_directory, f)
                for f in os.listdir(self.selected_directory)
                if f.lower().endswith(('.mkv', '.mp3', '.wav', '.flac', '.ogg'))
            ])
            
        if not files_to_process:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="No files, directory, or YouTube URLs selected."
            )
            dialog.run()
            dialog.destroy()
            return
            
        self.run_button.set_sensitive(False)
        buffer = self.log_output.get_buffer()
        buffer.set_text("")
        
        thread = TranscriptionThread(
            files_to_process,
            model_name,
            self.log
        )
        thread.start()

    def log(self, text, mpv='err'):
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_text = f"[{timestamp}] {text}"
        
        buffer = self.log_output.get_buffer()
        end_iter = buffer.get_end_iter()
        buffer.insert(end_iter, log_text + '\n')
        
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding="utf-8") as f:
                    f.write(log_text + '\n')
                    if mpv != 'err':
                        f.write(f"[{timestamp}] {mpv}\n")
            except Exception as e:
                end_iter = buffer.get_end_iter()
                buffer.insert(end_iter, f"Error writing to log file: {str(e)}\n")

    def check_clipboard(self):
        if not self.clipboard_monitoring:
            return True
            
        try:
            current_clipboard = pyperclip.paste()
            if current_clipboard == self.last_clipboard:
                return True
                
            self.last_clipboard = current_clipboard
            
            urls = current_clipboard.split('\n')
            youtube_urls = []
            
            for url in urls:
                url = url.strip()
                if 'youtu' in url.lower():
                    youtube_urls.insert(0, url)
            
            if youtube_urls:
                self.add_new_urls(youtube_urls)
                
        except Exception as e:
            self.log(f"Error checking clipboard: {str(e)}")
            
        return True

    def add_new_urls(self, new_urls):
        buffer = self.youtube_input.get_buffer()
        text = buffer.get_text(
            buffer.get_start_iter(),
            buffer.get_end_iter(),
            True
        )
        current_urls = set(text.split('\n'))
        current_urls.discard('')
        
        added = False
        for url in new_urls:
            if url not in current_urls:
                current_urls.add(url)
                added = True
        
        if added:
            buffer.set_text('\n'.join(sorted(current_urls)))
            self.log(f"Added {len(new_urls)} new YouTube URL(s) from clipboard")

    def update_url_count(self, *args):
        buffer = self.youtube_input.get_buffer()
        text = buffer.get_text(
            buffer.get_start_iter(),
            buffer.get_end_iter(),
            True
        )
        urls = [url for url in text.split('\n') if url.strip()]
        self.url_count_label.set_text(f"{len(urls)} URLs")

    def resort_urls(self, *args):
        buffer = self.youtube_input.get_buffer()
        text = buffer.get_text(
            buffer.get_start_iter(),
            buffer.get_end_iter(),
            True
        )
        urls = [url for url in text.split('\n') if url.strip()]
        if not urls:
            return
            
        if self.sort_oldest_check.get_active():
            if self.youtube_subs is None:
                self.youtube_subs = YoutubeSubs(
                    model_name=self.model_combo.get_selected_item().get_string(),
                    device='cuda'
                )
            urls = self.youtube_subs.sort_by_date(urls)
            
        if self.reverse_order_check.get_active():
            urls.reverse()
            
        buffer.set_text('\n'.join(urls))

class TranscriptionApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.github.fastwhisper")

    def do_activate(self):
        win = TranscriptionApp(application=self)
        win.present()

def main(version):
    app = TranscriptionApplication()
    return app.run(sys.argv)

if __name__ == "__main__":
    sys.exit(main("4.0"))
