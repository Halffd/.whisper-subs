"""
Search - unified search across subtitles, YouTube, and Twitch.

Public API:
    search_subtitles(query, channel=None, limit=50) -> List[dict]
        Content search across transcribed SRT files (timestamp + snippet).
    search_youtube(query, limit=10) -> List[dict]
        Online YouTube search via yt-dlp ytsearch.
    search_twitch(channel, query=None, vod_type="all", sort="date") -> dict
        Channel VODs + live stream, filtered/sorted.
"""

import os
import re
import time
import threading
from typing import Optional, Dict, Any, List

import yt_dlp

from .channels import (
    COOKIES_BROWSER,
    OUTPUT_DIR_DEFAULT,
    TITLE_RE,
    _output_dir,
    _ytdlp_base_opts,
    _strip_model,
)

SEARCH_CACHE_TTL = 10 * 60
_lock = threading.Lock()
_yt_cache: Dict[str, Dict[str, Any]] = {}
_twitch_cache: Dict[str, Dict[str, Any]] = {}


def _cache_get(cache: Dict[str, Dict[str, Any]], key: str) -> Optional[Any]:
    with _lock:
        entry = cache.get(key)
        if entry and time.time() - entry["at"] < SEARCH_CACHE_TTL:
            return entry["data"]
        if entry:
            cache.pop(key, None)
    return None


def _cache_put(cache: Dict[str, Dict[str, Any]], key: str, data: Any) -> None:
    with _lock:
        cache[key] = {"data": data, "at": time.time()}


# ---------------------------------------------------------------------------
# Subtitle content search
# ---------------------------------------------------------------------------


