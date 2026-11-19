"""YouTube channel discovery, subscription and recommendations.

Complements `api/channels.py` (which serves the *already transcribed*
library tree) with the *online* side:

- `search_channels()` — find a channel by name or @handle via yt-dlp.
- `channel_from_query()` — resolve any user-typed string (name, @handle,
  `/channel/UC…`, `/c/…`, bare URL) to a canonical channel URL.
- `fetch_channel_videos()` — full video list for a channel.
- subscriptions: a JSON-backed list of channels the user follows, so the
  app has something to show before anything is transcribed.
- `recommend()` — an on-device ranking over those channels' videos. No
  accounts, no tracking, no network calls beyond the fetches above.

Everything degrades to empty results when offline or when yt-dlp fails:
no endpoint here is allowed to raise into a request handler.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:  # yt-dlp is a hard runtime dependency for this module
    import yt_dlp
except Exception:  # pragma: no cover - exercised only on broken installs
    yt_dlp = None  # type: ignore


# ---------------------------------------------------------------------------
# Config / cache
# ---------------------------------------------------------------------------

CHANNEL_TTL = 30 * 60  # seconds: channel metadata/video list cache
SEARCH_TTL = 10 * 60
SUBS_PATH = os.path.expanduser("~/.config/WhisperSubs/subscriptions.json")

_lock = threading.RLock()
_channel_cache: Dict[str, Dict[str, Any]] = {}
_search_cache: Dict[str, Dict[str, Any]] = {}


def _base_opts() -> Dict[str, Any]:
    """Metadata-only yt-dlp options; never downloads media."""
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noprogress": True,
        "ignoreerrors": True,
    }


def _cache_get(cache: Dict[str, Dict[str, Any]], key: str):
    entry = cache.get(key)
    if entry and time.time() - entry["at"] < (_ttl_for(cache)):
        return entry["data"]
    cache.pop(key, None)
    return None


def _ttl_for(cache: Dict[str, Dict[str, Any]]) -> float:
    return SEARCH_TTL if cache is _search_cache else CHANNEL_TTL


def _cache_put(cache: Dict[str, Dict[str, Any]], key: str, data: Any) -> None:
    cache[key] = {"at": time.time(), "data": data}


def clear_caches() -> None:
    with _lock:
        _channel_cache.clear()
        _search_cache.clear()


# ---------------------------------------------------------------------------
# Channel discovery
# ---------------------------------------------------------------------------

@dataclass
class ChannelSummary:
    """A channel as discovered online (nothing transcribed yet)."""

    id: str = ""
    name: str = ""
    url: str = ""
    handle: str = ""
    avatar: str = ""
    subscribers: Optional[int] = None
    video_count: Optional[int] = None
    description: str = ""
    # How many search hits pointed here (rank signal for channel search).
    hits: int = 0

    @classmethod
    def from_entry(cls, entry: Dict[str, Any]) -> "ChannelSummary":
        url = entry.get("url") or entry.get("webpage_url") or ""
        return cls(
            id=str(entry.get("id") or entry.get("channel_id") or ""),
            name=(
                entry.get("channel")
                or entry.get("uploader")
                or entry.get("title")
                or ""
            ),
            url=url,
            handle=(entry.get("uploader_id") or "").lstrip("@"),
            avatar=_best_thumb(entry),
            subscribers=entry.get("channel_follower_count"),
            video_count=entry.get("video_count") or entry.get("playlist_count"),
            description=(entry.get("description") or "")[:400],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "handle": self.handle,
            "avatar": self.avatar,
            "subscribers": self.subscribers,
            "video_count": self.video_count,
            "description": self.description,
            "hits": self.hits,
        }


def _best_thumb(entry: Dict[str, Any]) -> str:
    thumbs = entry.get("thumbnails") or []
    if not thumbs:
        return entry.get("thumbnail") or ""
    best = max(thumbs, key=lambda t: t.get("preference") or 0)
    return best.get("url") or ""


def search_channels(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Search YouTube for channels matching `query` (flat, cached).

    `ytsearch` returns only video entries, so channels are derived: each
    video's `uploader_id` (@handle) / `channel_id` (UC…) identifies its
    channel, and channels are grouped and sorted by how many results point
    at them — which for a name search ranks the intended channel first.
    """
    query = (query or "").strip()
    if not query or yt_dlp is None:
        return []

    key = f"ch_{limit}_{query}"
    cached = _cache_get(_search_cache, key)
    if cached is not None:
        return cached

    opts = _base_opts()
    opts["extract_flat"] = True

    # channel_url -> {"hits": n, "entry": representative entry}
    grouped: Dict[str, Dict[str, Any]] = {}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max(limit * 6, 24)}:{query}", download=False)
        for e in info.get("entries") or []:
            if not e:
                continue
            handle = (e.get("uploader_id") or "").lstrip("@")
            channel_id = e.get("channel_id") or ""
            name = e.get("channel") or e.get("uploader") or ""
            if not handle and not channel_id:
                continue
            url = (
                f"https://www.youtube.com/@{handle}" if handle
                else f"https://www.youtube.com/channel/{channel_id}"
            )
            bucket = grouped.setdefault(url, {"hits": 0, "entry": e})
            bucket["hits"] += 1
            # First entry's fields describe the channel well enough.
            if bucket["entry"].get("uploader") is None and name:
                bucket["entry"] = e
    except Exception:
        grouped = {}

    found: List[Dict[str, Any]] = []
    for url, bucket in sorted(
        grouped.items(), key=lambda kv: kv[1]["hits"], reverse=True
    ):
        entry = bucket["entry"]
        summary = ChannelSummary.from_entry(entry)
        summary.url = url
        summary.hits = bucket["hits"]
        found.append(summary.to_dict())
        if len(found) >= limit:
            break

    _cache_put(_search_cache, key, found)
    return found


