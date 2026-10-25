#!/usr/bin/env python3
"""Removal of subtitle and wrapper files that serve no purpose.

Neither srt_checker nor verify_subtitles deleted anything: both only
flagged bad files and cleared progress indicators, so a library kept
accumulating

* zero-byte and stubbed `.srt` files (the "Transcription in progress..."
  placeholder left behind by an interrupted run)
* wrapper scripts (.sh/.bat/.ps1/.htm/.m3u) whose `--sub-file=` target no
  longer exists, so double-clicking them plays nothing

This module removes them, reusing verify_subtitles.assess_srt for the one
shared verdict on whether a subtitle is usable. Everything is a dry run
unless `apply` is true.

In-progress work is never touched: `.unfinished.srt` files and the
symlink that points at them are skipped.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# Wrapper types and the suffix they share with their subtitle.
WRAPPER_SUFFIXES = (".sh", ".bat", ".ps1", ".htm", ".m3u")


def _is_in_progress(path: str) -> bool:
    """True for symlinks and .unfinished files that a live run still owns."""
    if path.endswith(".unfinished.srt"):
        return True
    return os.path.islink(path)


def _unfinished_stem(path: str) -> str:
    """Reduce a subtitle or wrapper path to the shared base name.

    The pipeline names files `<title>.<model>.srt`, so the in-progress twin is
    `<title>.<model>.srt.unfinished.srt` and the wrapper is `<title>.<model>.sh`.
    All three must collapse to the same key, so suffixes are stripped
    repeatedly until none match.
    """
    suffixes = (".unfinished.srt", ".metadata.json") + WRAPPER_SUFFIXES + (".srt",)
    current = path
    while True:
        for suffix in suffixes:
            if current.endswith(suffix) and len(current) > len(suffix):
                current = current[: -len(suffix)]
                break
        else:
            return current


def find_broken_outputs(root_dir: str, min_size: int = 50) -> Dict[str, List[str]]:
    """Classify everything under `root_dir` that should be deleted.

    Returns {"empty_srts", "stubbed_srts", "orphan_wrappers"} — paths only,
    nothing is touched.
    """
    import verify_subtitles

    empty: List[str] = []
    stubbed: List[str] = []
    orphan: List[str] = []

    # Pass 1: subtitles. A usable subtitle protects its wrappers.
    # A live transcription owns this base name: its final .srt is a symlink to
    # a still-stubbed .unfinished.srt, so neither file nor wrapper may go.
    live_stems = set()
    usable_stems: set = set()
    all_srts: List[str] = []
    for base, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            # Order matters: `.srt.unfinished.srt` also ends with `.srt`, so it
            # must be tested first or the in-progress branch is dead code.
            if name.endswith(".unfinished.srt"):
                live_stems.add(_unfinished_stem(os.path.join(base, name)))
            elif name.endswith(".srt"):
                all_srts.append(os.path.join(base, name))

    # Finished files still carrying the in-progress metadata block get it
    # removed here, so an existing library is repaired rather than only
    # future transcriptions.
    repaired = 0
    for srt in all_srts:
        if _is_in_progress(srt):
            continue
        try:
            import transcribe

            if transcribe.strip_leading_metadata(srt, write=lambda m: None):
                repaired += 1
        except Exception:
            pass

    for srt in all_srts:
        if _is_in_progress(srt):
            continue
        verdict = verify_subtitles.assess_srt(srt, min_size=min_size)
        if verdict["ok"]:
            usable_stems.add(_unfinished_stem(srt))
            continue
        if verdict["kind"] == "stubbed":
            stubbed.append(srt)
        else:
            # "empty", "corrupt" and "missing" alike leave nothing to play.
            empty.append(srt)

    # Pass 2: wrappers whose subtitle target is gone or was just judged bad.
    for base, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not name.lower().endswith(WRAPPER_SUFFIXES):
                continue
            wrapper = os.path.join(base, name)
            if _is_in_progress(wrapper):
                continue
            # Never touch wrappers a running transcription still owns.
            if _unfinished_stem(wrapper) in live_stems:
                continue

            stem = os.path.join(base, name[: name.rfind(".")])
            refs = verify_subtitles.extract_subtitle_refs(wrapper)
            if refs:
                # A wrapper is only orphaned when every target is unusable.
                if all(
                    _unfinished_stem(os.path.normpath(os.path.join(base, r)))
                    not in usable_stems
                    for r in refs
                    if not os.path.isabs(r)
                ) and not any(
                    _unfinished_stem(r) in usable_stems
                    for r in refs
                    if os.path.isabs(r)
                ):
                    orphan.append(wrapper)
            elif (
                stem not in usable_stems
                and os.path.splitext(name)[0] not in usable_stems
            ):
                # No references at all: a wrapper with no playable subtitle.
                orphan.append(wrapper)

    return {
        "empty_srts": sorted(empty),
        "stubbed_srts": sorted(stubbed),
        "orphan_wrappers": sorted(orphan),
        "metadata_blocks_removed": repaired,
    }


def _drop_metadata_and_wrappers(srt_path: str, write=None) -> int:
    """Remove an SRT plus the metadata and wrappers sharing its stem."""
    import verify_subtitles

    removed = 0
    stem = srt_path[: -len(".srt")] if srt_path.endswith(".srt") else srt_path
    targets = [srt_path, f"{stem}.metadata.json"]
    targets += [f"{stem}{ext}" for ext in WRAPPER_SUFFIXES]
    # The .unfinished twin was already handled by the caller when present.
    targets.append(f"{stem}.unfinished.srt")

    for path in targets:
        if not os.path.lexists(path):
            continue
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                continue
            os.remove(path)
            removed += 1
            if write:
                write(f"    removed {path}")
        except OSError as exc:
            if write:
                write(f"    could not remove {path}: {exc}")
    return removed


def clean_outputs(
    root_dir: str,
    apply: bool = False,
    min_size: int = 50,
    write=None,
) -> Dict[str, Any]:
    """Delete empty/stubbed subtitles and wrappers pointing nowhere.

    With apply=False nothing is deleted and only the plan is reported.
    Returns counts plus the exact paths that were (or would be) removed.
    """
    write = write or (lambda _m: None)
    found = find_broken_outputs(root_dir, min_size=min_size)

    empty = found["empty_srts"]
    stubbed = found["stubbed_srts"]
    orphan = found["orphan_wrappers"]

    # Drop the empty/stubbed subtitles first; that can retire wrappers too,
    # so the wrapper pass below only sees what is left behind.
    doomed = empty + stubbed
    result: Dict[str, Any] = {
        "empty_srts": empty,
        "stubbed_srts": stubbed,
        "orphan_wrappers": [],
        "removed": 0,
        "would_remove": 0,
        "applied": bool(apply),
    }

    if doomed:
        write(f"\nEmpty or stubbed subtitles: {len(doomed)}")
        for srt in doomed:
            write(f"  {srt}")

    if apply:
        removed = 0
        for srt in doomed:
            removed += _drop_metadata_and_wrappers(srt, write)
        # Re-scan: a wrapper whose subtitle just died is now orphaned.
        remaining = find_broken_outputs(root_dir, min_size=min_size)
        orphan = remaining["orphan_wrappers"]
        for wrapper in orphan:
            write(f"  {wrapper} (subtitle missing)")
            try:
                os.remove(wrapper)
                removed += 1
                write(f"    removed {wrapper}")
            except OSError as exc:
                write(f"    could not remove {wrapper}: {exc}")
        result["removed"] = removed
    else:
        if orphan:
            write(f"\nWrappers pointing nowhere: {len(orphan)}")
            for wrapper in orphan:
                write(f"  {wrapper}")

    result["orphan_wrappers"] = orphan
    result["would_remove"] = len(doomed) + len(orphan)
    return result