def _snippet(line: str, query: str, width: int = 80) -> str:
    """Center a snippet of the matching line around the query hit."""
    idx = line.lower().find(query.lower())
    if idx < 0:
        return line[:width]
    start = max(0, idx - width // 2)
    end = min(len(line), start + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(line) else ""
    return prefix + line[start:end] + suffix


def search_subtitles(
    query: str,
    channel: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Search transcribed SRT content. Returns matches with timestamp + snippet."""
    query = query.strip()
    if not query:
        return []

    root = _output_dir()
    if not os.path.isdir(root):
        return []

    results: List[Dict[str, Any]] = []
    q_lower = query.lower()

    channels_to_scan: List[str]
    if channel:
        channels_to_scan = [channel]
    else:
        channels_to_scan = [
            d for d in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root, d))
        ]

    for ch in channels_to_scan:
        chdir = os.path.join(root, ch)
        if not os.path.isdir(chdir):
            continue
        for fname in sorted(os.listdir(chdir)):
            if not fname.endswith(".srt"):
                continue
            if re.search(r"[.-]unfinished\.srt$", fname):
                continue
            if os.path.islink(os.path.join(chdir, fname)):
                continue

            srt_path = os.path.join(chdir, fname)
            try:
                content = open(srt_path, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue

            matches = _srt_matches(content, q_lower)
            if not matches:
                continue

            base = os.path.splitext(fname)[0]
            m = TITLE_RE.match(base)
            date, _timepart, rest = m.groups() if m else (None, None, base)
            title, model_name = _strip_model(rest)

            rel = os.path.relpath(srt_path, root).replace(os.sep, "/")
            results.append(
                {
                    "id": rel,
                    "title": title,
                    "channel": ch,
                    "date": date,
                    "model": model_name,
                    "match_count": len(matches),
                    "matches": matches[:5],  # first 5 (timestamp + snippet)
                    "srt_url": f"/api/v1/subs/file?path={rel}",
                    "play_url": None,  # filled by endpoint if media exists
                }
            )

    results.sort(key=lambda r: (-(r["match_count"]), r["date"] or ""))
    return results[:limit]


def _srt_matches(
    content: str, q_lower: str, max_matches: int = 20
) -> List[Dict[str, Any]]:
    """Extract (timestamp, snippet) matches from SRT content."""
    matches = []
    blocks = re.split(r"\n\s*\n", content)
    for block in blocks:
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        timestamp = ""
        text_lines = []
        for line in lines:
            if "-->" in line:
                timestamp = line
            elif not re.fullmatch(r"\d+", line):
                text_lines.append(line)
        text = " ".join(text_lines)
        if q_lower in text.lower():
            matches.append(
                {
                    "timestamp": timestamp,
                    "snippet": _snippet(text, q_lower),
                }
            )
            if len(matches) >= max_matches:
                break
    return matches


# ---------------------------------------------------------------------------
# YouTube search
# ---------------------------------------------------------------------------


def search_youtube(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Online YouTube search via yt-dlp. Returns flat video entries."""
    query = query.strip()
    if not query:
        return []

    cache_key = f"yt_{limit}_{query}"
    cached = _cache_get(_yt_cache, cache_key)
    if cached is not None:
        return cached

    opts = _ytdlp_base_opts()
    opts["extract_flat"] = True
    opts["skip_download"] = True

    entries: List[Dict[str, Any]] = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        for e in info.get("entries") or []:
            if not e:
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
                    "channel": e.get("channel") or e.get("uploader"),
                    "live": bool(e.get("live_status")),
                }
            )
    except Exception:
        pass  # offline -> empty results

    _cache_put(_yt_cache, cache_key, entries)
    return entries


# ---------------------------------------------------------------------------
# Twitch search (channel VODs + live, filter/sort)
# ---------------------------------------------------------------------------


def search_twitch(
    channel: str,
    query: Optional[str] = None,
    vod_type: str = "all",  # all | vod | live
    sort: str = "date",  # date | views | duration | title
) -> Dict[str, Any]:
    """List a Twitch channel's live stream + VODs, filtered and sorted."""
    channel = channel.strip().lstrip("@").split("/")[0]
    if not channel:
        return {"live": None, "vods": [], "total": 0}

    cache_key = f"tw_{channel}"
    cached = _cache_get(_twitch_cache, cache_key)
    if cached:
        data = cached
    else:
        data = _fetch_twitch_channel(channel)
        _cache_put(_twitch_cache, cache_key, data)

    live = data.get("live")
    vods = list(data.get("vods") or [])

    # Filter
    if vod_type == "live":
        vods = []
    elif vod_type == "vod":
        live = None

    q_lower = (query or "").strip().lower()
    if q_lower:
        if live and q_lower not in (live.get("title") or "").lower():
            live = None
        vods = [v for v in vods if q_lower in (v.get("title") or "").lower()]

    # Sort
    if sort == "views":
        vods.sort(key=lambda v: v.get("views") or 0, reverse=True)
    elif sort == "duration":
        vods.sort(key=lambda v: v.get("duration") or 0, reverse=True)
    elif sort == "title":
        vods.sort(key=lambda v: (v.get("title") or "").lower())
    else:  # date
        vods.sort(key=lambda v: v.get("date") or "", reverse=True)

    return {"live": live, "vods": vods, "total": len(vods), "channel": channel}


def _fetch_twitch_channel(channel: str) -> Dict[str, Any]:
    """Fetch Twitch channel live status + VOD list via yt-dlp."""
    result: Dict[str, Any] = {"live": None, "vods": []}

    opts = _ytdlp_base_opts()
    opts["skip_download"] = True

    # Live status: extract the channel page itself
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.twitch.tv/{channel}", download=False)
        if info and info.get("is_live"):
            thumbs = info.get("thumbnails") or []
            thumb_url = info.get("thumbnail")
            if not thumb_url and thumbs:
                best = max(thumbs, key=lambda t: t.get("preference") or 0)
                thumb_url = best.get("url")
            result["live"] = {
                "id": info.get("id"),
                "title": info.get("title"),
                "url": f"https://www.twitch.tv/{channel}",
                "views": info.get("view_count"),
                "thumbnail_url": thumb_url,
                "duration": None,
                "date": None,
            }
    except Exception:
        pass  # offline or blocked -> no live

    # VODs: flat playlist of /videos
    vod_opts = dict(opts)
    vod_opts["extract_flat"] = "in_playlist"
    try:
        with yt_dlp.YoutubeDL(vod_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.twitch.tv/{channel}/videos", download=False
            )
        for e in info.get("entries") or []:
            if not e:
                continue
            thumbs = e.get("thumbnails") or []
            thumb_url = e.get("thumbnail")
            if not thumb_url and thumbs:
                best = max(thumbs, key=lambda t: t.get("preference") or 0)
                thumb_url = best.get("url")
            upload_date = e.get("upload_date")
            result["vods"].append(
                {
                    "id": e.get("id"),
                    "title": e.get("title"),
                    "url": e.get("url") or e.get("webpage_url"),
                    "views": e.get("view_count"),
                    "thumbnail_url": thumb_url,
                    "duration": e.get("duration"),
                    "date": (
                        f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
                        if upload_date and len(upload_date) == 8
                        else None
                    ),
                }
            )
    except Exception:
        pass  # no VODs or blocked

    return result


def clear_caches() -> None:
    with _lock:
        _yt_cache.clear()
        _twitch_cache.clear()