def normalize_channel_url(value: str) -> str:
    """Turn a user-typed string into a YouTube channel URL.

    Accepts an @handle, a /channel/UC… or /c/… path, a full URL, or a bare
    name (returned unchanged — names still need a search to resolve).
    """
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return text.rstrip("/")
    if text.startswith("@"):
        return f"https://www.youtube.com/{text}"
    if text.startswith("/channel/") or text.startswith("/c/") or text.startswith("/@"):
        return f"https://www.youtube.com{text}"
    return text  # a bare name: caller must search to resolve


def channel_from_query(query: str) -> Optional[Dict[str, Any]]:
    """Resolve a typed channel reference to a real channel, or None.

    Handles URLs directly; @handles and paths are normalised then looked
    up; bare names fall back to `search_channels()` and take the first hit.
    """
    query = (query or "").strip()
    if not query or yt_dlp is None:
        return None

    # Already a URL: fetch it directly.
    if query.startswith("http://") or query.startswith("https://"):
        info = _fetch_channel_info(query)
        if info:
            summary = ChannelSummary.from_entry(info)
            summary.url = query.rstrip("/")
            return summary.to_dict()
        results = search_channels(query.split("/")[-1])
        return results[0] if results else None

    url = normalize_channel_url(query)
    if url == query:  # a bare name
        results = search_channels(query)
        return results[0] if results else None

    info = _fetch_channel_info(url)
    if info:
        summary = ChannelSummary.from_entry(info)
        summary.url = url
        return summary.to_dict()
    return None


def _fetch_channel_info(channel_url: str) -> Optional[Dict[str, Any]]:
    """Flat channel metadata (cached CHANNEL_TTL).

    Deliberately *flat*: a non-flat extraction of a channel resolves every
    video on it, which takes minutes and blows past any request timeout.
    The flat call carries the fields this module needs (name, subscriber
    count, thumbnails) while staying cheap.
    """
    key = f"info_{channel_url}"
    cached = _cache_get(_channel_cache, key)
    if cached is not None:
        return cached
    try:
        opts = _base_opts()
        opts["extract_flat"] = "in_playlist"
        fetch_url = channel_url
        if "youtube.com/channel/" in channel_url or "youtube.com/@" in channel_url:
            fetch_url = channel_url.rstrip("/") + "/videos"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(fetch_url, download=False)
    except Exception:
        return None
    if not info:
        return None
    _cache_put(_channel_cache, key, info)
    return info


