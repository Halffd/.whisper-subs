#!/usr/bin/env python3
"""Test audio_cache timeday metadata and download_audio two-value returns.

Covers the fix for "too many values to unpack (expected 2)" when a cached
YouTube audio file is used: download_audio() must always return a 2-tuple
(audio_file, timeday), including cache hits.

Usage:
    python tests/test_audio_cache.py
"""

import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPRO_URL = "https://www.youtube.com/watch?v=IlanygYPeGQ"


class _TempCache:
    """Point audio_cache at a temp dir for the duration of the test."""

    def __init__(self):
        import audio_cache

        self._module = audio_cache
        self._orig = (audio_cache.CACHE_DIR, audio_cache.INDEX_FILE)
        self.tmp = tempfile.mkdtemp(prefix="ws-cache-test-")
        audio_cache.CACHE_DIR = self.tmp
        audio_cache.INDEX_FILE = os.path.join(self.tmp, "index.json")

    def write_index(self, index):
        with open(self._module.INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f)

    def read_index(self):
        with open(self._module.INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def make_source(self, name, content=b"audio-bytes"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def close(self):
        self._module.CACHE_DIR, self._module.INDEX_FILE = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _bare_ws(**attrs):
    from whisper_subs import WhisperSubs

    obj = WhisperSubs.__new__(WhisperSubs)
    obj.log = lambda message: None
    for key, value in attrs.items():
        setattr(obj, key, value)
    return obj


def test_put_stores_timeday():
    """Fresh put() persists timeday; get_meta() exposes it; get() stays path-only."""
    with _TempCache() as cache:
        import audio_cache

        src = cache.make_source("fresh.m4a")
        cached = audio_cache.put("https://youtu.be/fresh", src, "2026-10-03_10-15")
        assert cached, "put() returned None"
        assert os.path.exists(cached)

        # timeday is persisted in index.json
        index = cache.read_index()
        key = audio_cache._cache_key("https://youtu.be/fresh")
        assert index["entries"][key]["timeday"] == "2026-10-03_10-15", index

        entry = audio_cache.get_meta("https://youtu.be/fresh")
        assert entry, "get_meta() returned None"
        assert entry["path"] == cached, entry
        assert entry["timeday"] == "2026-10-03_10-15", entry

        # get() remains path-only for backward compatibility
        assert audio_cache.get("https://youtu.be/fresh") == cached
    print("  [PASS] put() stores timeday, get_meta() exposes it, get() path-only")


def test_legacy_entry_without_timeday():
    """Old index entries lack timeday; get_meta() must still work."""
    with _TempCache() as cache:
        import audio_cache

        key = audio_cache._cache_key("https://youtu.be/legacy")
        cached_path = os.path.join(cache.tmp, f"{key}.m4a")
        shutil.copy2(cache.make_source("legacy.m4a", b"legacy-audio"), cached_path)
        cache.write_index(
            {
                "entries": {
                    key: {
                        "path": cached_path,
                        "source": "https://youtu.be/legacy",
                        "mtime": os.path.getmtime(cached_path),
                        "size": os.path.getsize(cached_path),
                    }
                }
            }
        )

        entry = audio_cache.get_meta("https://youtu.be/legacy")
        assert entry, "get_meta() returned None for legacy entry"
        assert entry["path"] == cached_path
        assert entry.get("timeday", "") == "", "legacy entry must default to ''"
        assert audio_cache.get("https://youtu.be/legacy") == cached_path
    print("  [PASS] legacy entry without timeday works")


def test_put_replaces_stale_file():
    """put() with changed content replaces the old cached file."""
    with _TempCache() as cache:
        import audio_cache

        src_old = cache.make_source("old.m4a", b"old-content-bytes")
        src_new = cache.make_source("new.m4a", b"new-bytes")
        audio_cache.put("https://youtu.be/replace", src_old, "2026-01-01_00-00")
        cached = audio_cache.put("https://youtu.be/replace", src_new, "2026-02-02_00-00")

        with open(cached, "rb") as f:
            assert f.read() == b"new-bytes"
        entry = audio_cache.get_meta("https://youtu.be/replace")
        assert entry["size"] == len(b"new-bytes"), entry
        assert entry["timeday"] == "2026-02-02_00-00", entry
    print("  [PASS] put() replaces stale cached file")


def test_expired_entry_removed():
    """get_meta() drops expired entries and deletes their files."""
    with _TempCache() as cache:
        import audio_cache

        src = cache.make_source("exp.m4a")
        cached = audio_cache.put("https://youtu.be/expired", src)
        index = cache.read_index()
        key = audio_cache._cache_key("https://youtu.be/expired")
        index["entries"][key]["mtime"] = time.time() - (
            audio_cache.MAX_AGE_DAYS * 86400 + 100
        )
        cache.write_index(index)

        assert audio_cache.get_meta("https://youtu.be/expired") is None
        assert audio_cache.get("https://youtu.be/expired") is None
        assert not os.path.exists(cached), "expired file must be deleted"
        assert key not in cache.read_index()["entries"]
    print("  [PASS] expired entry removed with its file")


def test_stats_and_missing_lookups():
    """stats() counts entries; missing sources return None."""
    with _TempCache() as cache:
        import audio_cache

        assert audio_cache.get("https://youtu.be/missing") is None
        assert audio_cache.get_meta("https://youtu.be/missing") is None
        assert audio_cache.stats()["total_entries"] == 0

        s1 = cache.make_source("s1.m4a", b"a" * 10)
        s2 = cache.make_source("s2.m4a", b"b" * 20)
        audio_cache.put("https://youtu.be/one", s1)
        audio_cache.put("https://youtu.be/two", s2)

        stats = audio_cache.stats()
        assert stats["total_entries"] == 2, stats
        assert stats["existing_files"] == 2, stats
        assert stats["total_size_bytes"] == 30, stats
    print("  [PASS] stats() counts and missing lookups return None")


def test_identical_file_put_refreshes_timeday():
    """put() on an already-cached identical file must refresh timeday metadata."""
    with _TempCache() as cache:
        import audio_cache

        src = cache.make_source("same.m4a", b"same-bytes")
        first = audio_cache.put("https://youtu.be/same", src, "2026-01-01_00-00")
        second = audio_cache.put("https://youtu.be/same", src, "2026-02-02_12-34")
        assert first and second and first == second, (first, second)

        entry = audio_cache.get_meta("https://youtu.be/same")
        assert entry["timeday"] == "2026-02-02_12-34", entry
    print("  [PASS] identical-file put() refreshes timeday")


def test_download_audio_cache_hit_returns_two_tuple():
    """Cache hit must return (path, timeday) — the bug unpacked a bare string."""
    with _TempCache() as cache:
        import audio_cache

        ws = _bare_ws(force=False, specified_browser=None)
        clean_url = ws.clean_youtube_url(REPRO_URL)

        src = cache.make_source("hit.m4a", b"hit-audio")
        audio_cache.put(clean_url, src, "2026-01-05_14-30")

        out = os.path.join(cache.tmp, "out")
        result = ws.download_audio(REPRO_URL, out)

        assert isinstance(result, tuple), (
            f"expected tuple, got {type(result).__name__}: {result!r}"
        )
        audio_file, timeday = result  # reproduces the original unpack
        assert os.path.exists(audio_file), audio_file
        assert timeday == "2026-01-05_14-30", timeday

        # Second call: dest already exists, still a 2-tuple from the cached path
        result2 = ws.download_audio(REPRO_URL, out)
        assert isinstance(result2, tuple), result2
        audio_file2, timeday2 = result2
        assert os.path.exists(audio_file2), audio_file2
        assert timeday2 == "2026-01-05_14-30", timeday2
    print("  [PASS] cache hit returns (path, timeday) tuple")


def test_download_audio_failure_returns_none():
    """Failure paths return None, safe for the caller's if-not-result guard."""
    with _TempCache():
        import whisper_subs

        class FakeYDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, url, download=False):
                return None

        real_ydl = whisper_subs.yt_dlp.YoutubeDL
        whisper_subs.yt_dlp.YoutubeDL = FakeYDL
        try:
            ws = _bare_ws(force=True, specified_browser=None)
            out = os.path.join(tempfile.mkdtemp(prefix="ws-out-test-"), "out")
            result = ws.download_audio("https://www.youtube.com/watch?v=failtest", out)
            assert result is None, f"expected None, got {result!r}"
        finally:
            whisper_subs.yt_dlp.YoutubeDL = real_ydl
            shutil.rmtree(out, ignore_errors=True)
    print("  [PASS] download failure returns None")


def main():
    tests = [
        test_put_stores_timeday,
        test_legacy_entry_without_timeday,
        test_identical_file_put_refreshes_timeday,
        test_put_replaces_stale_file,
        test_expired_entry_removed,
        test_stats_and_missing_lookups,
        test_download_audio_cache_hit_returns_two_tuple,
        test_download_audio_failure_returns_none,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {test.__name__}: {e}")
    print(f"\n  {passed}/{passed + failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
