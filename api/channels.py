"""
Channels - serve the existing OUTPUT_DIR (Youtube-Subs) as a channel tree.

Scans `<OUTPUT_DIR>/<channel>/<date>_<title>.<model>.srt` structures, pairs
them with helper files (.htm URL, media, thumbnails), and merges with the
channel's remote video list (yt-dlp flat playlist) to show untranscribed
videos.

Public API:
    scan_channels() -> List[dict]
    scan_channel(channel) -> dict (transcribed videos + metadata)
    channel_remote(channel, refresh) -> dict (remote video list + channel info)
    video_stats(url) -> dict (views, likes, duration; cached)
"""

import json
import os
import re
import time
import threading
import hashlib
from typing import Optional, Dict, Any, List

import yt_dlp

OUTPUT_DIR_DEFAULT = os.path.expanduser("~/Documents/Youtube-Subs")
COOKIES_BROWSER = os.environ.get("WHISPER_COOKIES_BROWSER", "firefox")

CACHE_DIR = os.path.expanduser("~/.cache/whisper-subs/channels")
CHANNEL_TTL = 24 * 3600  # channel info + video list
VIDEO_TTL = 6 * 3600  # per-video stats

TITLE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:_(\d{2}-\d{2}))?_(.+)$")
URL_RE = re.compile(r"URL='([^']+)'")
YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{6,})")

_lock = threading.Lock()
_channel_cache: Dict[
    str, Dict[str, Any]
] = {}  # channel -> {"info":..., "videos":..., "at":...}
_stats_cache: Dict[str, Dict[str, Any]] = {}  # url -> {"stats":..., "at":...}


def _output_dir() -> str:
    return os.environ.get("WHISPER_OUTPUT_DIR", OUTPUT_DIR_DEFAULT)


def _ytdlp_base_opts() -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 15,
        "no_check_certificate": True,
    }
    browser = COOKIES_BROWSER
    if browser:
        try:
            opts["cookiesfrombrowser"] = (browser,)
        except Exception:
            pass
    return opts


# ---------------------------------------------------------------------------
# Filesystem scanning
# ---------------------------------------------------------------------------


def _extract_url_from_base(base: str) -> Optional[str]:
    """Source URL from the .htm/.bat/.sh helper files."""
    for suffix in (".htm", ".html", ".sh", ".bat"):
        helper = f"{base}{suffix}"
        if not os.path.exists(helper):
            continue
        try:
            content = open(helper, encoding="utf-8", errors="ignore").read(4000)
            m = URL_RE.search(content)
            if m:
                return m.group(1)
        except Exception:
            continue
    return None


def _strip_model(base_name: str) -> tuple:
    """Split '<title>.<model>' -> (title, model). Uses known model names."""
    import model as model_mod

    known = [m.replace(":", "_") for m in getattr(model_mod, "ALL_MODEL_NAMES", [])]
    # Common aliases not in ALL_MODEL_NAMES
    known += [
        "large-v3-turbo",
        "large-v3",
        "large-v2",
        "large",
        "medium",
        "small",
        "base",
        "tiny",
        "small.en",
        "base.en",
        "tiny.en",
        "medium.en",
        "distil-large-v3",
        "distil-small.en",
        "distil-medium.en",
    ]
    for m in sorted(set(known), key=len, reverse=True):
        if base_name.endswith(f".{m}"):
            return base_name[: -(len(m) + 1)], m
    # Fallback: single-dot tail that looks like a model (alphanumeric, <= 20 chars)
    if "." in base_name:
        title, tail = base_name.rsplit(".", 1)
        if re.fullmatch(r"[\w-]{1,20}", tail) and tail.lower() not in ("srt",):
            return title, tail
    return base_name, None


