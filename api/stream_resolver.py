"""
Stream Resolver - resolve remote video/audio streams via yt-dlp / streamlink.

Used by the API playback endpoints to give the mobile app a proxied or direct
stream URL. YouTube direct URLs are IP-bound and expire (~6h), so they must be
proxied through the server. Twitch HLS playlists are handed back directly.

Public API:
    resolve_stream(source, prefer_audio=False) -> StreamInfo
    clear_cache()
"""

import os
import re
import time
import threading
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List

import yt_dlp

STREAMLINK_BIN = shutil.which("streamlink") or "streamlink"
RESOLVE_CACHE_TTL = 6 * 3600  # YouTube URLs expire after ~6 hours

TWITCH_RE = re.compile(r"(?i)twitch\.tv")

# Same cookie policy as whisper_subs: pull cookies from browser for YouTube.
COOKIES_BROWSER = os.environ.get("WHISPER_COOKIES_BROWSER", "firefox")


@dataclass
class StreamInfo:
    """Resolved stream details for playback."""

    source: str
    url: str
    protocol: str = "https"  # https | hls | http
    ext: str = ""  # mp4, m3u8, ...
    format_note: str = ""  # "1080p", "audio only", ...
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    title: str = ""
    channel: Optional[str] = None
    thumbnail: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    is_live: bool = False
    resolved_at: float = field(default_factory=time.time)
    resolver: str = ""  # "yt-dlp" | "streamlink"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Cache of resolved streams: source URL -> StreamInfo
_cached: Dict[str, StreamInfo] = {}
_cache_lock = threading.Lock()


def _cache_get(source: str) -> Optional[StreamInfo]:
    with _cache_lock:
        entry = _cached.get(source)
        if entry is None:
            return None
        if time.time() - entry.resolved_at > RESOLVE_CACHE_TTL:
            _cached.pop(source, None)
            return None
        return entry


def _cache_put(source: str, info: StreamInfo) -> None:
    with _cache_lock:
        _cached[source] = info
        now = time.time()
        expired = [
            k for k, v in _cached.items() if now - v.resolved_at > RESOLVE_CACHE_TTL
        ]
        for k in expired:
            _cached.pop(k, None)


def _is_twitch(source: str) -> bool:
    return bool(TWITCH_RE.search(source))


def _pick_format(
    formats: List[Dict[str, Any]], prefer_audio: bool
) -> Optional[Dict[str, Any]]:
    """Pick the best format entry from yt-dlp 'formats' list."""
    if not formats:
        return None

    def has_video(f):
        return f.get("vcodec") not in (None, "none")

    def has_audio(f):
        return f.get("acodec") not in (None, "none")

    def is_progressive(f):
        return has_video(f) and has_audio(f)

    def score(f):
        s = 0
        if is_progressive(f):
            s += 1000
        elif has_video(f):
            s += 500
        elif has_audio(f):
            s += 200
        s += f.get("height") or 0
        if f.get("tbr"):
            s += min(f["tbr"], 2000) / 100
        return s

    candidates = [
        f
        for f in formats
        if f.get("url")
        and (
            has_video(f) or has_audio(f) or (f.get("protocol") or "").startswith("m3u8")
        )
        and f.get("protocol") not in ("mhtml",)
    ]

    if prefer_audio:
        audio_candidates = [c for c in candidates if has_audio(c)]
        if audio_candidates:
            candidates = audio_candidates

    if not candidates:
        return None

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def resolve_stream(
    source: str,
    prefer_audio: bool = False,
    force: bool = False,
    cookies_browser: Optional[str] = None,
) -> StreamInfo:
    """Resolve a playable stream URL for the given source.

    Uses yt-dlp Python API for progressive/direct URLs (YouTube, VODs, most
    sites) and streamlink for Twitch HLS. Results cached for RESOLVE_CACHE_TTL.
    """
    source = source.strip()
    if not source:
        raise ValueError("Empty source URL")

    cached = _cache_get(source)
    if cached and not force:
        return cached

    if _is_twitch(source):
        info = _resolve_twitch(source, prefer_audio, cookies_browser)
    else:
        info = _resolve_ytdlp(source, prefer_audio, cookies_browser)

    _cache_put(source, info)
    return info


