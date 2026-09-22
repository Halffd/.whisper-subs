"""
Downloads - server-side yt-dlp video downloads for in-app playback.

The phone (or web) starts a download via POST /api/v1/download, polls status,
then plays the finished file through /api/v1/media/file?path=.

Public API:
    start_download(source) -> dict  (download_id + initial status)
    get_download(download_id) -> dict
    list_downloads() -> dict
    clear_finished(max_age=3600)
"""

import os
import re
import time
import threading
import hashlib
from typing import Dict, Any, Optional

import yt_dlp

from .channels import COOKIES_BROWSER, OUTPUT_DIR_DEFAULT

_downloads: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()

MAX_CONCURRENT = 3


def _output_dir() -> str:
    return os.environ.get("WHISPER_OUTPUT_DIR", OUTPUT_DIR_DEFAULT)


def _ytdlp_opts() -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 15,
        "no_check_certificate": True,
        "noplaylist": True,
        # Best combined mp4 for direct playback; fall back to best
        "format": "best[ext=mp4]/best",
        # Channel dir + title [id] naming (integrates with channels scan)
        "outtmpl": os.path.join(
            _output_dir(),
            "%(channel,uploader,uploader_id)s",
            "%(title).100B [%(id)s].%(ext)s",
        ),
        "restrictfilenames": False,
        "windowsfilenames": True,  # safe on all platforms
    }
    browser = COOKIES_BROWSER
    if browser:
        try:
            opts["cookiesfrombrowser"] = (browser,)
        except Exception:
            pass
    return opts


def _make_download_id(source: str) -> str:
    return "dl_" + hashlib.md5(f"{source}_{time.time()}".encode()).hexdigest()[:12]


def _update(download_id: str, **fields) -> None:
    with _lock:
        entry = _downloads.get(download_id)
        if entry is None:
            return
        entry.update(fields)
        entry["updated_at"] = time.time()


def _progress_hook(download_id: str):
    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            progress = (done / total) if total else None
            speed = d.get("speed")
            _update(
                download_id,
                status="processing",
                progress=progress,
                speed_mbps=round(speed / (1024 * 1024), 2) if speed else None,
                downloaded_mb=round(done / (1024 * 1024), 2),
            )
        elif d.get("status") == "finished":
            _update(download_id, status="merging", progress=0.99)

    return hook


def _run_download(download_id: str, source: str) -> None:
    try:
        _update(download_id, status="processing", started_at=time.time())

        opts = _ytdlp_opts()
        opts["progress_hooks"] = [_progress_hook(download_id)]

        # Capture the resolved channel + title up front
        try:
            probe = dict(_ytdlp_opts())
            probe["skip_download"] = True
            probe["extract_flat"] = False
            with yt_dlp.YoutubeDL(probe) as ydl:
                info = ydl.extract_info(source, download=False)
            if info:
                _update(
                    download_id,
                    title=info.get("title"),
                    channel=info.get("channel") or info.get("uploader"),
                    duration=info.get("duration"),
                    thumbnail=info.get("thumbnail"),
                )
        except Exception:
            pass  # probe is best-effort; download itself validates

        with yt_dlp.YoutubeDL(opts) as ydl:
            result = ydl.extract_info(source, download=True)

        # Locate the finished file
        file_path = None
        if result:
            requested = result.get("requested_downloads") or []
            if requested:
                file_path = requested[0].get("filepath")
            if not file_path:
                file_path = ydl.prepare_filename(result)

        if not file_path or not os.path.exists(file_path):
            _update(
                download_id,
                status="failed",
                error="Download finished but file not found",
            )
            return

        _update(
            download_id,
            status="completed",
            progress=1.0,
            file_path=file_path,
            rel_path=os.path.relpath(file_path, _output_dir()).replace(os.sep, "/"),
            completed_at=time.time(),
        )
    except Exception as e:
        _update(download_id, status="failed", error=str(e)[:500])


def start_download(source: str) -> Dict[str, Any]:
    """Start a background yt-dlp download. Returns download info dict."""
    source = source.strip()
    if not source:
        raise ValueError("Empty source URL")

    # Reuse an existing active download for the same source
    with _lock:
        for entry in _downloads.values():
            if entry.get("source") == source and entry.get("status") in (
                "pending",
                "processing",
                "merging",
            ):
                return dict(entry)

    download_id = _make_download_id(source)
    with _lock:
        active = sum(
            1
            for e in _downloads.values()
            if e.get("status") in ("pending", "processing", "merging")
        )
        _downloads[download_id] = {
            "download_id": download_id,
            "source": source,
            "status": "pending",
            "progress": None,
            "title": None,
            "channel": None,
            "file_path": None,
            "rel_path": None,
            "error": None,
            "created_at": time.time(),
        }

    if active >= MAX_CONCURRENT:
        # Simple queue: still start a thread; yt-dlp calls are independent
        # but we mark it queued for UI clarity.
        _update(download_id, status="pending")

    thread = threading.Thread(
        target=_run_download, args=(download_id, source), daemon=True
    )
    thread.start()
    return dict(_downloads[download_id])


def get_download(download_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        entry = _downloads.get(download_id)
        if entry is None:
            return None
        return dict(entry)


def list_downloads() -> Dict[str, Any]:
    with _lock:
        entries = [dict(e) for e in _downloads.values()]
    entries.sort(key=lambda e: e.get("created_at") or 0, reverse=True)
    active = [
        e for e in entries if e.get("status") in ("pending", "processing", "merging")
    ]
    return {"downloads": entries, "count": len(entries), "active": len(active)}


def clear_finished(max_age: int = 3600) -> int:
    """Remove finished/failed downloads older than max_age seconds."""
    now = time.time()
    removed = 0
    with _lock:
        for key in list(_downloads.keys()):
            entry = _downloads[key]
            if entry.get("status") in ("completed", "failed"):
                if (
                    now - (entry.get("updated_at") or entry.get("created_at") or 0)
                    > max_age
                ):
                    _downloads.pop(key, None)
                    removed += 1
    return removed
