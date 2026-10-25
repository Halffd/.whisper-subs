#!/usr/bin/env python3
"""Compare finished subtitle files and help pick the best one.

Two models on the same audio rarely agree, and a word-error-rate number says
nothing about whether the cues are readable. This script scores the files you
already have on disk:

* hallucination and corruption checks, via transcribe.verify_srt_file —
  phrase repeats, identical cues in a row, over-duplication, near-duplicate
  loops, unparseable blocks
* segmentation quality: cues that end mid-word, which is the tell-tale sign
  of a transducer grouped by character count instead of by word
* leftover in-progress metadata blocks, which players render as a subtitle
* timing sanity: overlapping cues, cues out of order, zero-length cues

It prints one row per file, then — with --choose — backs up the losers as
<name>.2.srt, .3.srt, ... and leaves the winner under the original name, the
same numbering the rest of the toolchain uses for superseded subtitles.

    python srt_compare.py a.srt b.srt
    python srt_compare.py a.srt b.srt --choose 1
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

# Cues the parser ignores on purpose but a player will still show.
_META_BLOCK = re.compile(
    r"^\s*\d+\s*\n\s*\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}\s*\n"
    r"\s*TRANSCRIPTION METADATA\b",
    re.IGNORECASE,
)

# A cue ending on a letter whose successor starts on a letter is very likely a
# word cut in half. Punctuation, closing quotes and digits end a word cleanly.
_LAST_IS_LETTER = re.compile(r"[^\W\d_]\s*$", re.UNICODE)
_FIRST_IS_LETTER = re.compile(r"^\s*[^\W\d_]", re.UNICODE)


def _cue_lines(path: str) -> List[Tuple[str, str, str]]:
    """Parse a file into (start, end, text) triples, ignoring blank gaps."""
    import transcribe

    report = transcribe.verify_srt_file(path, write=lambda _m: None)
    return report, _read_cues(path)


def _read_cues(path: str) -> List[Dict[str, Any]]:
    """Read cues directly, keeping the raw text for segmentation checks."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return []

    cues: List[Dict[str, Any]] = []
    ts = re.compile(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})")
    for block in content.strip().split("\n\n"):
        lines = [l for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        match = None
        for i, line in enumerate(lines):
            match = ts.search(line)
            if match:
                index = i
                break
        else:
            continue
        text = "\n".join(l.strip() for l in lines[index + 1 :]).strip()
        if text.startswith("TRANSCRIPTION METADATA"):
            continue  # in-progress pseudo-block, handled separately
        cues.append({"start": match.group(1), "end": match.group(2), "text": text})
    return cues


def _seconds(stamp: str) -> float:
    hours, minutes, rest = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest.replace(",", "."))


def _has_metadata_block(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4000)
    except OSError:
        return False
    return bool(_META_BLOCK.search(head))


def analyse(path: str) -> Dict[str, Any]:
    """Score one subtitle file. Never raises for a readable-but-bad file."""
    import transcribe

    out: Dict[str, Any] = {
        "path": path,
        "exists": os.path.exists(path),
        "ok": False,
        "problems": [],
        "warnings": [],
        "segments": 0,
        "words": 0,
        "midword_splits": 0,
        "overlaps": 0,
        "zero_length": 0,
        "metadata_block": _has_metadata_block(path),
        "avg_chars": 0.0,
    }
    if not out["exists"]:
        out["problems"].append("file missing")
        return out

    report = transcribe.verify_srt_file(path, write=lambda _m: None)
    out["ok"] = report["ok"]
    out["problems"] = list(report["problems"])
    out["warnings"] = list(report["warnings"])
    out["segments"] = report["segments"]
    out["last_end"] = report.get("last_end", 0.0)

    cues = _read_cues(path)
    if not cues:
        return out

    words = 0
    chars = 0
    splits = 0
    for i, cue in enumerate(cues):
        text = cue["text"]
        words += len(text.split())
        chars += len(text)
        if i + 1 < len(cues):
            nxt = cues[i + 1]["text"]
            if _LAST_IS_LETTER.search(text) and _FIRST_IS_LETTER.match(nxt):
                splits += 1

    out["words"] = words
    out["avg_chars"] = round(chars / len(cues), 1)
    out["midword_splits"] = splits
    out["midword_examples"] = [
        f"{cues[i]['text'][-18:]}|{cues[i + 1]['text'][:18]}"
        for i in range(len(cues) - 1)
        if _LAST_IS_LETTER.search(cues[i]["text"])
        and _FIRST_IS_LETTER.match(cues[i + 1]["text"])
    ][:3]

    starts = [_seconds(c["start"]) for c in cues]
    ends = [_seconds(c["end"]) for c in cues]
    out["zero_length"] = sum(1 for a, b in zip(starts, ends) if b <= a)
    out["overlaps"] = sum(1 for a, b in zip(ends, starts[1:]) if b < a)
    out["unordered"] = starts != sorted(starts)
    return out