def _ytdlp_opts(cookies_browser: Optional[str], quiet: bool = True) -> Dict[str, Any]:
    browser = cookies_browser or COOKIES_BROWSER
    opts: Dict[str, Any] = {
        "quiet": quiet,
        "no_warnings": True,
        "socket_timeout": 15,
        "no_check_certificate": True,
        "noplaylist": True,
    }
    # Cookies from browser are required for YouTube. If extraction fails with
    # cookies, the caller retries without them (e.g., Twitch dislikes Firefox
    # cookie paths on some setups).
    if browser:
        try:
            opts["cookiesfrombrowser"] = (browser,)
        except Exception:
            pass
    return opts


def _resolve_ytdlp(
    source: str, prefer_audio: bool, cookies_browser: Optional[str]
) -> StreamInfo:
    """Resolve a direct/progressive stream URL via yt-dlp Python API."""
    last_err: Optional[Exception] = None

    for browser in [cookies_browser or COOKIES_BROWSER, None]:
        try:
            with yt_dlp.YoutubeDL(_ytdlp_opts(browser)) as ydl:
                data = ydl.extract_info(source, download=False)
            if not data:
                raise RuntimeError("yt-dlp returned no info")
            break
        except Exception as e:
            last_err = e
            continue
    else:
        raise RuntimeError(f"yt-dlp resolution failed: {last_err}")

    fmts = data.get("formats") or []
    fmt = _pick_format(fmts, prefer_audio)

    if not fmt:
        url = data.get("url")
        if not url:
            # Try HLS manifest fallback for live/formats-less sources
            hls_url = data.get("hls_manifest_url")
            if not hls_url:
                raise RuntimeError("No playable format found for source")
            fmt = {"url": hls_url, "protocol": "m3u8", "ext": "m3u8", "height": None}
        else:
            fmt = {
                "url": url,
                "ext": data.get("ext") or "",
                "format_note": data.get("format_note") or "",
                "height": data.get("height"),
            }

    protocol = (
        (fmt.get("protocol") or "") if isinstance(fmt.get("protocol"), str) else ""
    )
    is_hls = protocol.startswith("m3u8") or (fmt.get("ext") == "m3u8")

    # Media3 wants a UA header for most CDNs
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    http_headers = data.get("http_headers") or {}
    if isinstance(http_headers, dict):
        for k in ("User-Agent", "Referer", "Origin"):
            if http_headers.get(k):
                headers[k] = http_headers[k]

    info = StreamInfo(
        source=source,
        url=fmt.get("url") or "",
        protocol="hls" if is_hls else "https",
        ext=fmt.get("ext") or "",
        format_note=fmt.get("format_note") or "",
        width=fmt.get("width"),
        height=fmt.get("height"),
        duration=data.get("duration"),
        title=data.get("title") or "",
        channel=data.get("channel") or data.get("uploader"),
        thumbnail=data.get("thumbnail"),
        headers=headers,
        is_live=bool(data.get("is_live")),
        resolver="yt-dlp",
    )
    return info


def _resolve_twitch(
    source: str, prefer_audio: bool, cookies_browser: Optional[str]
) -> StreamInfo:
    """Resolve Twitch HLS via streamlink (handles live + VOD)."""
    quality = "audio" if prefer_audio else "best,1080p60,1080p,720p,best"
    cmd = [STREAMLINK_BIN, "--stream-url", "--no-config", source, quality]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        if isinstance(e, FileNotFoundError):
            return _resolve_ytdlp(source, prefer_audio, cookies_browser)
        raise RuntimeError(f"streamlink failed to run: {e}") from e

    url = (proc.stdout or "").strip()
    if proc.returncode != 0 or not url:
        try:
            return _resolve_ytdlp(source, prefer_audio, cookies_browser)
        except RuntimeError:
            err = (proc.stderr or "").strip()[-500:]
            raise RuntimeError(f"streamlink resolution failed: {err}")

    return StreamInfo(
        source=source,
        url=url,
        protocol="hls",
        ext="m3u8",
        format_note="audio" if quality == "audio" else "hls",
        is_live=True,
        resolver="streamlink",
    )


def clear_cache() -> None:
    """Clear the resolution cache."""
    with _cache_lock:
        _cached.clear()
