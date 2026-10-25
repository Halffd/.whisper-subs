#!/usr/bin/env python3
"""Compare transcription models on one file and collect a human rating.

Running `--rate` transcribes the same audio with each candidate model in
turn, prints what each produced, and asks for a score. The point is to pick
a model from evidence on *your* material rather than from a leaderboard:
accent, background noise and language matter more than WER averages.

Ratings persist to a JSON file keyed by a hash of the audio path plus the
model list, so a later run can show the previous verdict and skip ahead.

Typical use:

    python whisper_subs.py --rate audio.mp3
    python whisper_subs.py --rate audio.mp3 -m small,medium,large-v3
    python whisper_subs.py --rate audio.mp3 -m groq:whisper-large-v3
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# Where ratings are kept, next to the subtitle library.
DEFAULT_RATINGS_FILE = os.path.join(
    os.path.expanduser("~"),
    "Documents",
    "Youtube-Subs",
    "model_ratings.json",
)

SCALE = 5
PROMPT = "Rating 1-5 (0 = skip/unusable, just Enter = same as before)"

# A sensible spread when the caller does not name models: cheap-to-accurate,
# plus one non-Whisper engine so the comparison is not only within one family.
DEFAULT_CANDIDATES = [
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
]


def default_candidates() -> List[str]:
    """Local models that are actually installed/resolvable."""
    try:
        from model import get_context

        available = {
            name
            for group in get_context().list_available_adapters()
            if group["available"]
            for name in group["models"]
        }
    except Exception:
        return list(DEFAULT_CANDIDATES)

    # Keep only models this machine can run, and cap the list so a rating
    # session stays a few minutes rather than an hour.
    usable = [m for m in DEFAULT_CANDIDATES if m in available]
    return usable or list(DEFAULT_CANDIDATES)


def _ratings_path(path: Optional[str]) -> str:
    if path:
        return os.path.abspath(os.path.expanduser(path))
    return DEFAULT_RATINGS_FILE


def _session_key(audio_file: str, models: List[str]) -> str:
    digest = hashlib.sha256()
    digest.update(os.path.abspath(audio_file).encode("utf-8"))
    digest.update("\n".join(sorted(models)).encode("utf-8"))
    return digest.hexdigest()[:16]


def load_ratings(path: Optional[str] = None) -> Dict[str, Any]:
    target = _ratings_path(path)
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_ratings(data: Dict[str, Any], path: Optional[str] = None) -> str:
    target = _ratings_path(path)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return target


def _format_result(text: str, segments: List[Any], seconds: float) -> str:
    """Preview the transcript: timing line plus a bounded text block."""
    lines = [f"  {len(segments)} segments, {seconds:.1f}s wall"]
    body = text.strip()
    if not body:
        return "\n".join(lines + ["  (no text produced)"])
    limit = 600
    if len(body) > limit:
        body = body[:limit] + " ..."
    for line in body.splitlines() or [body]:
        lines.append(f"  | {line}")
    return "\n".join(lines)


def _ask(prompt: str, default: Optional[int] = None) -> Optional[int]:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        try:
            raw = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            return default
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("  enter a number 0-5")
            continue
        if 0 <= value <= SCALE:
            return value
        print(f"  {value} is out of range (0-{SCALE})")


def rate_file(
    audio_file: str,
    models: List[str],
    device: str = "cpu",
    compute_type: str = "int8",
    cpu_threads: Optional[int] = None,
    ratings_path: Optional[str] = None,
    previous: Optional[Dict[str, int]] = None,
    non_interactive: bool = False,
) -> Dict[str, Any]:
    """Transcribe `audio_file` with each model and record a rating."""
    if not audio_file or not os.path.exists(audio_file):
        print(f"Audio file not found: {audio_file}", file=sys.stderr)
        return {}

    from model import get_context

    ctx = get_context()
    session = _session_key(audio_file, models)
    previous = dict(previous or {})

    print("=" * 68)
    print(f"Model rating: {os.path.basename(audio_file)}")
    print(f"Models ({len(models)}): {', '.join(models)}")
    if previous:
        print(f"Previous ratings: {previous}")
    print("=" * 68)

    results: Dict[str, Any] = {}
    for index, model in enumerate(models, 1):
        print(f"\n[{index}/{len(models)}] {model}")
        started = time.time()
        try:
            segments, info = ctx.transcribe(
                audio_file=audio_file,
                model_name=model,
                write=lambda m: print(f"    {m}"),
                device=device,
                compute_type=compute_type,
                cpu_threads=cpu_threads,
            )
        except Exception as exc:
            elapsed = time.time() - started
            print(f"  FAILED after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
            results[model] = {"rating": 0, "error": str(exc), "seconds": elapsed}
            continue

        elapsed = time.time() - started
        text = "\n".join(getattr(s, "text", "") for s in segments or [])
        print(_format_result(text, segments or [], elapsed))

        if non_interactive:
            results[model] = {
                "rating": 0,
                "segments": len(segments or []),
                "seconds": round(elapsed, 2),
            }
            continue

        rating = _ask(PROMPT, default=previous.get(model))
        results[model] = {
            "rating": rating,
            "segments": len(segments or []),
            "seconds": round(elapsed, 2),
        }

    print("\n" + "=" * 68)
    print("Ranking")
    print("=" * 68)
    ranked = sorted(
        results.items(),
        key=lambda kv: (kv[1].get("rating") or 0, kv[1].get("segments") or 0),
        reverse=True,
    )
    for model, data in ranked:
        score = data.get("rating")
        mark = "  " if score else "--"
        note = f"  ({data['error'][:40]})" if data.get("error") else ""
        print(
            f" {mark} {score if score is not None else '?'}/{SCALE}  {model:<28} "
            f"{data.get('segments', 0):>4} seg  {data.get('seconds', 0):>6.1f}s{note}"
        )

    best = next((m for m, d in ranked if (d.get("rating") or 0) > 0), None)
    if best:
        print(f"\nBest: {best}")
        print(f"Use it with:  whisper_subs.py {best} ...")

    store = load_ratings(ratings_path)
    store[session] = {
        "audio": os.path.abspath(audio_file),
        "models": models,
        "results": results,
    }
    if not non_interactive:
        saved = save_ratings(store, ratings_path)
        print(f"\nRatings saved to {saved}")
    return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Transcribe one file with several models and rate the results."
    )
    parser.add_argument("audio", help="Audio or video file to rate models on.")
    parser.add_argument(
        "-m",
        "--models",
        default=None,
        help="Comma-separated models. Default: a spread of local models.",
    )
    parser.add_argument("--gpu", action="store_true", help="Use CUDA if available.")
    parser.add_argument(
        "--cpu-threads", type=int, default=None, help="CPU threads per model."
    )
    parser.add_argument(
        "--ratings-file", default=None, help=f"Default: {DEFAULT_RATINGS_FILE}"
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show stored ratings for this file and exit.",
    )
    args = parser.parse_args()

    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else default_candidates()
    )

    if args.show:
        data = load_ratings(args.ratings_file)
        session = _session_key(args.audio, models)
        print(json.dumps(data.get(session, {}), indent=2, ensure_ascii=False))
        return

    rate_file(
        audio_file=args.audio,
        models=models,
        device="cuda" if args.gpu else "cpu",
        cpu_threads=args.cpu_threads,
        ratings_path=args.ratings_file,
    )


if __name__ == "__main__":
    main()
