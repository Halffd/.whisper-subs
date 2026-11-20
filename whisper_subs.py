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
import random
import pyperclip
import yt_dlp
import hashlib
import vad
import app_meta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any, Tuple, Union

# Lazy imports - only import when needed
_transcribe_module = None
_twitch_vod_module = None
_model_module = None
_livestream_transcriber_module = None
_helper_files_module = None


def _get_transcribe():
    """Lazy import for transcribe module"""
    global _transcribe_module
    if _transcribe_module is None:
        import transcribe as _transcribe_module
    return _transcribe_module


def _get_helper_files():
    """Lazy import for helper_files module"""
    global _helper_files_module
    if _helper_files_module is None:
        import helper_files as _helper_files_module
    return _helper_files_module


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
EMPTY_SRT_FILE = os.path.join(OUTPUT_DIR, "empty_srts.txt")
# An existing subtitle with fewer entries than this is treated as
# unfinished, so a truncated or placeholder file gets re-transcribed.
MIN_EXISTING_SRT_LINES = 2
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
    if not os.path.exists(JOBS_FILE):
        return []
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_jobs(jobs):
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
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
        "tasks": [],
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
    print(
        f"{'ID':<4} {'Date':<20} {'Model':<15} {'Status':<12} {'Progress':<12} {'Source'}"
    )
    print("-" * 100)
    for job in jobs:
        date_str = datetime.datetime.fromisoformat(job["date"]).strftime(
            "%Y-%m-%d %H:%M"
        )
        source_str = (
            job["source"][:40] + "..." if len(job["source"]) > 40 else job["source"]
        )

        total_tasks = len(job.get("tasks", []))
        completed_tasks = len(
            [
                t
                for t in job.get("tasks", [])
                if t.get("status") in ["completed", "skipped"]
            ]
        )
        progress_str = f"{completed_tasks}/{total_tasks}" if total_tasks > 0 else "N/A"

        print(
            f"{job['id']:<4} {date_str:<20} {job['model']:<15} {job['status']:<12} {progress_str:<12} {source_str}"
        )


# --- Core Class ---
def cookie_domains_hit(domains) -> bool:
    """True when a cookie jar holds a youtube.com / youtube-nocookie login."""
    return any(
        domain == "youtube.com"
        or domain.endswith(".youtube.com")
        or domain.endswith(".youtube-nocookie.com")
        for domain in domains
    )


