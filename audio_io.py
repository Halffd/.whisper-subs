"""Shared audio extraction / trimming for every backend.

Every ffmpeg invocation in whisper-subs funnels through here, so the
stream-selection rules below are stated once:

- `-vn` drops video; `-map 0:a:N` pins a *specific* audio track. Without
  `-map`, ffmpeg keeps only the first audio stream of each input and,
  with `-vn` and several tracks, behaviour is build-dependent: some
  builds pick the first track, others mux one silent stream per input
  and the transcriber decodes silence. That is the "2 hours of audio,
  two English tracks and a Japanese dub" failure: the wrong track was
  transcribed and the right one never was.
- `-ac 1 -ar 16000` normalises to what ASR backends want.
- Cut with `-ss` before `-i` (input seeking): the decoder starts at the
  keyframe and demuxer discards up to the exact offset, so a 2-hour file
  cut at 1:50:00 does not decode the hour in between. Cutting *after*
  `-i` demuxes the whole file first, which is why long MKVs appeared to
  hang.
- `-t` (or `-to`) bounds the window, and m4a carries audio only.
"""

import os
import re
import subprocess
from typing import List, Optional

# Extensions that are known containers for video.
VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".ts", ".m2ts"}


def ffprobe_audio_streams(media_path: str) -> List[dict]:
    """List audio streams: [{'index', 'codec', 'language', 'title'}, ...].

    `index` is the stream index inside the container, which is what
    `-map 0:<index>` expects. Returns [] when ffprobe fails or the file
    has no audio.
    """
    if not os.path.exists(media_path):
        return []
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries",
                "stream=index,codec_name,codec_type:stream_tags=language,title",
                "-of", "json",
                media_path,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    import json

    try:
        payload = json.loads(result.stdout or "{}")
    except ValueError:
        return []

    streams: List[dict] = []
    for raw in payload.get("streams", []):
        if raw.get("codec_type") != "audio":
            continue
        try:
            index = int(raw.get("index"))
        except (TypeError, ValueError):
            continue
        tags = raw.get("tags") or {}
        streams.append(
            {
                "index": index,
                "codec": raw.get("codec_name"),
                "language": tags.get("language"),
                "title": tags.get("title"),
            }
        )
    return streams


def _stream_map(media_path: str, audio_track: Optional[str]) -> List[str]:
    """`-map` arguments for the requested audio track.

    `audio_track` is either None (first stream, the historical default)
    or a 0-based audio ordinal / stream selector like "a:1" or "1".
    An explicit index keeps multi-track files from being cut on the
    wrong track.
    """
    if not audio_track:
        return []
    selector = str(audio_track).strip()
    if not selector:
        return []
    # Accept "2", "a:2" and "2:a" (ordinal or stream index); normalise to
    # the 0:<n> form -map expects, and pass anything else through so
    # ffmpeg reports the real error instead of silently picking track 0.
    lowered = selector.lower()
    if lowered.startswith("a:"):
        # Ordinal: "the Nth audio track".
        ordinal = lowered[2:]
        if ordinal.isdigit():
            return ["-map", f"0:a:{ordinal}"]
    if lowered.endswith(":a"):
        # Stream index written backwards, e.g. "1:a".
        index = lowered.split(":", 1)[0]
        if index.isdigit():
            return ["-map", f"0:a:{index}"]
    if lowered.isdigit():
        # Bare number: a stream index.
        return ["-map", f"0:{lowered}"]
    # Anything else is passed through so ffmpeg reports the real error.
    return ["-map", f"0:{selector}"]


def extract_audio(
    video_path: str,
    output_path: str,
    audio_track: Optional[str] = None,
    log=None,
) -> bool:
    """Extract (or copy, if already audio-only) a single audio track.

    Returns True when `output_path` holds a 16 kHz mono M4A.
    """
    write = log if callable(log) else (lambda msg: None)
    streams = ffprobe_audio_streams(video_path)
    if streams and len(streams) > 1 and audio_track is None:
        langs = ", ".join(s.get("language") or "?" for s in streams)
        write(
            f"Note: {os.path.basename(video_path)} has {len(streams)} audio "
            f"tracks ({langs}); using the first. Pass --audio-track N to pick "
            "another."
        )

    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error"]
    cmd += _stream_map(video_path, audio_track)
    cmd += [
        "-i", video_path,
        "-vn",
        "-acodec", "aac", "-b:a", "128k",
        "-ac", "1",
        "-ar", "16000",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0 and os.path.exists(output_path):
        return True
    write(f"Audio extraction failed: {result.stderr.strip()[-400:]}")
    return False


def cut_audio(
    audio_path: str,
    output_path: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    audio_track: Optional[str] = None,
    log=None,
) -> bool:
    """Cut a window out of a media file into a 16 kHz mono M4A.

    `start`/`end` are HH:MM:SS or seconds. The window length is computed
    from the requested bound and passed as `-t`, because `-to` after an
    input `-ss` is measured from the seek point, not from the start of
    the file. `-ss` precedes `-i` (demuxer seek) so a 2-hour source is
    not decoded from the top.
    """
    write = log if callable(log) else (lambda msg: None)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", audio_path]
    cmd += _stream_map(audio_path, audio_track)
    if end:
        cmd += ["-t", _window_seconds(start, end)]
    cmd += [
        "-vn",
        "-acodec", "aac", "-b:a", "128k",
        "-ac", "1",
        "-ar", "16000",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0 and os.path.exists(output_path):
        return True
    write(f"Audio cutting failed: {result.stderr.strip()[-400:]}")
    return False


def _window_seconds(start: Optional[str], end: Optional[str]) -> str:
    """`-t` value for the [start, end) window, as ffmpeg expects."""
    def to_secs(value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            if ":" in text:
                parts = text.split(":")
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
            return float(text)
        except ValueError:
            return None

    start_secs = to_secs(start) or 0.0
    end_secs = to_secs(end) or 0.0
    seconds = max(0.0, end_secs - start_secs)
    return str(seconds) if seconds > 0 else "0"


def probe_duration(media_path: str) -> Optional[float]:
    """Duration in seconds via ffprobe, or None when unknown."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                media_path,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None
