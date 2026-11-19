#!/usr/bin/env python3
"""Fetch real media for the test suites.

The synthetic fixtures (a sine wave, 0-byte stubs) cannot exercise the parts
of this tool that decide things from audio: the speech detectors, the caption
fetcher, the inpainting cuts. Tests that only see a sine wave pass while
those paths are broken.

Two real sources, both optional and both fetched on demand:

  short-video  -- a short Creative-Commons video, real speech and real pauses,
                  so gap detection and speech detection have something to find.
  transcribed  -- an SRT plus its media from an already-transcribed library,
                  so tests can run against subtitles whose wording is known.

Nothing here is required for the suite to run: when the network or the
library is unavailable, the fixtures are absent and the real-media tests skip
themselves rather than fail.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
FIXTURES = os.path.join(HERE, "fixtures")
sys.path.insert(0, REPO)

# Short, Creative-Commons videos that carry real speech with genuine pauses
# between sentences. Kept deliberately short so the download is a few MB.
SHORT_VIDEOS = [
    # "Big Buck Bunny" trailer: CC-licensed, ~30s of real speech with real
    # pauses. Other candidate URLs were probed and are now geo-blocked or
    # removed, so this list stays short on purpose rather than accumulating
    # dead entries.
    ("bbb", "https://www.youtube.com/watch?v=aqz-KE-bpKQ", 30),
]

CAPTION_LANGS = ("en", "en-orig")


def _ffmpeg_cut(src: str, dst: str, seconds: int) -> bool:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-v", "error",
            "-i", src, "-t", str(seconds),
            "-vn", "-acodec", "aac", "-b:a", "128k",
            "-ac", "1", "-ar", "16000",
            dst,
        ],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0 and os.path.exists(dst)


def fetch_short_video(name: str, url: str, seconds: int) -> bool:
    """Download one short video, trimmed to `seconds` of 16 kHz mono audio."""
    target_dir = os.path.join(FIXTURES, "real")
    os.makedirs(target_dir, exist_ok=True)
    out = os.path.join(target_dir, f"{name}.m4a")
    if os.path.exists(out):
        print(f"already present: {out}")
        return True

    import yt_dlp

    print(f"downloading {name} ({url})")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "worstaudio/worst",
        "outtmpl": os.path.join(target_dir, f"{name}.%(ext)s"),
        "noprogress": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            src = ydl.prepare_filename(info)
    except Exception as exc:
        print(f"  download failed: {exc}")
        return False

    if not os.path.exists(src):
        alt = None
        for root, _dirs, files in os.walk(target_dir):
            for f in files:
                if f.startswith(f"{name}.") and os.path.splitext(f)[1] != ".m4a":
                    alt = os.path.join(root, f)
        if alt is None:
            print("  downloaded file not found")
            return False
        src = alt

    if not _ffmpeg_cut(src, out, seconds):
        print("  ffmpeg cut failed")
        return False
    try:
        os.remove(src)
    except OSError:
        pass
    print(f"  wrote {out}")
    return True


def find_transcribed_library() -> Optional[str]:
    """Locate a directory of already-transcribed subtitles.

    Prefers the standard output dir, then any folder the environment gives
    via WHISPERSUBS_LIBRARY.
    """
    candidates = []
    env = os.environ.get("WHISPERSUBS_LIBRARY")
    if env:
        candidates.append(env)
    candidates.append(os.path.expanduser("~/Documents/Youtube-Subs"))
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return None


def fetch_transcribed_example(count: int = 2) -> int:
    """Copy a few real (srt, media) pairs from a transcribed library."""
    library = find_transcribed_library()
    if not library:
        print("no transcribed library found, skipping")
        return 0

    target_dir = os.path.join(FIXTURES, "real")
    os.makedirs(target_dir, exist_ok=True)

    copied = 0
    for root, _dirs, files in os.walk(library):
        srts = [f for f in files if f.endswith(".srt")]
        for srt in srts:
            if copied >= count:
                return copied
            src_srt = os.path.join(root, srt)
            try:
                if os.path.getsize(src_srt) < 200:
                    continue  # stub/empty
            except OSError:
                continue
            dst = os.path.join(target_dir, f"real_{copied}.srt")
            try:
                with open(src_srt, "rb") as fin, open(dst, "wb") as fout:
                    fout.write(fin.read())
            except OSError:
                continue
            # Carry the media next to it when present, for inpainting tests.
            base = os.path.splitext(src_srt)[0]
            for ext in (".m4a", ".mp4", ".mkv", ".webm", ".mp3"):
                media = base + ext
                if os.path.exists(media):
                    with open(media, "rb") as fin, open(
                        os.path.join(target_dir, f"real_{copied}{ext}"), "wb"
                    ) as fout:
                        fout.write(fin.read())
                    break
            copied += 1
            print(f"  copied {src_srt} -> {dst}")
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-videos", action="store_true",
                        help="do not download short videos")
    parser.add_argument("--skip-transcribed", action="store_true",
                        help="do not copy already-transcribed subtitles")
    args = parser.parse_args()

    ok = True
    if not args.skip_videos:
        for name, url, seconds in SHORT_VIDEOS:
            if not fetch_short_video(name, url, seconds):
                ok = False
                break
    if not args.skip_transcribed:
        copied = fetch_transcribed_example()
        if copied == 0:
            print("no transcribed examples available")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())