class WhisperSubs:
    def __init__(
        self,
        model_name: str = "large",
        device: str = "cpu",
        compute_type: str = "int8",
        force: bool = False,
        ignore_subs: bool = False,
        fetch_caps: Optional[bool] = None,
        fetch_auto: bool = False,
        fetch_langs: str = "",
        inpaint: bool = False,
        inpaint_min_gap: float = 3.0,
        sub_lang: Optional[str] = None,
        language: Optional[str] = None,
        run_mpv: bool = False,
        browser: str = "firefox",
        cookie_file: Optional[str] = None,
        strict_language_tier: bool = False,
        force_retry: bool = False,
        vad_filter: Optional[bool] = None,
        vad_min_silence_duration: Optional[int] = None,
        diarization: bool = False,
        min_speakers: int = 1,
        max_speakers: int = 2,
        num_speakers: Optional[int] = None,
        temperature: Optional[float] = None,
        merge_lines: bool = False,
        whisperx_vad: bool = True,
        min_word_confidence: float = 0.4,
        furigana: bool = False,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        start_force: bool = False,
        mpv_ipc: bool = False,
        mpv_socket: Optional[str] = None,
        mpv_auto: bool = False,
        cpu_threads: Optional[int] = None,
        audio_track: Optional[str] = None,
        diarize_engine: Optional[str] = None,
        vad_engine: Optional[str] = None,
        vad_params_extra: Optional[Dict[str, str]] = None,
        playlist_mode: Optional[str] = None,
        playlist_path: Optional[str] = None,
        save_video: bool = False,
        save_thumbnail: bool = True,
        show: bool = False,
    ):
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.force = force
        self.force_retry = force_retry
        self.ignore_subs = ignore_subs
        # Caption fetching: None means "human captions only, on by default".
        self.fetch_caps = fetch_caps
        self.fetch_auto = fetch_auto
        self.fetch_langs = [
            l.strip() for l in (fetch_langs or "").split(",") if l.strip()
        ]
        self.inpaint = inpaint
        self.inpaint_min_gap = inpaint_min_gap
        self.sub_lang = sub_lang
        self.language = language
        self.run_mpv = run_mpv
        self.specified_browser = browser
        self.cookie_file = cookie_file
        # '' means probed and none found; None means not probed yet.
        self._cookie_browser_cache: Optional[str] = None
        self.force_cookies = True if browser else False
        self.strict_language_tier = strict_language_tier
        self.save_video = save_video
        self.save_thumbnail = save_thumbnail
        self.show = show
        self.model = None
        self.log_file = os.path.join(
            os.path.expanduser("~/.config/WhisperSubs"), "whisper_subs.log"
        )
        self.info_cache: Dict[
            str, Tuple[str, str]
        ] = {}  # Cache for video info to avoid re-fetching
        # Full yt-dlp info dicts and channel avatars, for subtitle metadata
        self.source_info_cache: Dict[str, Dict[str, Any]] = {}
        self.channel_thumb_cache: Dict[str, Optional[str]] = {}
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
        self.num_speakers = num_speakers
        # Transcription settings
        self.temperature = temperature
        self.merge_lines = merge_lines
        # WhisperX-specific settings (vad, word confidence, furigana)
        self.whisperx_vad = whisperx_vad
        self.min_word_confidence = min_word_confidence
        self.furigana = furigana
        # Time range settings
        self.start_time = start_time
        self.end_time = end_time
        self.start_force = start_force
        # MPV IPC settings
        self.mpv_ipc = mpv_ipc
        self.mpv_socket = mpv_socket or "/tmp/mpvsocket"
        self.mpv_auto = mpv_auto
        # CPU threads setting
        self.cpu_threads = cpu_threads
        # Preferred audio stream for multi-track media (None = first track)
        self.audio_track = audio_track
        # Diarization engine (pyannote / nemo / auto)
        self.diarize_engine = diarize_engine
        # VAD engine for adapter models (None = silero default)
        self.vad_engine = vad_engine
        self.vad_params_extra = vad_params_extra or {}

        # Optional callback when SRT file is created (for streaming)
        # Called with (srt_path, unfinished_srt_path) when the unfinished SRT is created
        self.on_srt_created: Optional[Callable[[str, str], None]] = None
        # Final and in-progress SRT paths of the most recent run; None
        # until a transcription produces them.
        self.last_srt_file: Optional[str] = None
        self.last_unfinished_srt: Optional[str] = None

        # mpv playlist support. `playlist_mode` is None, "pending" or
        # "channel"; `playlist_path` is the m3u handed to mpv.
        self.playlist_mode = playlist_mode
        self.playlist_path = playlist_path
        self.playlist: Optional[Any] = None
        # launch_mpv reads this unconditionally; empty means "no playlist".
        self.playlist_file: Optional[str] = None
        if self.playlist_mode:
            self._init_playlist()

    def _init_playlist(self) -> None:
        """Create the m3u that mpv will follow."""
        import playlist as playlist_mod

        path = self.playlist_path or os.path.join(OUTPUT_DIR, "playlist.m3u")
        self.playlist = playlist_mod.Playlist(path)
        self.playlist_file = self.playlist.path
        self.log(f"Playlist: {self.playlist.path}")

    def _append_to_playlist(self, source: str, srt_file: Optional[str]) -> None:
        """Queue a finished video for the running player.

        Called once a subtitle exists so playback continues into the
        next item without restarting mpv.
        """
        if self.playlist is None:
            return
        try:
            added = self.playlist.append(source, srt_file)
            if added:
                self.log(f"Added to playlist: {source}")
        except Exception as e:
            self.log(f"Warning: could not update playlist: {e}")

    def _build_channel_playlist(self, channel_dir: str) -> None:
        """Queue every finished subtitle in a channel directory."""
        # `is None`, not truthiness: an empty Playlist is falsy via __len__.
        if self.playlist is None or not os.path.isdir(channel_dir):
            return
        try:
            items = []
            for name in sorted(os.listdir(channel_dir)):
                if not name.endswith(".srt") or name.endswith(".unfinished.srt"):
                    continue
                full = os.path.join(channel_dir, name)
                if os.path.islink(full):
                    continue
                meta = os.path.join(
                    channel_dir, name[: -len(".srt")] + ".metadata.json"
                )
                url = ""
                if os.path.exists(meta):
                    try:
                        with open(meta, "r", encoding="utf-8") as f:
                            url = json.load(f).get("source_url") or ""
                    except (OSError, json.JSONDecodeError):
                        url = ""
                if url:
                    items.append((url, full))
            added = self.playlist.extend(items)
            self.log(f"Queued {added} channel videos for playback")
        except Exception as e:
            self.log(f"Warning: could not build channel playlist: {e}")

    def _find_cookie_browser(self) -> Optional[str]:
        """Which installed browser can actually yield a YouTube cookie jar.

        yt-dlp aborts the whole download with `CookieLoadError` when the named
        browser's cookie store is missing or unreadable — which is what a bare
        `cookiesfrombrowser=("firefox",)` produces on a machine where the
        default browser is Chrome, or where Firefox is not installed at all.
        Probing once keeps metadata-only calls working for every channel and
        avoids retrying a download that cannot succeed.
        """
        if self._cookie_browser_cache is not None:
            return self._cookie_browser_cache

        ordered: List[str] = []
        if self.specified_browser:
            ordered.append(self.specified_browser)
        for candidate in (
            "firefox", "chrome", "chromium", "edge", "brave", "opera",
            "vivaldi", "safari", "whale",
        ):
            if candidate not in ordered:
                ordered.append(candidate)

        from yt_dlp.cookies import extract_cookies_from_browser

        for candidate in ordered:
            try:
                jar = extract_cookies_from_browser(candidate)
            except Exception:
                continue
            domains = {c.domain.lstrip(".") for c in jar}
            if cookie_domains_hit(domains):
                self._cookie_browser_cache = candidate
                return candidate

        self._cookie_browser_cache = ""
        return None

    def _cookie_error(self) -> str:
        """Actionable message when no browser cookies can be read."""
        return (
            "No browser cookies readable for a YouTube login. yt-dlp aborts "
            "downloads with HTTP 403 when it cannot authenticate. Fix any of: "
            "log into youtube.com in your browser; pass --browser "
            "<firefox|chrome|chromium|edge|brave|opera|vivaldi>; or export a "
            "cookies.txt (Netscape format) and pass --cookies-file pointing at "
            "it (equivalent to yt-dlp's --cookies-from-browser)."
        )

    def _get_ytdlp_base_opts(self, **extra_opts) -> Dict[str, Any]:
        """Get base yt-dlp options with cookies from browser (required for YouTube)."""
        base_opts = {
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 10,
            "no_check_certificate": True,
        }
        if self.specified_browser:
            browser = self._find_cookie_browser()
            if browser:
                base_opts["cookiesfrombrowser"] = (browser,)
            else:
                message = self._cookie_error()
                self.log(message)
                raise RuntimeError(message)
        if self.cookie_file:
            base_opts["cookiefile"] = self.cookie_file
        base_opts.update(extra_opts)
        return base_opts

    def log(self, message: str) -> None:
        message_str = str(message)
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message_str}")
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message_str}\n")

    def is_youtube(self, url: str) -> bool:
        return bool(url and "youtu" in urlparse(url).netloc)

    def is_twitch(self, url: str) -> bool:
        return bool(url and "twitch.tv" in urlparse(url).netloc)

    def is_local_file(self, path: str) -> bool:
        return bool(path and os.path.exists(path))

    def is_local_dir(self, path: str) -> bool:
        return bool(path and os.path.isdir(path))

    def _safe_model_filename(self) -> str:
        """Return model name sanitized for use in filenames (colons -> underscores)."""
        return self.model_name.replace(":", "_")

    def _strip_model_from_filename(self, filename: str) -> str:
        """Strip any existing model name from filename to prevent duplicate model suffixes."""
        import model

        title = filename
        for model_name in _get_model().ALL_MODEL_NAMES:
            safe_name = model_name.replace(":", "_")
            title = re.sub(rf"\.{re.escape(safe_name)}(?=\.\w+$|$)", "", title)
            title = re.sub(rf"\.{re.escape(model_name)}(?=\.\w+$|$)", "", title)
        return title

    def is_channel_or_playlist_url(self, url):
        if not self.is_youtube(url) or ("v=" in url and "list=" in url):
            return False
        return any(
            indicator in url
            for indicator in [
                "@",
                "/channel/",
                "/c/",
                "/user/",
                "youtube.com/playlist?list=",
                "youtu.be/playlist?list=",
            ]
        )

    def is_twitch_channel(self, url):
        parsed = urlparse(url)
        if "twitch.tv" in parsed.netloc:
            path_parts = [p for p in parsed.path.split("/") if p]
            if len(path_parts) == 1:
                return path_parts[0]
            elif len(path_parts) == 2 and path_parts[1] == "videos":
                return path_parts[0]
        return None, ""

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

            # Keep the full dict so the subtitle metadata does not have to
            # fetch the same page again.
            self.source_info_cache[url] = dict(info)

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

    def get_source_info(self, url: str) -> Dict[str, Any]:
        """Full yt-dlp info dict for a URL, cached to avoid re-fetching.

        Used for the subtitle metadata (channel, stats, thumbnail, subs
        availability). Local files have no yt-dlp info and return {}.
        """
        if self.is_local_file(url):
            return {}

        clean_url = self.clean_youtube_url(url) if self.is_youtube(url) else url
        if clean_url in self.source_info_cache:
            return self.source_info_cache[clean_url]

        try:
            ydl_opts = self._get_ytdlp_base_opts(skip_download=True)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                raw_info = ydl.extract_info(url, download=False)
            info: Dict[str, Any] = dict(raw_info) if raw_info else {}
        except Exception as e:
            self.log(f"Warning: could not fetch video info for metadata: {e}")
            info = {}

        self.source_info_cache[clean_url] = info
        return info

    def get_channel_thumbnail(self, channel_url: Optional[str]) -> Optional[str]:
        """Channel avatar URL from the channel page, cached per channel.

        yt-dlp does not expose channel avatars in video info, so the channel
        page is read once per channel. Returns None when unavailable.
        """
        if not channel_url:
            return None
        if channel_url in self.channel_thumb_cache:
            return self.channel_thumb_cache[channel_url]

        thumbnail = None
        try:
            import requests

            response = requests.get(
                channel_url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "en-US,en",
                },
            )
            if response.ok:
                match = re.search(
                    r'<meta property="og:image" content="([^"]+)"', response.text
                )
                if match:
                    thumbnail = match.group(1)
        except Exception:
            thumbnail = None

        self.channel_thumb_cache[channel_url] = thumbnail
        return thumbnail

    def build_source_info(self, url: str, is_local: bool) -> Dict[str, Any]:
        """Video/channel fields stored in the subtitle metadata."""
        if is_local:
            return app_meta.build_source_info(
                {"title": os.path.basename(url), "channel_name": "local_files"},
                source_url=url,
            )

        info = self.get_source_info(url)
        channel_url = info.get("channel_url") or info.get("uploader_url")
        return app_meta.build_source_info(
            info,
            source_url=url,
            channel_thumbnail_url=self.get_channel_thumbnail(channel_url),
        )

    def backup_existing_sub(self, srt_file: str) -> Optional[str]:
        """Moves an existing subtitle aside before a forced re-transcription.

        `name.srt` becomes `name.2.srt`, then `name.3.srt` and so on; the
        matching metadata file is kept with it. Returns the new path, or None
        when there was nothing to preserve.
        """
        if not srt_file or not (os.path.exists(srt_file) or os.path.islink(srt_file)):
            return None

        if os.path.islink(srt_file):
            target = os.path.realpath(srt_file)
            os.remove(srt_file)
            existing = target if os.path.exists(target) else None
        else:
            existing = srt_file

        if not existing:
            return None

        stem = os.path.splitext(existing)[0]
        # A symlinked final subtitle points at "<name>.unfinished.srt"; back it
        # up as "<name>.2.srt" so the numbered files match the subtitle naming.
        if stem.endswith(".unfinished"):
            stem = stem[: -len(".unfinished")]
        number = 2
        while True:
            backup = f"{stem}.{number}.srt"
            if not os.path.exists(backup):
                break
            number += 1

        os.rename(existing, backup)
        self.log(f"Kept previous subtitle: {backup}")

        old_meta = os.path.splitext(srt_file)[0] + ".metadata.json"
        if os.path.exists(old_meta):
            new_meta = os.path.splitext(backup)[0] + ".metadata.json"
            try:
                os.rename(old_meta, new_meta)
            except OSError as e:
                self.log(f"Warning: could not move subtitle metadata: {e}")

        return backup

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
        if "youtu.be/" in url:
            # Extract the video ID (the part after youtu.be/)
            video_id = (
                url.split("youtu.be/")[-1].split("?")[0].split("&")[0].split("#")[0]
            )
            if len(video_id) == 11:  # YouTube video IDs are always 11 characters
                return f"https://youtu.be/{video_id}"
            return url  # Return original if we can't extract a valid ID

        # Handle full YouTube URLs
        if "youtube.com/watch" in url or "youtube.com/embed/" in url:
            from urllib.parse import urlparse, parse_qs, urlunparse

            try:
                # Parse the URL
                parsed = urlparse(url)

                # Extract video ID from the query parameters
                if "youtube.com/watch" in url:
                    query = parse_qs(parsed.query)
                    if "v" in query:
                        video_id = query["v"][0].split("&")[0]  # Get just the ID part
                        if len(video_id) == 11:  # Validate it's a proper YouTube ID
                            # Rebuild URL with just the video ID
                            clean_query = f"v={video_id}"
                            return urlunparse(
                                parsed._replace(query=clean_query, fragment="")
                            )

                # Handle embed URLs
                elif "youtube.com/embed/" in url:
                    path_parts = parsed.path.split("/")
                    if len(path_parts) >= 3:
                        video_id = path_parts[2].split("?")[0]
                        if len(video_id) == 11:
                            return f"https://youtu.be/{video_id}"

            except Exception as e:
                self.log(f"Error cleaning URL {url}: {e}")

        # Return original URL if we couldn't clean it
        return url

    @staticmethod
    def _strip_emojis(text):
        """Remove emojis and other non-filesystem-safe Unicode from text.

        Keeps: ASCII, common Latin/Greek/Cyrillic/CJK, digits, punctuation.
        Replaces: emojis, symbols, decorative Unicode, zero-width chars,
        control chars, and anything above U+FFFF (supplementary planes).
        """
        import unicodedata

        out = []
        for ch in text:
            cp = ord(ch)
            if cp < 0x20:
                continue
            if cp >= 0xFE00 and cp <= 0xFE0F:
                continue
            if cp >= 0x1F000 and cp <= 0x1FFFF:
                continue
            if cp >= 0xE0000 and cp <= 0xE007F:
                continue
            if cp > 0xFFFF:
                cat = unicodedata.category(ch)
                if cat.startswith(("So", "Sk")):
                    continue
                out.append(ch)
                continue
            cat = unicodedata.category(ch)
            if cat.startswith(("So", "Cc", "Cf")):
                continue
            if cat == "Sk" and cp > 0x0300:
                continue
            out.append(ch)
        return "".join(out)

    def clean_filename(self, filename):
        # If it's a YouTube URL, clean it first
        if isinstance(filename, str) and (
            "youtube.com" in filename or "youtu.be" in filename
        ):
            filename = self.clean_youtube_url(filename)

        # Remove invalid characters from filename
        filename = re.sub(r'[\\/*?:"<>|]', "_", str(filename))
        # Strip emojis and non-filesystem-safe Unicode
        filename = self._strip_emojis(filename)
        # Collapse multiple underscores/spaces
        filename = re.sub(r"[_\s]+", " ", filename)
        filename = filename.strip()
        # Fallback if title was only emojis/symbols
        if not filename:
            filename = "untitled"
        return filename

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
                    yield {
                        "source": item,
                        "status": "pending",
                        "title": os.path.basename(item),
                    }

        elif self.is_local_dir(source):
            self.log(f"Source is a local directory: {source}")
            for root, _, files in os.walk(source):
                for file in files:
                    if file.lower().endswith(
                        (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".mkv")
                    ):
                        file_path = os.path.join(root, file)
                        yield {
                            "source": file_path,
                            "status": "pending",
                            "title": os.path.splitext(file)[0],
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

            # Use an explicit executor so Ctrl+C cancels pending lookups
            # instead of joining every in-flight extract_info call.
            executor = ThreadPoolExecutor(max_workers=5)
            try:
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
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            if processed_count > 0:
                self.log(
                    f"Skipped {processed_count} already processed videos, processing {skipped_count} new ones"
                )
        # Check for Twitch channel videos page specifically
        elif (
            self.is_twitch(source) and "/videos" in source and "/videos/" not in source
        ):
            # This is a Twitch channel videos page (e.g., twitch.tv/channel/videos)
            self.log(f"Detected Twitch channel VOD page: {source}")

            # Extract channel name from URL
            import re

            channel_match = re.search(r"twitch\.tv/([^/]+)/videos", source)
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
                        title = self.clean_filename(vod["title"])
                        yield {"source": vod_url, "status": "pending", "title": title}

                    if processed_count > 0:
                        self.log(
                            f"Skipped {processed_count} already processed VODs, processing {skipped_count} new ones"
                        )

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
                title = self.clean_filename(title)
                yield {"source": source, "status": "pending", "title": title}
            except Exception as e:
                self.log(f"Error getting video info: {e}")
                yield {
                    "source": source,
                    "status": "pending",
                    "title": os.path.basename(source),
                }

    def _convert_to_audio(self, video_path: str) -> Optional[str]:
        """Convert video file to audio-only M4A for transcription.

        This is needed for time cutting (--start/--end) to work properly,
        as cutting video files requires video encoding which may fail.
        """
        if not os.path.exists(video_path):
            return None

        video_exts = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"}
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

        import audio_io

        track = self._select_audio_track(video_path)

        def _note(msg):
            self.log(msg)

        if audio_io.extract_audio(video_path, audio_path, audio_track=track, log=_note):
            self.log(f"Audio extracted: {os.path.basename(audio_path)}")
            try:
                import audio_cache

                audio_cache.put(video_path, audio_path)
            except Exception:
                pass
            return audio_path
        else:
            self.log(f"Audio extraction failed, using original file")
            return video_path

    def _select_audio_track(self, video_path: str) -> Optional[str]:
        """Pick the audio track to transcribe.

        Explicit `--audio-track N` wins (validated against the real
        stream list). Otherwise the first track is used and a multi-track
        file is noted, so a Japanese dub hiding behind an English track
        is visible instead of silent.
        """
        import audio_io

        requested = getattr(self, "audio_track", None)
        if requested:
            return str(requested)

        if os.environ.get("WHISPERSUBS_AUDIO_TRACK"):
            return os.environ["WHISPERSUBS_AUDIO_TRACK"]

        try:
            streams = audio_io.ffprobe_audio_streams(video_path)
        except Exception:
            return None

        if len(streams) > 1:
            langs = ", ".join(str(s.get("language") or "?") for s in streams)
            self.log(
                f"{os.path.basename(video_path)} has {len(streams)} audio "
                f"tracks ({langs}); using the first. Pass --audio-track N "
                "(0-based) or --lang <code> to choose."
            )
        return None

    def check_and_download_subs(self, url, output_dir, title):
        """Check for subs with minimal overhead.

        Returns the path of the downloaded subtitle when human-made subs
        were found, otherwise None.
        """
        if self.ignore_subs:
            return None

        # Default behaviour: human-made captions only. --no-fetch-caps turns
        # the whole path off, --fetch-auto also accepts YouTube's automatic
        # captions.
        if self.fetch_caps is False:
            return None

        self.log("Checking for existing subtitles...")

        try:
            import caption_fetch

            timestamp = ""
            try:
                ydl_opts = self._get_ytdlp_base_opts(
                    skip_download=True,
                    writesubtitles=False,
                    listsubtitles=False,
                )
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                if info:
                    timestamp = info.get("timestamp", "") or ""
            except Exception:
                timestamp = ""

            if timestamp:
                date_time = datetime.datetime.fromtimestamp(timestamp)
                timeday = date_time.strftime("%Y-%m-%d_%H-%M")
            else:
                timeday = ""

            safe_title = (
                f"{timeday}_{self.clean_filename(title)}"
                if timeday
                else self.clean_filename(title)
            )
            # Extension-less: caption_fetch appends ".<lang>.srt".
            out_base = os.path.join(output_dir, safe_title)

            result = caption_fetch.fetch_captions(
                url,
                out_base,
                langs=self.fetch_langs,
                allow_automatic=bool(self.fetch_auto),
                write=self.log,
                video_title=title,
            )
            if not result.ok:
                # Distinguish "nothing to grab" from a fetch failure; both
                # fall through to transcription, which is the safe default.
                return None

            final_file = os.path.join(output_dir, f"{safe_title}.srt")
            if result.path and os.path.exists(result.path):
                if os.path.exists(final_file):
                    os.remove(final_file)
                os.rename(result.path, final_file)
                kind = "automatic" if result.automatic else "human-made"
                self.log(f"Subtitle saved to {final_file} ({kind})")
                _get_helper_files().make_files(final_file, url=url)
                return final_file

        except Exception as e:
            self.log(f"Subtitle check failed: {e}")

        return None

    def download_audio(self, url: str, output_path: str) -> Optional[Tuple[str, str]]:
        """Download audio and return the actual file path and the upload timestamp."""
        self.log(f"Downloading audio from {url}...")

        expected_base = None
        os.makedirs(output_path, exist_ok=True)

        # Clean the URL first
        clean_url = self.clean_youtube_url(url) if self.is_youtube(url) else url

        # === STEP 1.5: Check audio cache ===
        if not self.force:
            try:
                import audio_cache

                entry = audio_cache.get_meta(clean_url)
                if entry and os.path.exists(entry["path"]):
                    cached = entry["path"]
                    self.log(f"Using cached audio: {cached}")
                    dest = os.path.join(output_path, os.path.basename(cached))
                    if dest != cached and not os.path.exists(dest):
                        import shutil

                        shutil.copy2(cached, dest)
                        return dest, entry.get("timeday", "")
                    return cached, entry.get("timeday", "")
            except Exception as e:
                self.log(f"Cache lookup failed: {e}")

        # === STEP 2: Download the file ===
        original_cwd = os.getcwd()
        os.chdir(output_path)

        # Define progress hook once outside the loop
        def progress_hook(d):
            """Show clean progress updates."""
            if d["status"] == "downloading":
                if "total_bytes" in d or "total_bytes_estimate" in d:
                    total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                    downloaded = d.get("downloaded_bytes", 0)

                    if total > 0:
                        percent = (downloaded / total) * 100
                        last_percent = getattr(progress_hook, "last_percent", -1)

                        # Show at 10%, 20%, 30%... milestones
                        if int(percent) % 10 == 0 and int(percent) != last_percent:
                            speed = d.get("speed", 0)
                            speed_mb = speed / (1024 * 1024) if speed else 0
                            self.log(f"Download: {int(percent)}% ({speed_mb:.1f} MB/s)")
                            progress_hook.last_percent = int(percent)

            elif d["status"] == "finished":
                filename = os.path.basename(d.get("filename", "unknown"))
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
                    timestamp = info.get("timestamp", "")
                    if timestamp:
                        date_time = datetime.datetime.fromtimestamp(timestamp)
                        timeday = date_time.strftime("%Y-%m-%d_%H-%M")
                    else:
                        timeday = ""

                    clean_title = self.clean_filename(info.get("title", "unknown"))
                    # Strip any existing model suffix to avoid duplicate model names
                    title_without_model = self._strip_model_from_filename(clean_title)
                    expected_base = (
                        f"{timeday}_{title_without_model}.{self._safe_model_filename()}"
                        if timeday
                        else f"{title_without_model}.{self._safe_model_filename()}"
                    )

                    # Download with proper template
                    download_opts = self._get_ytdlp_base_opts(
                        outtmpl=f"{expected_base}.%(ext)s",
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
                            "youtube": {"player_client": ["android", "web"]}
                        },
                        http_chunk_size=10485760,
                        concurrent_fragment_downloads=5,
                    )

                    if fallback_format:
                        download_opts["format"] = fallback_format
                    elif not self.save_video:
                        download_opts.update(
                            {
                                "format": "bestaudio[ext=m4a]/bestaudio/best",
                                "postprocessors": [
                                    {
                                        "key": "FFmpegExtractAudio",
                                        "preferredcodec": "m4a",
                                        "preferredquality": "192",
                                    }
                                ],
                            }
                        )
                    else:
                        download_opts.update(
                            {
                                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                                "merge_output_format": "mp4",
                            }
                        )

                    self.log(f"Starting download (attempt {attempt}/{max_attempts})...")
                    with yt_dlp.YoutubeDL(download_opts) as ydl:
                        ydl.download([clean_url])

                    # Find the downloaded file based on expected name
                    for ext in [".m4a", ".mp4", ".mp3", ".webm", ".ogg"]:
                        predicted_path = f"{expected_base}{ext}"
                        full_path = os.path.join(output_path, predicted_path)
                        if os.path.exists(full_path):
                            self.log(f"Successfully downloaded: {full_path}")
                            return full_path, timeday

                    self.log(
                        f"Download completed but expected file not found: {expected_base}"
                    )
                    return None

                except Exception as e:
                    error_str = str(e).lower()

                    if (
                        "rate" in error_str
                        or "unavailable" in error_str
                        or "429" in error_str
                    ) and attempt < max_attempts:
                        delay = min(30 * (2**attempt), 3600)
                        self.log(
                            f"Rate limited. Retrying in {delay}s... (attempt {attempt}/{max_attempts})"
                        )
                        time.sleep(delay)
                        continue
                    elif (
                        "requested format is not available" in error_str
                        or "format not available" in error_str
                    ) and attempt < max_attempts:
                        self.log(
                            f"Format not available. Trying fallback format... (attempt {attempt}/{max_attempts})"
                        )
                        if attempt == 1:
                            fallback_format = "bestaudio[ext=m4a]/bestaudio/best"
                        elif attempt == 2:
                            fallback_format = "bestaudio/best"
                        else:
                            fallback_format = "best"
                        continue
                    else:
                        self.log(f"Download failed: {e}")
                        return None

        finally:
            os.chdir(original_cwd)
            # Clean up leftover .part files from interrupted/failed downloads
            if expected_base:
                for part_file in glob.glob(
                    os.path.join(output_path, f"{expected_base}*.part")
                ):
                    try:
                        os.remove(part_file)
                        self.log(
                            f"Cleaned up partial download: {os.path.basename(part_file)}"
                        )
                    except OSError:
                        pass
                # Clean up thumbnails unless saving video
                if not self.save_video:
                    for thumb_ext in [".webp", ".jpg", ".jpeg", ".png"]:
                        thumb_path = os.path.join(
                            output_path, f"{expected_base}{thumb_ext}"
                        )
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
        clean_source = (
            self.clean_youtube_url(source) if self.is_youtube(source) else source
        )

        # Handle YouTube URLs
        if self.is_youtube(clean_source):
            # Try to extract from youtu.be/ID format first
            if "youtu.be/" in clean_source:
                video_id = (
                    clean_source.split("youtu.be/")[-1]
                    .split("?")[0]
                    .split("&")[0]
                    .split("#")[0]
                )
                if len(video_id) == 11:  # Validate it's a proper YouTube ID
                    return video_id

            # Try to extract from youtube.com/watch?v=ID format
            if "youtube.com/watch" in clean_source:
                from urllib.parse import urlparse, parse_qs

                parsed = urlparse(clean_source)
                if "v" in parse_qs(parsed.query):
                    video_id = parse_qs(parsed.query)["v"][0].split("&")[0]
                    if len(video_id) == 11:  # Validate it's a proper YouTube ID
                        return video_id

            # Try to extract from youtube.com/embed/ID format
            if "youtube.com/embed/" in clean_source:
                parts = clean_source.split("youtube.com/embed/")[-1].split("/")
                if parts and len(parts[0]) == 11:
                    return parts[0]

        # Handle Twitch VODs
        if self.is_twitch(clean_source):
            match = re.search(r"(?:videos?|clip)/(\d+)", clean_source)
            if match:
                return f"twitch_{match.group(1)}"

        # Handle local files - use file hash for reliable tracking
        if self.is_local_file(clean_source):
            return self._get_file_hash(clean_source)

        # Fallback: use a hash of the source string
        return f"hash_{hash(clean_source) & 0xFFFFFFFF}"

    def _get_file_hash(self, file_path: str) -> str:
        """Generate MD5 hash of file content (first 1MB for speed)."""
        import hashlib

        if not os.path.exists(file_path):
            return f"file_{os.path.basename(file_path)}"

        try:
            md5 = hashlib.md5()
            # Read first 1MB for speed - enough to detect same file
            with open(file_path, "rb") as f:
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

        current_is_english = ".en" in self.model_name

        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
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

                history_is_english = ".en" in history_model

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
                    current_normalized = (
                        current_model_index - 7
                        if current_is_english
                        else current_model_index
                    )
                    history_normalized = (
                        history_model_index - 7
                        if history_is_english
                        else history_model_index
                    )

                    # Now compare normalized values
                    # large-v3 (6) vs medium.en (10 -> 3): 6 >= 3 → large-v3 wins ✅
                    # medium.en (10 -> 3) vs large-v3 (6): 3 >= 6 → re-process ✅
                    if history_normalized >= current_normalized:
                        return True
                # ==================================

        return False

    def mark_as_processed(self, unique_id):
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(f"{unique_id} {self.model_name}\n")

    def is_already_processed(self, url: str) -> bool:
        """Check if a URL has already been processed by checking history file."""
        if not os.path.exists(HISTORY_FILE):
            return False

        # Clean URL for consistent comparison
        clean_url = self.clean_youtube_url(url) if self.is_youtube(url) else url

        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = set(line.strip().split()[0] for line in f if line.strip())

            # Check both original and cleaned URL
            return url in history or clean_url in history
        except Exception:
            return False

    def find_existing_srt(self, source: str) -> Optional[str]:
        """Locate an existing finished subtitle for `source`.

        Matches on the video id or source URL recorded in the sibling
        `<name>.metadata.json`. In-progress artifacts (`.unfinished.srt`
        and the symlink that points at them) are ignored, and numbered
        backups (`name.2.srt`) are skipped in favour of the current file.

        Returns the subtitle path, or None when the source has no
        finished subtitle on disk.
        """
        if not source:
            return None

        unique_id = self.get_unique_id(source)
        if not unique_id or not os.path.isdir(OUTPUT_DIR):
            return None

        matches: List[str] = []
        for root, dirs, files in os.walk(OUTPUT_DIR):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if not name.endswith(".metadata.json"):
                    continue

                srt_path = os.path.join(root, name[: -len(".metadata.json")] + ".srt")
                if (
                    not os.path.exists(srt_path)
                    or os.path.islink(srt_path)
                    or srt_path.endswith(".unfinished.srt")
                ):
                    continue
                # Numbered backups (name.2.srt) are not the current subtitle.
                if re.search(r"\.\d+\.srt$", srt_path):
                    continue

                try:
                    with open(os.path.join(root, name), "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except (OSError, json.JSONDecodeError):
                    continue

                recorded_url = meta.get("source_url") or meta.get("url") or ""
                recorded_id = meta.get("video_id") or ""
                if recorded_id == unique_id or (
                    recorded_url and self.get_unique_id(recorded_url) == unique_id
                ):
                    matches.append(srt_path)

        if not matches:
            return None

        # Newest subtitle wins when several models produced one.
        return max(matches, key=os.path.getmtime)

    def validate_existing_srt(self, srt_path: str) -> Tuple[bool, str]:
        """Check an existing subtitle is usable before trusting the skip.

        A subtitle counts as usable when it parses as real SRT blocks and
        carries at least MIN_EXISTING_SRT_LINES entries. Anything less
        (placeholder text, zero bytes, a lone stray cue) is treated as
        unfinished so the task is re-transcribed.

        Returns (ok, reason). `reason` is empty when ok.
        """
        import transcribe as _tr

        if not srt_path or not os.path.exists(srt_path):
            return False, "missing"
        if os.path.getsize(srt_path) == 0:
            return False, "empty file"

        report = _tr.verify_srt_file(srt_path, write=lambda m: None)
        if not report["ok"]:
            problems = "; ".join(report["problems"][:3])
            return False, f"invalid ({problems})"
        if report["segments"] < MIN_EXISTING_SRT_LINES:
            return (
                False,
                f"only {report['segments']} subtitle (needs {MIN_EXISTING_SRT_LINES})",
            )
        return True, ""

    def _report_existing(self, task_source: str, srt_path: str) -> None:
        """Print what is known about a finished subtitle.

        The metadata sits next to the subtitle as <name>.metadata.json, so the
        video facts, the date it was transcribed and the model that produced
        it are all available without another network round trip.
        """
        self.log(f"Subtitle: {srt_path}")

        base = srt_path[: -len(".srt")] if srt_path.endswith(".srt") else srt_path
        meta_path = f"{base}.metadata.json"
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, json.JSONDecodeError):
                meta = {}

            def _field(label: str, *keys: str) -> None:
                for key in keys:
                    value = meta.get(key)
                    if value not in (None, ""):
                        self.log(f"{label}: {value}")
                        return

            _field("Title", "title")
            _field("Channel", "channel_name", "channel")
            _field("Source", "source_url", "url", "webpage_url")
            _field("Transcribed", "transcription_timestamp", "date")
            _field("Published", "upload_timestamp")
            _field("Model", "model")
            _field("Duration", "duration_seconds")
            _field("Views", "views")
            _field("Cues", "segments_count")
        else:
            self.log(f"Metadata: {meta_path} not found")

        wrappers = [
            path
            for ext in (".sh", ".bat", ".ps1", ".htm")
            if (path := f"{base}{ext}") and os.path.exists(path)
        ]
        if wrappers:
            self.log("Wrappers: " + ", ".join(wrappers))
        else:
            # Regenerate so a finished video is always runnable.
            try:
                created = _get_helper_files().make_files(srt_path, url=task_source)
                made = [str(p) for p in (created or {}).values() if p]
                if made:
                    self.log("Wrappers: " + ", ".join(made))
            except Exception as e:
                self.log(f"Warning: could not create wrappers: {e}")

    def _handle_existing_subtitle(
        self, job_id: int, task_source: str, unique_id: str
    ) -> bool:
        """Validate an already-processed subtitle and report its paths.

        Returns True when the task may be skipped, False when the
        subtitle is unusable and the task must run again.
        """
        existing_srt = self.find_existing_srt(task_source)

        if existing_srt:
            ok, reason = self.validate_existing_srt(existing_srt)
            if ok:
                self.log(f"Reusing existing subtitle: {existing_srt}")
                self._report_existing(task_source, existing_srt)
                if self.run_mpv or self.mpv_auto:
                    self.log(f"Playing existing subtitle: {existing_srt}")
                    self.launch_mpv(task_source, existing_srt, task_source)
                # Queue it so --playlist replays finished videos too.
                self._append_to_playlist(task_source, existing_srt)
                return True

            self.log(
                f"Existing subtitle unusable ({reason}): {existing_srt}. "
                "Re-transcribing."
            )
            # Drop the completion marker so the retry is not skipped again.
            import srt_checker

            srt_checker.remove_from_history(
                HISTORY_FILE, [unique_id, task_source, existing_srt]
            )
            return False

        self.log(f"No existing subtitle found for '{task_source}'. Re-transcribing.")
        import srt_checker

        srt_checker.remove_from_history(HISTORY_FILE, [unique_id, task_source])
        return False

    def process_task(self, job_id, task, task_id: Optional[str] = None):
        task_source = task["source"]
        unique_id = self.get_unique_id(task_source)
        if not self.force_retry and self.is_processed(unique_id):
            # Validate what is on disk before trusting the skip: an empty
            # or near-empty subtitle is re-transcribed instead.
            if self._handle_existing_subtitle(job_id, task_source, unique_id):
                update_task_status(job_id, task_source, "skipped", task["title"])
                return
            self.log(f"Skipping task '{task_source}' - already processed.")
            self.log("Retrying transcription because the subtitle is unusable.")

        # Generate task_id if not provided (for API media path registration)
        if task_id is None:
            import hashlib

            task_id = f"{job_id}_{hashlib.md5(task_source.encode()).hexdigest()[:8]}"

        audio_file, timeday = None, ""
        is_local = self.is_local_file(task_source)
        try:
            title, self.channel_name = self.get_video_info(task_source)
            if is_local:
                self.channel_name = "local_files"
            update_task_status(job_id, task_source, "processing", title)
            self.model_name = _get_model().getName(self.model_name)
            channel_dir = os.path.join(
                OUTPUT_DIR, self.clean_filename(self.channel_name)
            )
            os.makedirs(channel_dir, exist_ok=True)
            if self.playlist_mode == "channel":
                self._build_channel_playlist(channel_dir)

            if (
                not is_local
                and not self.force_retry
                and (
                    downloaded_sub := self.check_and_download_subs(
                        task_source, channel_dir, title
                    )
                )
                and not self.force
            ):
                self.log(
                    f"Found existing human-made subtitle for '{title}', skipping transcription. Use -r to force re-transcription."
                )
                self.mark_as_processed(unique_id)
                # No transcription follows, so honour a player request now.
                if self.run_mpv or self.mpv_auto:
                    self.launch_mpv(task_source, downloaded_sub, task_source)
                update_task_status(job_id, task_source, "skipped")
                return

            # FIX: Just pass the directory, not a template path
            if is_local:
                # Convert video to audio if needed (for time cutting to work properly)
                audio_file = self._convert_to_audio(task_source)
                if not audio_file:
                    self.log(f"Failed to convert video to audio: {task_source}")
                    # Mark the task failed: an unmarked task reads as "not
                    # failed" where the job status is computed, so the job was
                    # reported "completed" after every download failed.
                    update_task_status(job_id, task_source, "failed")
                    return
            else:
                result = self.download_audio(task_source, channel_dir)
                if not result:
                    self.log(f"Failed to download audio: {task_source}")
                    update_task_status(job_id, task_source, "failed")
                    return
                audio_file, timeday = result

            if not audio_file or not os.path.exists(audio_file):
                self.log(f"Audio file not found: {audio_file}")
                update_task_status(job_id, task_source, "failed")
                return

            # Register audio file for media streaming API
            try:
                from api.server import register_media_path

                register_media_path(task_id, "audio", audio_file)
            except ImportError:
                pass  # API server not available (e.g., CLI mode)

            update_task_status(job_id, task_source, "transcribing")
            safe_model = self._safe_model_filename()
            if is_local:
                base_name = os.path.splitext(os.path.basename(audio_file))[0]
                if not base_name.endswith(f".{safe_model}"):
                    base_name = f"{base_name}.{safe_model}"
            else:
                title_without_model = self._strip_model_from_filename(
                    self.clean_filename(title)
                )
                base_name = (
                    f"{timeday}_{title_without_model}.{safe_model}"
                    if timeday
                    else f"{title_without_model}.{safe_model}"
                )
                self.log(f"DEBUG: Using base_name={base_name}")

            # Write to both locations: video folder AND Documents/Youtube-Subs/local_files
            if is_local:
                # Primary: video file's folder
                srt_file = os.path.join(os.path.dirname(audio_file), f"{base_name}.srt")
                # Secondary: Documents/Youtube-Subs/local_files
                local_files_dir = os.path.join(OUTPUT_DIR, "local_files")
                os.makedirs(local_files_dir, exist_ok=True)
                srt_file_secondary = os.path.join(local_files_dir, f"{base_name}.srt")

                # Check for existing unfinished transcription to resume
                unfinished_srt = srt_file.replace(".srt", ".unfinished.srt")
                if (
                    os.path.exists(unfinished_srt)
                    and os.path.getsize(unfinished_srt) > 10
                ):
                    self.log(f"Found unfinished transcription: {unfinished_srt}")
                    self.log("Will resume from where it left off...")
            else:
                channel_dir = os.path.join(
                    OUTPUT_DIR, self.clean_filename(self.channel_name)
                )
                os.makedirs(channel_dir, exist_ok=True)
                srt_file = os.path.join(channel_dir, f"{base_name}.srt")
                srt_file_secondary = None

            # Keep the previous subtitle when forcing a re-transcription
            if self.force or self.force_retry:
                self.backup_existing_sub(srt_file)
                if srt_file_secondary:
                    self.backup_existing_sub(srt_file_secondary)

            # Video/channel facts stored in the subtitle metadata
            source_info = self.build_source_info(task_source, is_local)

            # Create helper files (bash, bat, thumbnail) before transcription
            unfinished_srt = srt_file.replace(".srt", ".unfinished.srt")
            _get_helper_files().make_files(unfinished_srt, url=task_source)

            # Register SRT paths for streaming API
            try:
                from api.server import register_srt_path

                register_srt_path(task_id, "unfinished", unfinished_srt)
                register_srt_path(task_id, "srt", srt_file)
            except ImportError:
                pass  # API server not available (e.g., CLI mode)

            # Create symlink from srt_file -> unfinished_srt so players see in-progress transcription
            try:
                if os.path.exists(srt_file) or os.path.islink(srt_file):
                    os.remove(srt_file)
                os.symlink(os.path.basename(unfinished_srt), srt_file)
            except OSError:
                pass

            # Remember what this run produced so callers (API server)
            # can register the paths even when the callback fired before
            # they were attached.
            self.last_srt_file = srt_file
            self.last_unfinished_srt = unfinished_srt

            # Callback for real-time subtitle streaming
            if self.on_srt_created:
                try:
                    self.on_srt_created(srt_file, unfinished_srt)
                except Exception as e:
                    self.log(f"Warning: on_srt_created callback failed: {e}")

            # Launch mpv FIRST if --run option is specified (before transcription starts)
            mpv_process = None
            if hasattr(self, "run_mpv") and self.run_mpv:
                mpv_process = self.launch_mpv(
                    audio_file if is_local else task_source, srt_file, task_source
                )
                # Wait a moment for mpv to start
                time.sleep(1)

            # Start auto-reload thread if mpv_ipc is enabled
            reload_stop_event = threading.Event()
            reload_thread = None
            if hasattr(self, "mpv_ipc") and self.mpv_ipc and mpv_process:
                reload_thread = self.start_mpv_auto_reload(srt_file, reload_stop_event)

            # Build VAD parameters if enabled
            vad_params = None
            if hasattr(self, "vad_filter") and self.vad_filter:
                vad_params = (
                    dict(min_silence_duration_ms=self.vad_min_silence_duration)
                    if self.vad_min_silence_duration
                    else None
                )

            # Build diarization parameters if enabled
            diarization_params = None
            if hasattr(self, "diarization") and self.diarization:
                diarization_params = dict(
                    min_speakers=self.min_speakers, max_speakers=self.max_speakers
                )

            if _get_transcribe().process_create(
                file=audio_file,
                model_name=self.model_name,
                srt_file=srt_file,
                language=getattr(self, "language", None),
                device=self.device,
                compute_type=self.compute_type,
                force_device=False,
                auto=True,
                write=self.log,
                cpu_threads=getattr(self, "cpu_threads", None),
                vad_filter=self.vad_filter if hasattr(self, "vad_filter") else False,
                vad_params=vad_params,
                diarization=self.diarization if hasattr(self, "diarization") else False,
                diarization_params=diarization_params,
                temperature=self.temperature if hasattr(self, "temperature") else None,
                merge_lines=self.merge_lines if hasattr(self, "merge_lines") else False,
                start_time=getattr(self, "start_time", None),
                end_time=getattr(self, "end_time", None),
                mpv_auto=getattr(self, "mpv_auto", False),
                mpv_socket=self.mpv_socket,
                media_source=audio_file if is_local else task_source,
                show_segments=getattr(self, "show", False),
                source_info=source_info,
                whisperx_vad=getattr(self, "whisperx_vad", True),
                min_word_confidence=getattr(self, "min_word_confidence", 0.4),
                furigana=getattr(self, "furigana", False),
                diarize=getattr(self, "diarization", False),
                hf_token=os.environ.get("HF_TOKEN"),
                diarize_engine=getattr(self, "diarize_engine", None),
                vad_engine=getattr(self, "vad_engine", None),
                vad_params_extra=getattr(self, "vad_params_extra", None),
                min_speakers=getattr(self, "min_speakers", None),
                max_speakers=getattr(self, "max_speakers", None),
                num_speakers=getattr(self, "num_speakers", None),
            ):
                self.log("Transcription successful.")
                # Update the SRT filename in case it was changed during processing
                if os.path.exists(srt_file):
                    base_name = os.path.splitext(srt_file)[0]
                    new_srt_file = f"{base_name}.srt"
                    if new_srt_file != srt_file and os.path.exists(new_srt_file):
                        srt_file = new_srt_file
                _get_helper_files().make_files(srt_file, url=task_source)

                # Fill in the stretches the SRT left empty. Runs on the local
                # faster-whisper backend (the adapter path has no way to feed
                # a clipped file back to a model), and only when the user
                # asked: it re-transcribes audio, so it doubles the pass over
                # the gaps and is not something to do silently.
                if self.inpaint:
                    try:
                        import audio_inpaint

                        # Runs on the local faster-whisper backend (the adapter
                        # path has no way to feed a clipped file to a model),
                        # and re-transcribes audio, so it doubles the pass over
                        # the holes -- done only when asked, never silently.
                        result = audio_inpaint.inpaint_srt(
                            srt_path=srt_file,
                            audio_path=audio_file,
                            model=self.model_name,
                            language=self.language or "en",
                            min_gap_seconds=self.inpaint_min_gap,
                            write=self.log,
                        )
                        report = result.as_dict()
                        self.log(
                            f"Inpainting: {report['filled']}/{report['gaps']} "
                            f"gap(s) filled, {report['added_cues']} cue(s) "
                            f"added ({report['recovered_seconds']:.1f}s)"
                        )
                        for failure in report["failures"]:
                            self.log(f"  inpaint: {failure}")

                        self.log("Verifying inpainted subtitles...")
                        srt_problems = self._verify_inpaint(srt_file, audio_file)
                        if srt_problems:
                            for problem in srt_problems:
                                self.log(f"  verify: {problem}")
                    except Exception as inpaint_err:
                        self.log(f"Warning: inpainting skipped: {inpaint_err}")

                # Copy to secondary location if applicable
                if srt_file_secondary and os.path.exists(srt_file):
                    try:
                        import shutil

                        shutil.copy2(srt_file, srt_file_secondary)
                        self.log(f"Copied subtitle to: {srt_file_secondary}")
                    except Exception as copy_err:
                        self.log(
                            f"Warning: Could not copy to secondary location: {copy_err}"
                        )

                # Stop auto-reload thread
                if reload_thread:
                    reload_stop_event.set()
                    reload_thread.join(timeout=2)

                # Final subtitle reload
                if hasattr(self, "mpv_ipc") and self.mpv_ipc and mpv_process:
                    self.mpv_reload_subtitles(srt_file)

                # Empty-subtitle check: an empty SRT must not be marked
                # complete — clear its progress/completed indicators and
                # record it so the next run re-transcribes it
                import srt_checker

                if srt_checker.check_empty_srt(
                    srt_path=srt_file,
                    ids=[unique_id, task_source],
                    source=task_source,
                    model_name=self.model_name,
                    history_file=HISTORY_FILE,
                    jobs_file=JOBS_FILE,
                    job_id=job_id,
                    list_file=EMPTY_SRT_FILE,
                    write=self.log,
                ):
                    raise Exception(
                        f"Unusable subtitles for '{task_source}' (empty or "
                        "hallucinated) — removed from progress/completed "
                        "indicators, added to the empty list"
                    )
                update_task_status(job_id, task_source, "completed")
                self.mark_as_processed(unique_id)
            else:
                raise Exception("Transcription process failed.")

        except Exception as e:
            self.log(f"Error on task '{task_source}': {e}")
            update_task_status(job_id, task_source, "failed")

        finally:
            if audio_file and not is_local and os.path.exists(audio_file):
                if not self.save_video:
                    try:
                        import audio_cache

                        cached_path = audio_cache.put(task_source, audio_file, timeday)
                        if cached_path:
                            self.log(f"Cached audio: {cached_path}")
                    except Exception:
                        pass
                    try:
                        os.remove(audio_file)
                    except OSError as e:
                        self.log(f"Error removing temp audio: {e}")
                else:
                    self.log(f"Keeping media file: {audio_file}")

    def launch_mpv(self, audio_file, srt_file, task_source):
        """Launch mpv with the audio file, subtitles, and --pause flag.

        Guarded by mpv_lock so one media source opens one window even
        though both this path and the first-segment hook can fire. The
        player's output goes to <subtitle>.mpv.log and a watcher reports
        when it exits, so a player that dies on a dead URL is not silent.
        """
        import mpv_lock

        try:
            # Determine the media source to use - prefer the original source if it's a URL
            # If it's a local file, use the audio file directly
            is_local = self.is_local_file(task_source)
            media_source = audio_file if is_local else task_source

            mpv_socket = self.mpv_socket if self.mpv_socket else "/tmp/mpvsocket"

            log_path = None
            if srt_file:
                base = (
                    srt_file[: -len(".srt")] if srt_file.endswith(".srt") else srt_file
                )
                log_path = f"{base}.mpv.log"

            process = mpv_lock.launch(
                media_source,
                srt_file=srt_file,
                socket_path=mpv_socket,
                playlist=self.playlist_file,
                log_file=log_path,
            )
            if process is None:
                self.log(f"mpv already open for {media_source}, not reopening")
                return None

            self.log(f"Launched mpv: {media_source}")
            if log_path:
                self.log(f"mpv output: {log_path}")
            self._watch_mpv(process, log_path)
            return process

        except Exception as e:
            self.log(f"Error launching mpv: {e}")
            return None

    def _watch_mpv(self, process, log_path: Optional[str]) -> None:
        """Report when the detached player exits, echoing its tail on error.

        mpv runs detached, so without this a player that fails to open its
        media exits with a nonzero status and nothing is ever printed.
        """

        def watcher() -> None:
            try:
                code = process.wait()
            except Exception:
                return
            handle = getattr(process, "log_handle", None)
            tail = ""
            if log_path and os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        lines = [l.strip() for l in f if l.strip()]
                    if handle:
                        handle.close()
                    tail = " | ".join(lines[-3:])
                except OSError:
                    tail = ""
            if code == 0:
                self.log("mpv exited normally.")
            else:
                self.log(f"mpv exited with code {code}.")
                if tail:
                    self.log(f"mpv output tail: {tail}")

        threading.Thread(target=watcher, daemon=True).start()

    def _verify_inpaint(self, srt_file: str, audio_file: str) -> List[str]:
        """Report gaps that survive in the SRT after inpainting.

        Re-parses the finished file rather than trusting the pass, since the
        point of inpainting is measurable: fewer holes, more cues. Uses the
        shared gap analysis so the thresholds match what `verify_subtitles`
        and the tests use.
        """
        try:
            import audio_inpaint as ai
            import audio_io as aio
        except Exception as exc:
            return [f"could not load verification modules: {exc}"]

        cues = ai.parse_srt(srt_file)
        if not cues:
            return ["SRT has no usable cues"]

        duration = aio.probe_duration(audio_file)
        remaining = ai.find_gaps(
            cues, duration, min_gap_seconds=self.inpaint_min_gap
        )
        if not remaining:
            return []

        problems: List[str] = []
        for start, end in remaining:
            problems.append(
                f"gap remains: {start:.1f}s-{end:.1f}s ({end - start:.1f}s)"
            )
        if duration:
            still = sum(b - a for a, b in remaining)
            problems.append(
                f"{still:.1f}s of {duration:.0f}s still uncovered"
            )
        return problems

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
                    self.log(
                        f"Auto-reload failed (#{reload_count}) - mpv may not be running"
                    )

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
            command = {"command": ["sub-reload"]}
            sock.sendall(json.dumps(command).encode() + b"\n")

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
        sources = job["source"] if isinstance(job["source"], list) else [job["source"]]

        # Get existing tasks to know where to resume from
        existing_tasks = job.get("tasks", [])
        processed_sources = {
            task["source"]
            for task in existing_tasks
            if task["status"] in ["completed", "skipped", "failed"]
        }

        total_processed = len(processed_sources)
        total_discovered = len(existing_tasks)

        update_job(job["id"], {"status": "processing"})

        # Process each source
        for source in sources:
            self.log(f"Processing source: {source}")

            # Use lazy generator to get tasks one by one
            for task in self.resolve_source_to_tasks_lazy(source):
                total_discovered += 1

                # Skip if already processed
                if task["source"] in processed_sources:
                    self.log(f"Skipping already processed: {task['title']}")
                    # Keep it queued so --playlist-channel stays complete.
                    if self.playlist_mode:
                        existing = self.find_existing_srt(task["source"])
                        if existing:
                            self._append_to_playlist(task["source"], existing)
                    continue

                # Add task to job
                existing_tasks.append(task)
                update_job(job["id"], {"tasks": existing_tasks})

                # Generate task_id for media path registration
                import hashlib

                task_id = f"{job['id']}_{hashlib.md5(task['source'].encode()).hexdigest()[:8]}"

                # Process the task
                self.log(
                    f"Processing [{total_processed + 1}/{total_discovered}]: {task['title']}"
                )
                self.process_task(job["id"], task, task_id)

                # Queue the video for the player once its subtitle exists.
                if self.playlist_mode:
                    ready = self.find_existing_srt(task["source"])
                    if ready:
                        self._append_to_playlist(task["source"], ready)
                    else:
                        self._append_to_playlist(task["source"], None)

                # Update progress
                total_processed += 1
                processed_sources.add(task["source"])

                # Update job status after each task
                updated_jobs = get_jobs()
                current_job = next(
                    (j for j in updated_jobs if j["id"] == job["id"]), None
                )
                if current_job:
                    # Count only tasks that actually succeeded; a failed one
                    # is processed but not completed.
                    done = sum(
                        1
                        for t in current_job.get("tasks", [])
                        if t.get("status") in ["completed", "skipped"]
                    )
                    failed_now = sum(
                        1
                        for t in current_job.get("tasks", [])
                        if t.get("status") == "failed"
                    )
                    suffix = f", {failed_now} failed" if failed_now else ""
                    self.log(
                        f"Progress: {done}/{total_discovered} tasks completed{suffix}"
                    )

        # Mark the job from what actually happened to its tasks. Reporting
        # "completed" after a failed transcription hides the failure.
        refreshed = get_jobs()
        current = next((j for j in refreshed if j["id"] == job["id"]), None)
        task_statuses = [
            t.get("status") for t in (current or {}).get("tasks", [])
        ] or []
        failed = sum(1 for s in task_statuses if s == "failed")
        if task_statuses and failed == len(task_statuses):
            # Every task reported in and none worked.
            final_status = "failed"
        elif failed:
            final_status = "completed_with_errors"
        else:
            # Nothing failed: some tasks may still be unstarted, but the job
            # itself ran to completion, which is what "completed" means here.
            final_status = "completed"
        update_job(job["id"], {"status": final_status})
        self.log(f"Job {job['id']} finished with status: {final_status}")
        if failed:
            self.log(f"{failed} task(s) failed — see the errors above.")

    def process(self, job_or_source: Union[Dict[str, Any], str]) -> None:
        """Main processing entry point."""
        if isinstance(job_or_source, dict):
            job = job_or_source
        else:
            job = add_job(job_or_source, self.model_name)

        # Normalize source to list
        if isinstance(job["source"], str):
            if "\n" in job["source"]:
                job["source"] = job["source"].split("\n")
            else:
                job["source"] = [job["source"]]

        # Use lazy resolution for better performance and resume capability
        try:
            self.process_with_lazy_resolution(job)
        except KeyboardInterrupt:
            self.log("Interrupted by user (Ctrl+C), stopping job.")
            try:
                update_job(job["id"], {"status": "interrupted"})
            except Exception:
                pass