def _fmt_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def report(paths: List[str]) -> List[Dict[str, Any]]:
    results = [analyse(p) for p in paths]
    usable = [r for r in results if r["exists"]]

    print("=" * 78)
    print("Subtitle comparison")
    print("=" * 78)
    for r in results:
        print(f"\n{r['path']}")
        if not r["exists"]:
            print("  MISSING")
            continue
        status = "OK" if r["ok"] else "PROBLEMS"
        print(
            f"  cues {r['segments']:<5} words {r['words']:<7} "
            f"length {_fmt_duration(r.get('last_end', 0)):<8} "
            f"avg {r['avg_chars']:<5} chars/cue   [{status}]"
        )
        if r["problems"]:
            for p in r["problems"][:4]:
                print(f"  ! {p}")
        for w in r["warnings"][:3]:
            print(f"  ~ {w}")
        if r["midword_splits"]:
            # Heuristic: a cue ending on a letter followed by one starting on a
            # letter. Catches BPE splits like "grandin"|"ha" but also flags
            # clean splits at word boundaries, so treat it as a smell.
            print(
                f"  ~ {r['midword_splits']} possible mid-word split(s) "
                f"(heuristic; e.g. {' | '.join(r['midword_examples'])})"
            )
        if r["zero_length"]:
            print(f"  ! {r['zero_length']} zero-length cue(s)")
        if r["overlaps"]:
            print(f"  ! {r['overlaps']} overlapping cue(s)")
        if r["unordered"]:
            print("  ! cues out of order")
        if r["metadata_block"]:
            print(
                "  ! contains a leftover TRANSCRIPTION METADATA block "
                "(players show it as a subtitle)"
            )

    if len(usable) > 1:
        best = max(usable, key=lambda r: (r["ok"], r["words"], r["segments"]))
        print("\n" + "-" * 78)
        print(
            f"Suggested: {os.path.basename(best['path'])} "
            f"({best['words']} words, {best['segments']} cues)"
        )
    return results


def _backup(path: str) -> Optional[str]:
    """Move a losing subtitle aside as <name>.2.srt, .3.srt, ..."""
    stem, ext = os.path.splitext(path)
    if ext != ".srt":
        return None
    number = 2
    while os.path.exists(f"{stem}.{number}.srt"):
        number += 1
    target = f"{stem}.{number}.srt"
    shutil.move(path, target)
    return target


def choose(paths: List[str], index: int) -> Optional[str]:
    """Keep paths[index] in place; move every other file aside."""
    if not 0 <= index < len(paths):
        print(f"Choice {index} is out of range (0-{len(paths) - 1})", file=sys.stderr)
        return None

    winner = paths[index]
    if not os.path.exists(winner):
        print(f"Chosen file does not exist: {winner}", file=sys.stderr)
        return None

    moved = []
    for i, path in enumerate(paths):
        if i == index or not os.path.exists(path):
            continue
        backup = _backup(path)
        if backup:
            moved.append((path, backup))
            print(f"  {os.path.basename(path)} -> {os.path.basename(backup)}")

    print(f"\nKept: {winner}")
    if moved:
        print(f"Superseded {len(moved)} other subtitle(s).")
    return winner


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare subtitle files, check for hallucinations and "
        "mid-word splits, and optionally keep the best one."
    )
    parser.add_argument("files", nargs="+", help="SRT files to compare.")
    parser.add_argument(
        "--choose",
        type=int,
        default=None,
        metavar="N",
        help="Keep file N (0-based) and move the others aside as .2.srt, .3.srt.",
    )
    args = parser.parse_args()

    existing = [p for p in args.files]
    report(existing)
    if args.choose is not None:
        print()
        choose(existing, args.choose)


if __name__ == "__main__":
    main()
