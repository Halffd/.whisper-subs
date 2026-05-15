"""
WhisperSubs tkinter GUI - Desktop Application

Simple tkinter interface for audio/video transcription using WhisperX.
Supports all adapter backends via provider:model syntax.
"""
import os
from pathlib import Path
import ffmpeg
from tkinter import Tk, filedialog, ttk
import whisperx
import torch

from ui.models import get_flat_display_list, is_separator as _is_sep


def convert_mkv_to_mp3(input_file, output_file):
    try:
        input_stream = ffmpeg.input(input_file)
        audio_stream = input_stream.audio
        output_stream = ffmpeg.output(audio_stream, output_file, vcodec='libmp3lame')
        ffmpeg.run(output_stream)
        print(f"Conversion successful: {input_file} -> {output_file}")
    except Exception as e:
        print(f"Error converting {input_file}: {e}")


def transcribe_audio(audio_file, model_name="base", device=None, compute_type="int8"):
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisperx.load_model(model_name, device=device, compute_type=compute_type)
    result = model.transcribe(audio_file, language="ja")
    return result


def format_timestamp(timestamp):
    hours = int(timestamp // 3600)
    minutes = int(timestamp % 3600 // 60)
    seconds = timestamp % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def _get_selected_model(combo, items):
    sel = combo.get()
    if _is_sep(sel):
        for item in items:
            if not _is_sep(item):
                return item
        return "base"
    return sel


def main():
    root = Tk()
    root.title("WhisperSubs - Transcription")
    root.geometry("500x200")

    model_items = get_flat_display_list()

    frame = ttk.Frame(root, padding=10)
    frame.pack(fill="x")

    ttk.Label(frame, text="Model:").pack(side="left", padx=(0, 5))

    combo = ttk.Combobox(frame, values=model_items, state="readonly", width=40)
    combo.pack(side="left", fill="x", expand=True)

    default_idx = 0
    for i, item in enumerate(model_items):
        if not _is_sep(item):
            default_idx = i
            break
    combo.current(default_idx)

    def run_transcription():
        model_name = _get_selected_model(combo, model_items)
        files = filedialog.askopenfilenames(
            title="Select one or more files",
            filetypes=[("Audio/Video files", "*.mkv;*.wav;*.mp3;*.flac;*.ogg")]
        )

        for file in files:
            file_ext = os.path.splitext(file)[1].lower()
            if file_ext == ".mkv":
                mp3_file = os.path.splitext(file)[0] + ".mp3"
                convert_mkv_to_mp3(file, mp3_file)
            else:
                result = transcribe_audio(file, model_name=model_name)
                srt_file = os.path.splitext(file)[0] + ".srt"
                with open(srt_file, "w", encoding="utf-8") as f:
                    for i, segment in enumerate(result.segments, start=1):
                        start_time = segment.start.total_seconds()
                        end_time = segment.end.total_seconds()
                        text = segment.text.strip()
                        f.write(f"{i}\n")
                        f.write(f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}\n")
                        f.write(f"{text}\n\n")
                print(f"SRT file saved: {srt_file}")

    btn_frame = ttk.Frame(root, padding=10)
    btn_frame.pack(fill="x")
    ttk.Button(btn_frame, text="Select Files & Transcribe", command=run_transcription).pack()

    root.mainloop()


if __name__ == "__main__":
    main()