def read_sources_from_file(filename):
    """
    Read sources from a file, one per line, with optional model specifications.

    Format:
    <url_or_path> [model_name_or_index]

    Example:
    https://www.youtube.com/watch?v=example1 large-v3
    https://www.youtube.com/watch?v=example2 10
    /path/to/local/audio.mp3 base
    https://www.youtube.com/watch?v=example3
    """
    try:
        with open(filename, "r", encoding="utf-8") as f:
            sources = []
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = line.split()
                if not parts:
                    continue

                url = parts[0]
                model = parts[1] if len(parts) > 1 else None

                is_url = url.startswith("http") or url.startswith("www.")
                is_local = os.path.exists(os.path.expanduser(url))
                if not is_url and not is_local:
                    print(
                        f"Warning: Line {i} doesn't appear to be a valid URL or local path: {url}",
                        file=sys.stderr,
                    )
                    continue

                sources.append({"url": url, "model": model})

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


def build_parser():
    """Build the full CLI parser (importable for tests)."""
    # The catalog is rendered into --help so the model list is discoverable
    # without a second command. Built lazily; a runtime failure must not stop
    # the parser from working.
    import model_catalog

    examples = """
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

  # List every adapter and model, with availability
  whisper_subs.py --model-list

  # Compare models on one file and pick the best
  whisper_subs.py --rate audio.mp3 -m small,medium,sherpa:parakeet-tdt-0.6b-v2

  # Remove empty/stubbed subtitles and wrappers pointing nowhere
  whisper_subs.py --verify --clean
"""

    parser = argparse.ArgumentParser(
        description="Transcribe audio from various sources.",
        usage="""whisper_subs.py <model> [source] [options]
           whisper_subs.py -p [file.txt]
           whisper_subs.py -l | --list
           whisper_subs.py -c | --continue
           whisper_subs.py --file/-d [file_or_directory]
           whisper_subs.py --model-list
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=examples + "\n" + model_catalog.build_help_epilog(),
    )

    # Model and source arguments
    model_group = parser.add_argument_group("Source and Model")
    model_group.add_argument(
        "model",
        nargs="?",
        help="Whisper model name/index (e.g., 'tiny', 'base', 'small', 'medium', 'large', 'large-v2', 'large-v3')",
    )
    model_group.add_argument(
        "source",
        nargs="?",
        help="URL, local file/directory path, or multiple paths/URLs separated by newlines.",
    )

    # Source type arguments (explicit source specification)
    source_group = parser.add_argument_group("Source Specification")
    source_group.add_argument(
        "--url",
        "-u",
        dest="url_source",
        help="YouTube/Twitch URL to transcribe (overrides positional source)",
    )
    source_group.add_argument(
        "--file",
        "-F",
        dest="file_source",
        help="Local audio/video file to transcribe (overrides positional source)",
    )
    source_group.add_argument(
        "--dir",
        "-d",
        dest="dir_source",
        help="Local directory to transcribe all media files (overrides positional source)",
    )

    # Action arguments
    action_group = parser.add_argument_group("Actions")
    action_group.add_argument(
        "-l", "--list", action="store_true", help="List all jobs and exit."
    )
    parser.add_argument(
        "--model-list",
        action="store_true",
        help="List every adapter and model with availability, then exit.",
    )
    parser.add_argument(
        "--rate",
        action="store_true",
        help="Transcribe one file with each candidate model and ask which is best.",
    )
    parser.add_argument(
        "--rate-models",
        type=str,
        default=None,
        metavar="LIST",
        help="Comma-separated models to compare with --rate (default: a spread of local models).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check finished subtitles for missing/empty/corrupt files.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="With --verify, delete empty/stubbed subtitles and wrappers pointing nowhere.",
    )
    parser.add_argument(
        "--compare",
        nargs="+",
        metavar="SRT",
        help="Compare subtitle files for hallucinations and mid-word splits.",
    )
    parser.add_argument(
        "--choose",
        type=int,
        default=None,
        metavar="N",
        help="With --compare, keep file N and move the others aside as .2.srt, .3.srt.",
    )
    action_group.add_argument(
        "-c",
        "--continue",
        dest="continue_last",
        action="store_true",
        help="Continue the last unfinished job.",
    )
    action_group.add_argument(
        "-p",
        "--process-file",
        nargs="?",
        const=PROCESS_FILE,
        help="Read sources from a file (one per line). If no file is specified, uses 'Youtube-Subs/process.txt'.",
    )
    action_group.add_argument(
        "--shuffle",
        action="store_true",
        help="Shuffle the input URLs/files randomly before processing.",
    )
    action_group.add_argument(
        "--shift",
        action="store_true",
        help="Create a shifted queue file (.shift suffix) when using -p. Rerunning shifts/updates that file.",
    )

    # Processing options
    process_group = parser.add_argument_group("Processing Options")
    process_group.add_argument(
        "-g", "--gpu", action="store_true", help="Use GPU (CUDA) if available."
    )
    process_group.add_argument(
        "--device",
        default="cpu",
        help="Device to use ('cpu', 'cuda', 'mps'). Default: 'cpu'",
    )
    process_group.add_argument(
        "--compute",
        default="int8",
        help="Compute type ('int8', 'float16'). Default: 'int8'",
    )
    process_group.add_argument(
        "--cpu-threads",
        type=int,
        default=None,
        help="Number of CPU threads for transcription (default: auto-detect)",
    )
    process_group.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force transcription even if already processed.",
    )
    process_group.add_argument(
        "-r",
        "--force-retry",
        action="store_true",
        help="Force retry transcription even if already completed (ignores existing subtitles).",
    )
    process_group.add_argument(
        "-is", "--ignore-subs", action="store_true", help="Ignore existing subtitles."
    )
    process_group.add_argument(
        "--fetch-caps",
        action="store_true",
        default=None,
        dest="fetch_caps",
        help="Fetch YouTube captions when they exist instead of transcribing "
        "(default: on for human-made captions). '--no-fetch-caps' disables.",
    )
    process_group.add_argument(
        "--no-fetch-caps",
        action="store_false",
        dest="fetch_caps",
        help="Never use YouTube captions; always transcribe.",
    )
    process_group.add_argument(
        "--fetch-auto",
        action="store_true",
        help="Also accept YouTube's automatic captions when no human track "
        "exists (off by default: auto captions are low quality).",
    )
    process_group.add_argument(
        "--fetch-langs",
        type=str,
        default="",
        metavar="LANGS",
        help="Comma-separated caption language preference, e.g. 'en,pt' "
        "(default: video language, then English).",
    )
    process_group.add_argument(
        "-i", "--invert", action="store_true", help="Invert lines"
    )
    process_group.add_argument(
        "-lang", "--language", help="Language code for subtitle priority."
    )
    process_group.add_argument(
        "--cross-tier",
        action="store_true",
        help="Allow comparison between multilingual and English-only models.",
    )
    process_group.add_argument(
        "-m", "--run", action="store_true", help="Run player in background."
    )
    process_group.add_argument(
        "--play",
        action="store_true",
        help="Launch player (mpv) with live subtitle updates (alias for --run).",
    )
    process_group.add_argument(
        "--mpv",
        action="store_true",
        help="Launch mpv when first subtitle segment is written (live preview).",
    )
    process_group.add_argument(
        "--show",
        action="store_true",
        help="Print each new subtitle line as it is transcribed.",
    )
    process_group.add_argument(
        "--playlist",
        action="store_true",
        help="Queue this job's videos in an mpv playlist, appending each as it finishes.",
    )
    process_group.add_argument(
        "--playlist-channel",
        action="store_true",
        help="Queue the channel's finished subtitles in an mpv playlist.",
    )
    process_group.add_argument(
        "--playlist-file",
        type=str,
        default=None,
        metavar="FILE",
        help="Write the mpv playlist to FILE (default: <output>/playlist.m3u).",
    )
    process_group.add_argument(
        "--live",
        action="store_true",
        help="Transcribe live streams in real-time (for Twitch/YouTube live streams).",
    )
    process_group.add_argument(
        "--video",
        action="store_true",
        help="Save the video file (default: False/audio-only).",
    )
    process_group.add_argument(
        "--no-thumbnail",
        action="store_false",
        dest="save_thumbnail",
        help="Do not save the video thumbnail.",
    )
    process_group.add_argument(
        "--yt-search-channels",
        metavar="QUERY",
        help="Search YouTube for channels matching QUERY and list them "
        "(no transcription).",
    )
    process_group.add_argument(
        "--yt-subscribe",
        metavar="CHANNEL",
        help="Follow a YouTube channel (name, @handle, or channel URL).",
    )
    process_group.add_argument(
        "--yt-unsubscribe",
        metavar="CHANNEL",
        help="Unfollow a channel by URL or @handle.",
    )
    process_group.add_argument(
        "--yt-subscriptions",
        action="store_true",
        help="List the channels you follow.",
    )
    process_group.add_argument(
        "--yt-feed",
        action="store_true",
        help="Show the ranked feed of videos from channels you follow.",
    )
    process_group.set_defaults(save_thumbnail=True)

    # Advanced transcription options
    advanced_group = parser.add_argument_group("Advanced Transcription Options")
    advanced_group.add_argument(
        "--vad",
        action="store_true",
        dest="vad_filter",
        help="Enable the Voice Activity Detection (VAD) filter. Off by "
        "default: the filter drops whole stretches of real speech on "
        "material with background music or archive audio, and no smaller "
        "model can recover the missing text.",
    )
    advanced_group.add_argument(
        "--vad-silence",
        type=int,
        default=500,
        help="VAD minimum silence duration in ms (default: 500).",
    )
    advanced_group.add_argument(
        "--browser",
        type=str,
        default="firefox",
        choices=["firefox", "chrome", "chromium", "edge", "brave",
                 "opera", "vivaldi", "safari", "whale"],
        help="Browser to read YouTube login cookies from (default: firefox). "
        "Whichever installed browser has a youtube.com login is used when the "
        "named one has none.",
    )
    advanced_group.add_argument(
        "--cookies-file",
        type=str,
        default=None,
        metavar="FILE",
        help="Netscape cookies.txt to authenticate YouTube downloads with "
        "(overrides browser cookies).",
    )
    advanced_group.add_argument(
        "--inpaint",
        action="store_true",
        help="After transcribing, re-transcribe the stretches the SRT left "
        "empty (with condition_on_previous_text=False) and splice the "
        "recovered cues back in.",
    )
    advanced_group.add_argument(
        "--inpaint-min-gap",
        type=float,
        default=3.0,
        metavar="SECONDS",
        help="Shortest hole to inpaint (default: 3.0).",
    )
    advanced_group.add_argument(
        "--vad-engine",
        type=str,
        default=None,
        choices=["silero", "pyannote", "webrtc", "custom"],
        help="VAD engine for adapter models (default: silero). \"custom\" needs "
        "WHISPERSUBS_VAD=module:callable.",
    )
    advanced_group.add_argument(
        "--vad-param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Parameter for the selected VAD engine; repeat for multiple keys.",
    )
    advanced_group.add_argument(
        "--diarization", action="store_true", help="Enable speaker diarization."
    )
    advanced_group.add_argument(
        "--min-speakers",
        type=int,
        default=1,
        help="Minimum number of speakers for diarization (default: 1).",
    )
    advanced_group.add_argument(
        "--max-speakers",
        type=int,
        default=2,
        help="Maximum number of speakers for diarization (default: 2).",
    )
    advanced_group.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        help="Exact number of speakers for diarization (overrides min/max).",
    )
    advanced_group.add_argument(
        "--diarize-engine",
        type=str,
        default=None,
        choices=["auto", "pyannote", "nemo"],
        help="Diarization engine: pyannote (needs HF_TOKEN) or nemo (NeMo MSDD, "
        "offline). Default: auto.",
    )
    advanced_group.add_argument(
        "--audio-track",
        type=str,
        default=None,
        metavar="N",
        help="Audio stream to transcribe for multi-track media (0-based ordinal, "
        "as reported by ffprobe). Default: the first track.",
    )
    advanced_group.add_argument(
        "--temperature",
        type=float,
        default=0,
        help="Sampling temperature for transcription (default: 0).",
    )
    advanced_group.add_argument(
        "--no-whisperx-vad",
        action="store_false",
        dest="whisperx_vad",
        help="Disable WhisperX VAD pre-filtering (on by default for whisperx:* models).",
    )
    advanced_group.add_argument(
        "--min-word-confidence",
        type=float,
        default=0.4,
        help="WhisperX: drop aligned words below this score, 0.0-1.0 (default: 0.4).",
    )
    advanced_group.add_argument(
        "--furigana",
        action="store_true",
        help="Annotate Japanese cues with furigana readings (whisperx:* models; requires pykakasi).",
    )
    advanced_group.add_argument(
        "--merge-lines", action="store_true", help="Merge adjacent subtitle lines."
    )
    advanced_group.add_argument(
        "--start-time",
        "--start",
        type=str,
        default=None,
        help="Start time to transcribe (format: HH:MM:SS, MM:SS, or minutes as int/float).",
    )
    advanced_group.add_argument(
        "--start-force",
        action="store_true",
        help="Force transcribe only from --start-time to end (default: transcribe both parts and merge).",
    )
    advanced_group.add_argument(
        "--end-time",
        "--end",
        type=str,
        default=None,
        help="End time to transcribe (format: HH:MM:SS, MM:SS, or minutes as int/float).",
    )
    advanced_group.add_argument(
        "--mpv-ipc",
        action="store_true",
        help="Enable MPV IPC subtitle reload during transcription (updates subtitles in real-time).",
    )
    advanced_group.add_argument(
        "--mpv-socket",
        type=str,
        default="/tmp/mpvsocket",
        help="MPV IPC socket path (default: /tmp/mpvsocket).",
    )
    # Livestream options
    advanced_group.add_argument(
        "--live-poll",
        type=int,
        default=10,
        help="Livestream transcription poll interval in seconds (default: 10).",
    )
    advanced_group.add_argument(
        "--live-growth",
        type=float,
        default=1.02,
        help="Livestream growth threshold factor (default: 1.02 = 2%% growth).",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        list_jobs()
        return
    if args.model_list:
        import model_catalog

        groups = _get_model().get_context().list_available_adapters()
        print(model_catalog.format_catalog(groups))
        return

    if args.compare:
        import srt_compare

        srt_compare.report(args.compare)
        if args.choose is not None:
            print()
            srt_compare.choose(args.compare, args.choose)
        return

    # YouTube channel discovery, subscriptions and feed — all metadata-only,
    # none of them transcribe anything.
    if (
        args.yt_search_channels
        or args.yt_subscribe
        or args.yt_unsubscribe
        or args.yt_subscriptions
        or args.yt_feed
    ):
        import api.youtube as yt

        if args.yt_search_channels:
            results = yt.search_channels(args.yt_search_channels)
            if not results:
                print(f"No YouTube channels found for {args.yt_search_channels!r}")
            for r in results:
                subs = f"{r['subscribers']:,}" if r.get("subscribers") else "?"
                print(f"{r['name']:34} {subs:>14} subs  {r['url']}")
        elif args.yt_subscribe:
            channel = yt.channel_from_query(args.yt_subscribe)
            if channel:
                result = yt.subscribe(channel)
                if result["subscribed"]:
                    print(f"Subscribed to {result['channel']['name']}")
                    print(f"  {result['channel']['url']}")
                else:
                    print(f"Could not subscribe: {result.get('reason')}")
            else:
                print(f"No channel found for {args.yt_subscribe!r}")
        elif args.yt_unsubscribe:
            channel = yt.channel_from_query(args.yt_unsubscribe)
            target = (channel or {}).get("url") or args.yt_unsubscribe
            yt.unsubscribe(target)
            print(f"Unsubscribed: {target}")
        elif args.yt_subscriptions:
            subs = yt.load_subscriptions()
            if not subs:
                print("No subscriptions yet. Use --yt-search-channels to find channels.")
            for s in subs:
                print(f"{s.get('name', '?'):34} {s.get('url', '')}")
        elif args.yt_feed:
            feed = yt.recommend(limit=20)
            if not feed:
                print("Your feed is empty — subscribe to a channel with --yt-subscribe.")
            for item in feed:
                reasons = ", ".join(item.get("reasons") or [])
                minutes = (item.get("duration") or 0) / 60.0
                print(
                    f"{item['score']:.2f}  {minutes:5.0f}m  "
                    f"{(item.get('channel') or '?')[:20]:20}  {item['title'][:48]}"
                    + (f"  [{reasons}]" if reasons else "")
                )
        return

    if args.verify:
        import verify_subtitles

        clean = bool(args.clean)
        if not clean:
            print("=== DRY RUN (pass --clean to delete broken files) ===")
        stats = verify_subtitles.verify_and_fix(
            min_size=verify_subtitles.DEFAULT_MIN_SRT_SIZE,
            rerun_file=verify_subtitles.DEFAULT_RERUN_FILE,
            apply_changes=clean,
            clean=clean,
        )
        print("\nSummary:")
        print(f"  Checked: {stats['checked']}")
        print(f"  Missing: {stats['missing']}")
        print(f"  Corrupted: {stats['corrupted']}")
        print(f"  Fixed: {stats['fixed']}")
        print(f"  Removed: {stats.get('removed', 0)}")
        print(f"  Rerun URLs: {len(stats['rerun_list'])}")
        return

    if args.rate:
        import model_rater

        candidates = args.rate_models or model_rater.default_candidates()
        model_rater.rate_file(
            audio_file=args.file_source or args.source,
            models=candidates,
            device="cuda" if args.gpu else args.device,
            compute_type=args.compute,
            cpu_threads=args.cpu_threads,
            audio_track=args.audio_track,
            diarize_engine=args.diarize_engine,
        )
        return

    # Handle continue case first
    if args.continue_last:
        job = get_last_unfinished_job()
        if not job:
            print("No unfinished jobs to continue.")
            return 1  # Exit with error code

        tasks = job.get("tasks", [])
        completed = len(
            [t for t in tasks if t["status"] in ["completed", "skipped", "failed"]]
        )
        total = len(tasks)

        print(f"Continuing job ID {job['id']}")
        print(f"Source: {job['source']}")
        print(f"Progress: {completed}/{total} tasks completed")
        print(f"Model: {job['model']}")

        model_to_use = job["model"]
        job_or_source = job
    elif args.process_file is not None:
        try:
            process_file = os.path.expanduser(args.process_file)
            print(f"Reading sources from file: {process_file}")

            shift_file = None
            if args.shift:
                shift_file = process_file + ".shift"
                if os.path.exists(shift_file):
                    print(f"Resuming from shift file: {shift_file}")
                    sources = read_sources_from_file(shift_file)
                else:
                    sources = read_sources_from_file(process_file)
            else:
                sources = read_sources_from_file(process_file)
            if not sources:
                print(f"No valid sources found in {process_file}", file=sys.stderr)
                return 1

            if args.shuffle:
                random.shuffle(sources)
                print(f"Shuffled {len(sources)} sources")

            if args.shift and shift_file is not None:
                with open(shift_file, "w", encoding="utf-8") as sf:
                    for s in sources:
                        line = s["url"]
                        if s["model"]:
                            line += f" {s['model']}"
                        sf.write(line + "\n")
                print(f"Shift file written: {shift_file}")

            for i, source_info in enumerate(sources):
                source_model = source_info["model"] or args.model
                if source_model is None:
                    print(
                        "Error: No model specified for source and no default model provided. Either specify a model in your process file or provide a model argument (e.g., 'wsub large -p').",
                        file=sys.stderr,
                    )
                    return 1
                model_for_this_source = _get_model().getName(source_model)
                processor = WhisperSubs(
                    model_name=model_for_this_source,
                    device="cuda" if args.gpu else args.device,
                    compute_type=args.compute,
                    force=args.force,
                    ignore_subs=args.ignore_subs,
                    fetch_caps=args.fetch_caps,
                    fetch_auto=args.fetch_auto,
                    fetch_langs=args.fetch_langs,
                    inpaint=args.inpaint,
                    inpaint_min_gap=args.inpaint_min_gap,
                    sub_lang=args.language,
                    language=args.language,
                    run_mpv=args.run or args.play,
                    strict_language_tier=args.cross_tier,
                    force_retry=args.force_retry,
                    vad_filter=args.vad_filter,
                    browser=args.browser,
                    cookie_file=args.cookies_file,
                    vad_min_silence_duration=args.vad_silence,
                    diarization=args.diarization,
                    min_speakers=args.min_speakers,
                    max_speakers=args.max_speakers,
                    num_speakers=args.num_speakers,
                    temperature=args.temperature,
                    merge_lines=args.merge_lines,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    start_force=args.start_force,
                    mpv_ipc=args.mpv_ipc,
                    mpv_socket=args.mpv_socket,
                    mpv_auto=args.mpv,
                    cpu_threads=args.cpu_threads,
                    audio_track=args.audio_track,
                    diarize_engine=args.diarize_engine,
                    save_video=args.video,
                    save_thumbnail=args.save_thumbnail,
                    show=args.show,
                    playlist_mode=(
                        "channel"
                        if args.playlist_channel
                        else ("pending" if args.playlist else None)
                    ),
                    playlist_path=args.playlist_file,
                )
                processor.process(source_info["url"])

                if args.shift and shift_file is not None:
                    remaining = sources[i + 1 :]
                    with open(shift_file, "w", encoding="utf-8") as sf:
                        for s in remaining:
                            line = s["url"]
                            if s["model"]:
                                line += f" {s['model']}"
                            sf.write(line + "\n")
                    if remaining:
                        print(f"Shifted queue: {len(remaining)} sources remaining")
                    else:
                        print("Shift queue empty, removing shift file")
                        os.remove(shift_file)

            return 0
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
                sources = [
                    line.strip()
                    for line in clipboard_content.split("\n")
                    if line.strip()
                ]
                # Save clipboard sources to a timestamped text file in Documents
                try:
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    clipboard_log = os.path.join(
                        OUTPUT_DIR, f"clipboard_{timestamp}.txt"
                    )
                    with open(clipboard_log, "w", encoding="utf-8") as _clf:
                        _clf.write("\n".join(sources) + "\n")
                    print(f"Clipboard sources saved to: {clipboard_log}")
                except OSError as _cle:
                    print(f"Warning: could not save clipboard log: {_cle}")
                if args.shuffle and len(sources) > 1:
                    random.shuffle(sources)
                    print(f"Shuffled {len(sources)} clipboard sources")
                if len(sources) == 1:
                    print(f"Using source from clipboard: {sources[0]}")
                    job_or_source = sources[0]
                else:
                    print(f"Found {len(sources)} sources in clipboard:")
                    if args.invert:
                        print("Inverting...")
                        sources.reverse()
                    for i, src in enumerate(sources):
                        print(f"  {i}. {src}")
                    job_or_source = "\n".join(sources)
            except Exception as e:
                parser.error(f"No source provided and could not read clipboard: {e}")

    # Handle model selection
    if args.continue_last:
        model_to_use = _get_model().getName(job["model"])
    elif args.process_file:
        # For process file, we'll get the model from the file or use default
        # This will be handled in the process file loop
        pass
    elif not args.model and not any(
        [
            args.list,
            args.continue_last,
            args.url_source,
            args.file_source,
            args.dir_source,
        ]
    ):
        parser.error(
            "Model argument is required unless using --list, --continue, --url, --file, or --dir."
        )
    else:
        model_to_use = _get_model().getName(args.model)

    # Handle live stream transcription separately
    if args.live:
        if not job_or_source or (
            isinstance(job_or_source, str) and not job_or_source.strip()
        ):
            print("Error: Live stream mode requires a URL", file=sys.stderr)
            return 1

        # Extract URL if it's a string (might be a list if multiple sources)
        source_url = job_or_source
        if isinstance(job_or_source, list):
            if len(job_or_source) != 1:
                print(
                    "Error: Live stream mode requires exactly one URL", file=sys.stderr
                )
                return 1
            source_url = job_or_source[0]
        elif "\n" in job_or_source:
            # Handle multi-line input
            sources = [
                line.strip() for line in job_or_source.split("\n") if line.strip()
            ]
            if len(sources) != 1:
                print(
                    "Error: Live stream mode requires exactly one URL", file=sys.stderr
                )
                return 1
            source_url = sources[0]

        # Create live stream transcriber and start transcription
        live_transcriber = _get_livestream_transcriber().LiveStreamTranscriber(
            model_name=model_to_use,
            device="cuda" if args.gpu else args.device,
            compute_type=args.compute,
            output_dir=OUTPUT_DIR,
            log_func=lambda msg: print(f"[LIVE] {msg}"),
            live_poll=args.live_poll,
            live_growth=args.live_growth,
            mpv_auto=getattr(args, "mpv", False),
            mpv_socket=args.mpv_socket,
            show_segments=getattr(args, "show", False),
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
        # Shuffle multi-source input if requested
        if args.shuffle and isinstance(job_or_source, str) and "\n" in job_or_source:
            source_list = [l.strip() for l in job_or_source.split("\n") if l.strip()]
            random.shuffle(source_list)
            job_or_source = "\n".join(source_list)
            print(f"Shuffled {len(source_list)} sources")

        processor = WhisperSubs(
            model_name=model_to_use,
            device="cuda" if args.gpu else args.device,
            compute_type=args.compute,
            force=args.force,
            ignore_subs=args.ignore_subs,
            fetch_caps=args.fetch_caps,
            fetch_auto=args.fetch_auto,
            fetch_langs=args.fetch_langs,
            sub_lang=args.language,
            language=args.language,
            run_mpv=args.run or args.play,
            strict_language_tier=args.cross_tier,
            force_retry=args.force_retry,
            vad_filter=args.vad_filter,
            browser=args.browser,
            cookie_file=args.cookies_file,
            vad_min_silence_duration=args.vad_silence,
            diarization=args.diarization,
            min_speakers=args.min_speakers,
            max_speakers=args.max_speakers,
            num_speakers=args.num_speakers,
            temperature=args.temperature,
            merge_lines=args.merge_lines,
            start_time=args.start_time,
            end_time=args.end_time,
            start_force=args.start_force,
            mpv_ipc=args.mpv_ipc,
            mpv_socket=args.mpv_socket,
            mpv_auto=args.mpv,
            cpu_threads=args.cpu_threads,
            audio_track=args.audio_track,
            diarize_engine=args.diarize_engine,
            vad_engine=args.vad_engine,
            vad_params_extra=vad.parse_vad_params(args.vad_param),
            inpaint=args.inpaint,
            inpaint_min_gap=args.inpaint_min_gap,
            save_video=args.video,
            save_thumbnail=args.save_thumbnail,
            show=args.show,
            playlist_mode=(
                "channel"
                if args.playlist_channel
                else ("pending" if args.playlist else None)
            ),
            playlist_path=args.playlist_file,
        )
        processor.process(job_or_source)


if __name__ == "__main__":
    main()
