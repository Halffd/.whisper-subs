#!/usr/bin/env python3
"""mpv playlist (m3u) building for `--playlist` and `--playlist-channel`.

mpv reads `--playlist=<file>` once at startup, so entries discovered
later have to be appended and picked up while the player runs. mpv
reloads a playlist when the file grows, which is what makes "add the
next videos as each transcription finishes" work.

Entries carry the media URL and its subtitle as an `#EXTINF`-less pair,
matching the format helper_files.create_playlist() already writes:

    #EXTM3U
    #EXTINF:-1,<title>
    <url or path>
    #EXTINF:-1,Subtitles
    <absolute subtitle path>
"""

from __future__ import annotations

import os
import threading
from typing import List, Optional, Tuple


class Playlist:
    """An m3u playlist that can be appended to while mpv is running."""

    def __init__(self, path: str, title: str = "playlist"):
        self.path = path
        self.title = title
        self._lock = threading.Lock()
        self._entries: List[Tuple[str, str]] = []  # (media, srt) pairs
        self._dir = os.path.dirname(path) or "."
        os.makedirs(self._dir, exist_ok=True)
        if not os.path.exists(path):
            self._write([])

    def _format(self, entries: List[Tuple[str, str]]) -> str:
        lines = ["#EXTM3U"]
        for media, srt in entries:
            title = os.path.basename(media)
            lines.append(f"#EXTINF:-1,{title}")
            lines.append(media)
            if srt:
                lines.append("#EXTINF:-1,Subtitles")
                lines.append(srt)
        return "\n".join(lines) + "\n"

    def _write(self, entries: List[Tuple[str, str]]) -> None:
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(self._format(entries))
        # Atomic replace: mpv must never read a half-written playlist.
        os.replace(tmp, self.path)

    def _has(self, media: str) -> bool:
        """Duplicate check. Caller must already hold the lock."""
        return any(m == media for m, _ in self._entries)

    def contains(self, media: str) -> bool:
        with self._lock:
            return self._has(media)

    def append(self, media: str, srt: Optional[str] = None) -> bool:
        """Add one entry. Returns False when it is already present."""
        if not media:
            return False
        with self._lock:
            if self._has(media):
                return False
            self._entries.append((media, srt or ""))
            self._write(self._entries)
            return True

    def extend(self, items: List[Tuple[str, Optional[str]]]) -> int:
        """Add several entries, skipping duplicates. Returns the count added."""
        added = 0
        with self._lock:
            for media, srt in items:
                if media and not self._has(media):
                    self._entries.append((media, srt or ""))
                    added += 1
            if added:
                self._write(self._entries)
        return added

    def entries(self) -> List[Tuple[str, str]]:
        with self._lock:
            return list(self._entries)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