def scan_channels() -> List[Dict[str, Any]]:
    """List channels (subdirectories of OUTPUT_DIR) with counts."""
    root = _output_dir()
    if not os.path.isdir(root):
        return []

    channels = []
    for name in sorted(os.listdir(root)):
        chdir = os.path.join(root, name)
        if not os.path.isdir(chdir):
            continue
        transcribed = 0
        unfinished = 0
        for f in os.listdir(chdir):
            if (
                f.endswith(".srt")
                and not re.search(r"[.-]unfinished\.srt$", f)
                and not os.path.islink(os.path.join(chdir, f))
            ):
                transcribed += 1
            elif ".unfinished.srt" in f:
                unfinished += 1
        channels.append(
            {
                "name": name,
                "transcribed": transcribed,
                "unfinished": unfinished,
            }
        )
    return [c for c in channels if c["transcribed"] or c["unfinished"]]


def scan_channel(channel: str) -> Dict[str, Any]:
    """Scan one channel directory for transcribed videos + metadata."""
    root = _output_dir()
    chdir = os.path.join(root, channel)
    if not os.path.isdir(chdir):
        raise FileNotFoundError(f"Channel not found: {channel}")

    videos = []
    seen_bases = set()
    for f in sorted(os.listdir(chdir)):
        if not f.endswith(".srt") or re.search(r"[.-]unfinished\.srt$", f):
            continue
        if os.path.islink(os.path.join(chdir, f)):
            continue

        base = os.path.splitext(f)[0]
        if base in seen_bases:
            continue
        seen_bases.add(base)

        m = TITLE_RE.match(base)
        if m:
            date, timepart, rest = m.groups()
        else:
            date, timepart, rest = None, None, base

        title, model_name = _strip_model(rest)

        srt_path = os.path.join(chdir, f)
        source_url = _extract_url_from_base(base_path := os.path.join(chdir, base))

        # Sibling media + thumbnail
        media = []
        thumb = None
        for sf in os.listdir(chdir):
            if not sf.startswith(base):
                continue
            ext = os.path.splitext(sf)[1].lower()
            full = os.path.join(chdir, sf)
            if ext in (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts"):
                media.append({"type": "video", "format": ext[1:]})
            elif ext in (".m4a", ".mp3", ".wav", ".ogg", ".opus", ".flac", ".aac"):
                media.append({"type": "audio", "format": ext[1:]})
            elif ext in (".webp", ".jpg", ".jpeg", ".png") and thumb is None:
                thumb = full

        video_id = None
        if source_url:
            im = YT_ID_RE.search(source_url)
            if im:
                video_id = im.group(1)

        rel = os.path.relpath(srt_path, root).replace(os.sep, "/")
        videos.append(
            {
                "id": rel,
                "title": title,
                "date": date,
                "model": model_name,
                "video_id": video_id,
                "source_url": source_url,
                "has_srt": True,
                "has_media": bool(media),
                "media": media,
                "has_thumbnail": thumb is not None,
                "thumbnail_url": (
                    "/api/v1/thumb/file?path="
                    + os.path.relpath(thumb, root).replace(os.sep, "/")
                    if thumb
                    else None
                ),
                "srt_url": f"/api/v1/subs/file?path={rel}",
                "duration": None,  # filled from remote list if matched
                "views": None,
                "likes": None,
            }
        )

    videos.sort(key=lambda v: v["date"] or "", reverse=True)
    return {"channel": channel, "videos": videos}


# ---------------------------------------------------------------------------
# Remote (yt-dlp) resolution
# ---------------------------------------------------------------------------


def _resolve_channel_url(sample_url: str) -> Optional[str]:
    """Resolve the channel page URL from a single video URL (cached)."""
    with _lock:
        cached = _channel_cache.get(f"__churl_{sample_url}")
        if cached and time.time() - cached["at"] < CHANNEL_TTL:
            return cached.get("url")

    try:
        opts = _ytdlp_base_opts()
        opts["skip_download"] = True
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(sample_url, download=False)
        channel_url = None
        if info:
            channel_url = info.get("channel_url") or info.get("uploader_url")
        with _lock:
            _channel_cache[f"__churl_{sample_url}"] = {
                "url": channel_url,
                "at": time.time(),
            }
        return channel_url
    except Exception:
        with _lock:
            _channel_cache[f"__churl_{sample_url}"] = {"url": None, "at": time.time()}
        return None


def _fetch_channel_remote(channel_url: str, refresh: bool = False) -> Dict[str, Any]:
    """Fetch channel info + flat video list via yt-dlp (cached CHANNEL_TTL)."""
    with _lock:
        cached = _channel_cache.get(channel_url)
        if cached and not refresh and time.time() - cached["at"] < CHANNEL_TTL:
            return cached

    # Channel root URL yields tab entries ("X - Videos"); request the videos tab
    fetch_url = channel_url
    if "youtube.com/channel/" in channel_url or "youtube.com/@" in channel_url:
        fetch_url = channel_url.rstrip("/") + "/videos"

    opts = _ytdlp_base_opts()
    opts["extract_flat"] = "in_playlist"
    opts["skip_download"] = True

    result: Dict[str, Any] = {
        "entries": [],
        "channel_name": None,
        "avatar": None,
        "subscribers": None,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
        if info:
            result["channel_name"] = (
                info.get("channel") or info.get("uploader") or info.get("title")
            )
            result["subscribers"] = info.get("channel_follower_count")
            avatars = info.get("thumbnails") or []
            if avatars:
                best = max(avatars, key=lambda t: t.get("preference") or 0)
                result["avatar"] = best.get("url")

            # Videos tab flat playlist (channel root returns tabs instead)
            entries_raw: List[Any] = []
            if fetch_url != channel_url:
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl2:
                        tab_info = ydl2.extract_info(fetch_url, download=False)
                    entries_raw = (
                        list(tab_info.get("entries") or []) if tab_info else []
                    )
                except Exception:
                    entries_raw = []
            else:
                entries_raw = list(info.get("entries") or [])

            entries = []
            for e in entries_raw:
                if not e:
                    continue
                # Skip playlist/tab entries (channel root fallback)
                ie_key = str(e.get("ie_key") or e.get("_type") or "")
                if "tab" in ie_key.lower() or "playlist" in ie_key.lower():
                    continue
                thumbs = e.get("thumbnails") or []
                thumb_url = e.get("thumbnail")
                if not thumb_url and thumbs:
                    best = max(thumbs, key=lambda t: t.get("preference") or 0)
                    thumb_url = best.get("url")
                entries.append(
                    {
                        "id": e.get("id"),
                        "title": e.get("title"),
                        "duration": e.get("duration"),
                        "views": e.get("view_count"),
                        "thumbnail_url": thumb_url,
                        "url": e.get("url") or e.get("webpage_url"),
                        "upload_date": None,
                    }
                )
            result["entries"] = entries
    except Exception:
        pass  # offline / private / failure -> empty entries, transcribed still shown

    with _lock:
        _channel_cache[channel_url] = {**result, "at": time.time()}
    return result


def channel_remote(channel: str, refresh: bool = False) -> Dict[str, Any]:
    """Remote video list for a channel dir, resolved via its videos' URLs."""
    data = scan_channel(channel)
    sample_url = next(
        (v["source_url"] for v in data["videos"] if v["source_url"]), None
    )
    if not sample_url:
        return {
            "channel": channel,
            "entries": [],
            "channel_name": None,
            "avatar": None,
            "subscribers": None,
            "channel_url": None,
        }

    channel_url = _resolve_channel_url(sample_url)
    if not channel_url:
        return {
            "channel": channel,
            "entries": [],
            "channel_name": None,
            "avatar": None,
            "subscribers": None,
            "channel_url": None,
        }

    remote = _fetch_channel_remote(channel_url, refresh=refresh)
    remote["channel_url"] = channel_url
    remote["channel"] = channel
    return remote


def video_stats(url: str, refresh: bool = False) -> Dict[str, Any]:
    """Full per-video stats: views, likes, duration, upload_date (cached)."""
    with _lock:
        cached = _stats_cache.get(url)
        if cached and not refresh and time.time() - cached["at"] < VIDEO_TTL:
            return cached["stats"]

    opts = _ytdlp_base_opts()
    opts["skip_download"] = True
    stats: Dict[str, Any] = {
        "url": url,
        "title": None,
        "views": None,
        "likes": None,
        "duration": None,
        "upload_date": None,
        "channel": None,
        "thumbnail": None,
        "description": None,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info:
            stats.update(
                {
                    "title": info.get("title"),
                    "views": info.get("view_count"),
                    "likes": info.get("like_count"),
                    "duration": info.get("duration"),
                    "upload_date": info.get("upload_date"),
                    "channel": info.get("channel") or info.get("uploader"),
                    "thumbnail": info.get("thumbnail"),
                    "description": (info.get("description") or "")[:500],
                }
            )
    except Exception:
        pass

    with _lock:
        _stats_cache[url] = {"stats": stats, "at": time.time()}
    return stats


# ---------------------------------------------------------------------------
# Merged view: transcribed + untranscribed
# ---------------------------------------------------------------------------


def channel_videos_merged(channel: str, refresh: bool = False) -> Dict[str, Any]:
    """Merge local transcribed videos with the channel's remote video list."""
    local = scan_channel(channel)
    remote = channel_remote(channel, refresh=refresh)

    # Index local by video_id
    by_id: Dict[str, Dict[str, Any]] = {}
    for v in local["videos"]:
        if v["video_id"]:
            by_id[v["video_id"]] = v

    merged: List[Dict[str, Any]] = []
    seen_ids = set()
    for e in remote.get("entries") or []:
        vid = e.get("id")
        seen_ids.add(vid)
        local_v = by_id.get(vid)
        if local_v:
            merged.append(
                {
                    **local_v,
                    "duration": e.get("duration"),
                    "views": e.get("views"),
                    "transcribed": True,
                    # Remote thumb when local file has none
                    "thumbnail_url": local_v.get("thumbnail_url")
                    or (
                        f"/api/v1/thumb/proxy?url={e['thumbnail_url']}"
                        if e.get("thumbnail_url")
                        else None
                    ),
                    "has_thumbnail": local_v.get("has_thumbnail")
                    or bool(e.get("thumbnail_url")),
                }
            )
        else:
            merged.append(
                {
                    "id": vid,
                    "title": e.get("title"),
                    "date": None,
                    "model": None,
                    "video_id": vid,
                    "source_url": e.get("url"),
                    "has_srt": False,
                    "has_media": False,
                    "media": [],
                    "has_thumbnail": bool(e.get("thumbnail_url")),
                    "thumbnail_url": (
                        f"/api/v1/thumb/proxy?url={e['thumbnail_url']}"
                        if e.get("thumbnail_url")
                        else None
                    ),
                    "srt_url": None,
                    "duration": e.get("duration"),
                    "views": e.get("views"),
                    "likes": None,
                    "transcribed": False,
                }
            )

    # Local videos not in remote list (deleted privately, or remote fetch failed)
    for v in local["videos"]:
        if v["video_id"] and v["video_id"] not in seen_ids:
            merged.append({**v, "transcribed": True})
        elif not v["video_id"]:
            merged.append({**v, "transcribed": True})

    merged.sort(key=lambda v: v.get("date") or "", reverse=True)

    return {
        "channel": channel,
        "channel_name": remote.get("channel_name"),
        "channel_url": remote.get("channel_url"),
        "subscribers": remote.get("subscribers"),
        "avatar_url": (
            f"/api/v1/channels/{channel}/icon" if remote.get("avatar") else None
        ),
        "videos": merged,
        "total": len(merged),
        "transcribed_count": sum(1 for v in merged if v.get("transcribed")),
    }


def clear_caches() -> None:
    with _lock:
        _channel_cache.clear()
        _stats_cache.clear()
