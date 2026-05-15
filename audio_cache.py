"""
AudioCache - Persistent disk cache for downloaded/converted audio files.

Stores audio files keyed by source URL hash to avoid re-downloading.
Evicts files older than 30 days or when the cache exceeds 100 files (LRU).
"""
import json
import os
import time
from typing import Optional, Dict, Any

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "whisper-subs", "audio")
INDEX_FILE = os.path.join(CACHE_DIR, "index.json")
MAX_FILES = 100
MAX_AGE_DAYS = 30


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _load_index() -> Dict[str, Any]:
    _ensure_cache_dir()
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"entries": {}}


def _save_index(index: Dict[str, Any]):
    _ensure_cache_dir()
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def _cache_key(source: str) -> str:
    import hashlib
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _evict(index: Dict[str, Any]):
    entries = index["entries"]
    now = time.time()
    max_age_seconds = MAX_AGE_DAYS * 86400

    expired = [
        k for k, v in entries.items()
        if now - v.get("mtime", 0) > max_age_seconds or not os.path.exists(v.get("path", ""))
    ]
    for k in expired:
        path = entries[k].get("path", "")
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        del entries[k]

    while len(entries) > MAX_FILES:
        oldest_key = min(entries, key=lambda k: entries[k].get("mtime", 0))
        path = entries[oldest_key].get("path", "")
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        del entries[oldest_key]

    if expired or len(entries) > MAX_FILES:
        _save_index(index)


def put(source: str, audio_path: str) -> Optional[str]:
    """Cache an audio file, returning the cached path (or None on failure).

    Moves the file into the cache directory and records it in the index.
    """
    if not audio_path or not os.path.exists(audio_path):
        return None

    index = _load_index()
    _evict(index)

    key = _cache_key(source)
    ext = os.path.splitext(audio_path)[1] or ".m4a"
    cached_name = f"{key}{ext}"
    cached_path = os.path.join(CACHE_DIR, cached_name)

    old_entry = index["entries"].get(key)
    if old_entry:
        old_path = old_entry.get("path", "")
        if old_path and os.path.exists(old_path) and old_path != cached_path:
            try:
                os.remove(old_path)
            except OSError:
                pass

    try:
        import shutil
        shutil.move(audio_path, cached_path)
    except OSError:
        try:
            import shutil
            shutil.copy2(audio_path, cached_path)
            os.remove(audio_path)
        except OSError:
            return None

    index["entries"][key] = {
        "path": cached_path,
        "source": source[:200],
        "mtime": time.time(),
        "size": os.path.getsize(cached_path) if os.path.exists(cached_path) else 0,
    }
    _save_index(index)
    return cached_path


def get(source: str) -> Optional[str]:
    """Look up a cached audio file by source URL/path.

    Returns the cached file path if it exists and is not expired, else None.
    Also updates mtime (LRU touch).
    """
    index = _load_index()
    key = _cache_key(source)
    entry = index["entries"].get(key)
    if not entry:
        return None

    path = entry.get("path", "")
    if not path or not os.path.exists(path):
        del index["entries"][key]
        _save_index(index)
        return None

    now = time.time()
    if now - entry.get("mtime", 0) > MAX_AGE_DAYS * 86400:
        try:
            os.remove(path)
        except OSError:
            pass
        del index["entries"][key]
        _save_index(index)
        return None

    entry["mtime"] = now
    _save_index(index)
    return path


def stats() -> Dict[str, Any]:
    """Return cache statistics."""
    index = _load_index()
    entries = index["entries"]
    total_size = sum(e.get("size", 0) for e in entries.values())
    existing = sum(1 for e in entries.values() if os.path.exists(e.get("path", "")))
    return {
        "total_entries": len(entries),
        "existing_files": existing,
        "total_size_bytes": total_size,
        "cache_dir": CACHE_DIR,
        "max_files": MAX_FILES,
        "max_age_days": MAX_AGE_DAYS,
    }
