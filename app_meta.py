"""Application build info and subtitle metadata.

Every `.metadata.json` written next to a subtitle is built here, so all
transcription paths (subprocess worker, in-process, adapters) produce the
same shape: transcription settings, source video/channel facts, and the
build that produced the file.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
from typing import Any, Dict, List, Optional

APP_VERSION = "3.0.0"

_commit_hash_cache: Optional[str] = None


def get_commit_hash() -> str:
    """Short hash of the checked-out commit, or "unknown" outside a git repo."""
    global _commit_hash_cache
    if _commit_hash_cache is not None:
        return _commit_hash_cache

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        commit = result.stdout.strip()
        _commit_hash_cache = commit if result.returncode == 0 and commit else "unknown"
    except Exception:
        _commit_hash_cache = "unknown"

    return _commit_hash_cache


def get_build_info() -> Dict[str, str]:
    """Version and commit of the code that produced a file."""
    return {"version": APP_VERSION, "commit_hash": get_commit_hash()}


def _pick_thumbnail(thumbnails: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """Picks the highest-preference thumbnail URL from a yt-dlp thumbnails list."""
    if not thumbnails:
        return None

    def rank(thumb: Dict[str, Any]) -> tuple:
        return (
            thumb.get("preference", -100),
            thumb.get("width") or 0,
            thumb.get("height") or 0,
        )

    best = max(thumbnails, key=rank)
    return best.get("url") or None


def _iso_from_epoch(epoch: Any) -> Optional[str]:
    """Converts a yt-dlp epoch timestamp to ISO 8601, or None when unusable."""
    if not epoch:
        return None
    try:
        return datetime.datetime.fromtimestamp(int(epoch)).astimezone().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _iso_from_date(value: Any) -> Optional[str]:
    """Converts a yt-dlp YYYYMMDD date to ISO 8601, or None when unusable."""
    if not value or len(str(value)) != 8:
        return None
    try:
        return datetime.datetime.strptime(str(value), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def build_source_info(
    info: Optional[Dict[str, Any]],
    source_url: str = "",
    channel_thumbnail_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Extracts the video, channel and statistics fields stored with a subtitle.

    `info` is a yt-dlp info dict. Missing values become None rather than
    guessed defaults, so consumers can tell "not published" from "zero".
    """
    info = info or {}

    upload_timestamp = (
        _iso_from_epoch(info.get("timestamp"))
        or _iso_from_epoch(info.get("release_timestamp"))
        or _iso_from_date(info.get("upload_date"))
    )

    return {
        "source_url": source_url or info.get("webpage_url") or info.get("original_url"),
        "video_id": info.get("id"),
        "title": info.get("title"),
        "channel_name": info.get("channel")
        or info.get("uploader")
        or info.get("channel_name"),
        "channel_id": info.get("channel_id"),
        "channel_url": info.get("channel_url") or info.get("uploader_url"),
        "thumbnail_url": info.get("thumbnail")
        or _pick_thumbnail(info.get("thumbnails")),
        "channel_thumbnail_url": channel_thumbnail_url
        or info.get("channel_thumbnail")
        or _pick_thumbnail(info.get("channel_thumbnails")),
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "dislikes": info.get("dislike_count"),
        "comments_count": info.get("comment_count"),
        "upload_timestamp": upload_timestamp,
        "duration_seconds": info.get("duration"),
        "has_human_subs": bool(info.get("subtitles")),
        "has_automatic_subs": bool(info.get("automatic_captions")),
    }


def write_metadata(
    srt_file: str,
    transcription_info: Dict[str, Any],
    source_info: Optional[Dict[str, Any]] = None,
) -> str:
    """Writes <name>.metadata.json next to the subtitle and returns its path.

    Transcription facts win over source facts for shared keys such as
    duration, because they describe the audio that was actually transcribed.
    """
    metadata: Dict[str, Any] = dict(source_info or {})
    metadata.update(transcription_info)

    now = datetime.datetime.now().astimezone().isoformat()
    metadata.setdefault("date", now)
    metadata["transcription_timestamp"] = now
    metadata.update(get_build_info())

    metadata_file = os.path.splitext(srt_file)[0] + ".metadata.json"
    os.makedirs(os.path.dirname(metadata_file) or ".", exist_ok=True)

    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return metadata_file