def fetch_channel_videos(
    channel_url: str,
    limit: int = 50,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    """Flat video list for a channel (cached CHANNEL_TTL).

    Channel roots return tab entries, so the `/videos` tab is requested for
    the two URL shapes that support it — same approach `api/channels.py`
    already uses.
    """
    channel_url = (channel_url or "").strip().rstrip("/")
    if not channel_url or yt_dlp is None:
        return []

    key = f"vids_{limit}_{channel_url}"
    if not refresh:
        cached = _cache_get(_channel_cache, key)
        if cached is not None:
            return cached

    fetch_url = channel_url
    if "youtube.com/channel/" in channel_url or "youtube.com/@" in channel_url:
        fetch_url = channel_url + "/videos"

    opts = _base_opts()
    opts["extract_flat"] = "in_playlist"

    videos: List[Dict[str, Any]] = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(fetch_url, download=False)
        entries = (info or {}).get("entries") or []
        channel_name = (info or {}).get("channel") or (info or {}).get("uploader")
        for e in entries:
            if not e or not e.get("id"):
                continue
            videos.append(
                {
                    "id": e.get("id"),
                    "title": e.get("title") or "",
                    "url": e.get("url")
                    or e.get("webpage_url")
                    or f"https://www.youtube.com/watch?v={e.get('id')}",
                    "duration": e.get("duration"),
                    "views": e.get("view_count"),
                    # Flat entries DO carry an upload timestamp; without it
                    # the feed's recency signal is always zero.
                    "timestamp": e.get("timestamp"),
                    "thumbnail_url": _best_thumb(e) or e.get("thumbnail"),
                    "channel": e.get("channel") or channel_name or "",
                    "channel_url": channel_url,
                    "live": bool(e.get("live_status")),
                }
            )
            if len(videos) >= limit:
                break
    except Exception:
        return []

    _cache_put(_channel_cache, key, videos)
    return videos


# ---------------------------------------------------------------------------
# Subscriptions (following a channel)
# ---------------------------------------------------------------------------

def load_subscriptions() -> List[Dict[str, Any]]:
    """The user's followed channels, most recently added first."""
    with _lock:
        try:
            with open(SUBS_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return []
    subs = data.get("subscriptions") if isinstance(data, dict) else data
    return subs if isinstance(subs, list) else []


def save_subscriptions(subs: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(SUBS_PATH), exist_ok=True)
    tmp = SUBS_PATH + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"subscriptions": subs}, handle, indent=2)
        os.replace(tmp, SUBS_PATH)


def subscribe(channel: Dict[str, Any]) -> Dict[str, Any]:
    """Follow a channel; returns `{"subscribed": True, "channel": …}`."""
    url = (channel.get("url") or "").rstrip("/")
    if not url:
        return {"subscribed": False, "reason": "channel url required"}
    subs = [s for s in load_subscriptions() if (s.get("url") or "").rstrip("/") != url]
    entry = {
        "id": channel.get("id") or "",
        "name": channel.get("name") or "",
        "url": url,
        "handle": channel.get("handle") or "",
        "avatar": channel.get("avatar") or "",
        "subscribers": channel.get("subscribers"),
        "followed_at": time.time(),
    }
    subs.insert(0, entry)
    save_subscriptions(subs)
    return {"subscribed": True, "channel": entry}


def unsubscribe(channel_url: str) -> Dict[str, Any]:
    target = (channel_url or "").strip().rstrip("/")
    subs = [s for s in load_subscriptions() if (s.get("url") or "").rstrip("/") != target]
    save_subscriptions(subs)
    return {"subscribed": False, "removed": target}


def is_subscribed(channel_url: str) -> bool:
    target = (channel_url or "").strip().rstrip("/")
    return any(
        (s.get("url") or "").rstrip("/") == target
        for s in load_subscriptions()
    )


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

