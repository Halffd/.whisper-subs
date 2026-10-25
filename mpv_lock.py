#!/usr/bin/env python3
"""Single-instance guard for the mpv preview window.

`--mpv` can fire from more than one place: whisper_subs.launch_mpv()
before transcription, and transcribe.py on the FIRST_SEGMENT_WRITTEN
marker. try_transcribe() is also called repeatedly (model fallback,
loop retry, two-pass), so the marker can be seen once per pass and the
player was reopened each time.

The lock is keyed on the media being played, so switching to the next
video opens a fresh window while re-entering the same video does not.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Sequence

# One launch per media for this long. Covers a full transcription pass:
# the window is meant to stay open while subtitles stream into it.
_LOCK_TTL_SECONDS = 6 * 60 * 60

# Process-wide registry. transcribe.py and whisper_subs.py both import
# this module, so the guard holds for the whole run.
_claims: Dict[str, float] = {}


def _lock_path(key: str) -> str:
    import hashlib

    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return os.path.join(tempfile.gettempdir(), f".whispersubs-mpv-{digest}.lock")


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _claim_file(key: str, pid: int) -> bool:
    """Record ownership in a lock file so other processes respect it."""
    path = _lock_path(key)
    try:
        now = time.time()
        if os.path.exists(path):
            age = now - os.path.getmtime(path)
            if age < _LOCK_TTL_SECONDS:
                with open(path, "r", encoding="utf-8") as f:
                    existing = f.read().strip()
                if existing.isdigit() and int(existing) != pid:
                    if _is_running(int(existing)):
                        return False
                elif not existing.isdigit():
                    return False
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(pid))
        return True
    except OSError:
        # A missing lock is not a reason to skip playback.
        return True


def claim(key: str) -> bool:
    """True when the caller owns the player for `key` and may launch it."""
    if not key:
        return True

    now = time.time()
    previous = _claims.get(key)
    if previous is not None and now - previous < _LOCK_TTL_SECONDS:
        return False

    if not _claim_file(key, os.getpid()):
        return False

    _claims[key] = now
    return True


def release(key: str) -> None:
    """Drop the in-process claim (the lock file is left to expire)."""
    _claims.pop(key, None)


def launch(
    media_source: str,
    srt_file: Optional[str] = None,
    socket_path: str = "/tmp/mpvsocket",
    playlist: Optional[str] = None,
    extra_args: Optional[Sequence[str]] = None,
    log_file: Optional[str] = None,
) -> Optional[subprocess.Popen]:
    """Launch mpv once per media source.

    When `log_file` is given the player's stdout and stderr are written
    there instead of being discarded, so a player that fails to open its
    media (a dead URL, a missing ytdl extractor) leaves evidence behind
    instead of exiting silently.

    Returns the Popen handle, or None when the player was already open
    for this media or the launch failed.
    """
    key = media_source or ""
    if not claim(key):
        return None

    cmd: List[str] = [
        "mpv",
        media_source,
        "--pause",
        f"--input-ipc-server={socket_path}",
        "--really-quiet",
    ]
    if srt_file:
        cmd.append(f"--sub-file={srt_file}")
    if playlist:
        cmd.append(f"--playlist={playlist}")
    if extra_args:
        cmd.extend(extra_args)

    try:
        if log_file:
            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
            # The handle has to stay open for the player's lifetime; it is
            # closed by the watcher when mpv exits.
            handle = open(log_file, "w", encoding="utf-8")
            process = subprocess.Popen(
                cmd,
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
            process.log_handle = handle  # type: ignore[attr-defined]
            return process
        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, ValueError):
        release(key)
        return None