@dataclass
class Recommendation:
    """One ranked video plus why it ranked (kept for UI transparency)."""

    video: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        out = dict(self.video)
        out["score"] = round(self.score, 3)
        out["reasons"] = self.reasons
        return out


def _recency_score(timestamp: Optional[float], now: float) -> float:
    """1.0 for just-uploaded, ~0 for a year old."""
    if not timestamp or timestamp <= 0:
        return 0.0
    age_days = max(0.0, (now - timestamp) / 86400.0)
    return 1.0 / (1.0 + age_days / 30.0)


def _popularity_score(views: Optional[int]) -> float:
    """Log-scaled so a 10M-view video does not swamp everything else."""
    if not views or views < 0:
        return 0.0
    import math

    return min(1.0, math.log10(views + 1) / 7.0)


def _duration_fit(duration: Optional[float]) -> float:
    """Prefer 3–30 min: long enough to be substantive, short enough to start."""
    if not duration or duration <= 0:
        return 0.0
    minutes = duration / 60.0
    if minutes < 1:
        return 0.1
    if minutes < 3:
        return 0.5
    if minutes <= 30:
        return 1.0
    if minutes <= 60:
        return 0.6
    return 0.2


def recommend(
    limit: int = 20,
    subscribed_only: bool = True,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    """Rank videos from followed channels, newest-and-most-watched first.

    Purely local ranking over data the app already fetched: recency and
    views dominate, duration nudges toward watchable lengths, and live
    streams are boosted since they are what the live-transcription feature
    exists for. No accounts, no tracking, nothing leaves the device.
    """
    subs = load_subscriptions()
    now = time.time()

    channels: List[Dict[str, Any]] = list(subs)
    if not subscribed_only:
        # Not subscribed to anything yet: fall back to nothing rather than
        # guessing. A discovery feed needs the user to follow something.
        return []

    ranked: List[Recommendation] = []
    for channel in channels:
        videos = fetch_channel_videos(
            channel.get("url") or "", limit=50, refresh=refresh
        )
        # The flat listing is reverse-chronological for the /videos tab, so
        # position carries the age signal when yt-dlp omits `timestamp`
        # (it does, for most flat entries). Decay by position from the top.
        total = max(1, len(videos))
        for index, video in enumerate(videos):
            reasons: List[str] = []
            position_recency = 1.0 - (index / total)
            recency = _recency_score(video.get("timestamp"), now)
            if recency == 0.0:
                recency = position_recency
                if position_recency > 0.8:
                    reasons.append("recently uploaded")
            elif recency > 0.6:
                reasons.append("recent upload")
            popularity = _popularity_score(video.get("views"))
            fit = _duration_fit(video.get("duration"))
            score = recency * 2.0 + popularity * 1.0 + fit * 0.3
            if popularity > 0.6:
                reasons.append("widely watched")
            if fit == 1.0:
                reasons.append("watchable length")
            if video.get("live"):
                score += 3.0
                reasons.append("live now")
            ranked.append(
                Recommendation(video=video, score=score, reasons=reasons)
            )

    ranked.sort(key=lambda r: r.score, reverse=True)
    return [r.to_dict() for r in ranked[:limit]]


def recommend_from_history(
    watch_history: Optional[List[Dict[str, Any]]] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Rank followed-channel videos against recorded watch history.

    Uses the history only as a keyword signal (channel names and title
    words the user already watched); nothing is sent anywhere.
    """
    history = watch_history or []
    keywords = set()
    for entry in history:
        for value in (entry.get("title"), entry.get("channel")):
            for word in (value or "").lower().split():
                if len(word) > 3:
                    keywords.add(word)

    ranked = recommend(limit=limit)
    if not keywords:
        return ranked
    for item in ranked:
        title = (item.get("title") or "").lower()
        overlap = sum(1 for k in keywords if k in title)
        if overlap:
            item["score"] = item.get("score", 0) + overlap * 0.2
    ranked.sort(key=lambda i: i.get("score", 0), reverse=True)
    return ranked[:limit]
