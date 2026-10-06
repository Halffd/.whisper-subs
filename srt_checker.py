#!/usr/bin/env python3
"""Empty-subtitle checker.

Finds .srt files that hold no usable subtitle content (missing, zero
bytes, only the in-progress placeholder, or no valid subtitle blocks),
removes their entries from the progress indicator (jobs.json) and the
complete indicator (history.txt) so the next run re-transcribes them
instead of skipping them as processed, and records them in a list file
(empty_srts.txt, one JSON record per line).

Standalone use:

    python srt_checker.py [directory]

defaults to ~/Documents/Youtube-Subs.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple


def is_empty_srt(srt_path: str) -> bool:
    """True when the SRT has no usable subtitle content.

    Empty means: missing, zero bytes, only the in-progress placeholder,
    or no valid subtitle blocks at all. A file that merely carries
    hallucination or structure warnings is NOT empty — it has content.
    """
    import transcribe  # lazy: pulls the model registry

    report = transcribe.verify_srt_file(srt_path, write=lambda m: None)
    return report["segments"] == 0


def remove_from_history(history_file: str, ids: List[str]) -> int:
    """Remove history entries (complete indicator) matching any id.

    history.txt lines look like "<unique_id> <model>"; ids may be the
    video id, the task source or URL variants used when marking
    processed. Returns the number of removed lines.
    """
    if not ids or not os.path.exists(history_file):
        return 0
    wanted = {i for i in ids if i}
    removed = 0
    kept: List[str] = []
    with open(history_file, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            first = stripped.split()[0] if stripped else ""
            if first and first in wanted:
                removed += 1
            else:
                kept.append(line)
    if removed:
        with open(history_file, "w", encoding="utf-8") as f:
            f.writelines(kept)
    return removed


def remove_task_from_progress(jobs_file: str, job_id: Any, task_source: str) -> bool:
    """Remove the task entry from its job in jobs.json (progress indicator).

    Returns True when a task entry was removed.
    """
    if job_id is None or not os.path.exists(jobs_file):
        return False
    try:
        with open(jobs_file, "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    removed = False
    for job in jobs:
        if job.get("id") == job_id:
            tasks = job.get("tasks", [])
            remaining = [t for t in tasks if t.get("source") != task_source]
            removed = len(remaining) != len(tasks)
            job["tasks"] = remaining
            break
    if removed:
        with open(jobs_file, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
    return removed


def add_to_empty_list(
    list_file: str,
    srt_path: str,
    source: Optional[str],
    model_name: Optional[str],
) -> None:
    """Append the empty SRT to the list file (one JSON record per line)."""
    os.makedirs(os.path.dirname(list_file) or ".", exist_ok=True)
    record = {
        "srt": srt_path,
        "source": source or "",
        "model": model_name or "",
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    with open(list_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_empty_list(list_file: str) -> List[Dict[str, Any]]:
    """Read the empty-SRT list file."""
    if not os.path.exists(list_file):
        return []
    records: List[Dict[str, Any]] = []
    with open(list_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def check_empty_srt(
    srt_path: str,
    ids: List[str],
    source: Optional[str],
    model_name: Optional[str],
    history_file: str,
    jobs_file: str,
    job_id: Any,
    list_file: str,
    write: Callable = print,
) -> bool:
    """Check one finished SRT.

    If it is empty: remove its entries from the progress indicator
    (jobs.json) and the complete indicator (history.txt) so the next run
    re-transcribes it, and add it to the empty list. Returns True when
    the file was empty and got cleaned up — the caller should treat the
    task as failed, not completed.
    """
    if not is_empty_srt(srt_path):
        return False

    write(f"Empty subtitles: {srt_path}")
    removed = remove_from_history(history_file, ids)
    if removed:
        entry = "entry" if removed == 1 else "entries"
        write(
            f"Removed {removed} completed {entry} from {os.path.basename(history_file)}"
        )
    if remove_task_from_progress(jobs_file, job_id, source):
        write("Removed task from the progress indicator")
    add_to_empty_list(list_file, srt_path, source, model_name)
    write(f"Added to empty list: {os.path.basename(list_file)}")
    return True


def scan_empty_srts(
    directory: str,
    history_file: str,
    jobs_file: str,
    list_file: str,
    write: Callable = print,
) -> List[str]:
    """Scan a directory tree for empty .srt files and clean them up.

    In-progress symlinked files and .unfinished.srt artifacts are
    skipped. The source for indicator cleanup is recovered from the
    sibling .metadata.json when present. Returns the paths of all empty
    SRTs found (they are also added to the list file).
    """
    empty: List[str] = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in sorted(files):
            if not name.endswith(".srt") or name.endswith(".unfinished.srt"):
                continue
            srt_path = os.path.join(root, name)
            if os.path.islink(srt_path):
                continue  # in-progress symlink
            if not is_empty_srt(srt_path):
                continue
            empty.append(srt_path)
            source, ids = _source_from_metadata(srt_path)
            check_empty_srt(
                srt_path=srt_path,
                ids=ids + [name],
                source=source or name,
                model_name=None,
                history_file=history_file,
                jobs_file=jobs_file,
                job_id=_find_job_id(jobs_file, source),
                list_file=list_file,
                write=write,
            )
    return empty


def _source_from_metadata(srt_path: str) -> Tuple[Optional[str], List[str]]:
    """Recover source and matching ids from the sibling metadata.json."""
    meta_file = os.path.splitext(srt_path)[0] + ".metadata.json"
    if not os.path.exists(meta_file):
        return None, []
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, []
    source = data.get("source_url") or data.get("url") or data.get("webpage_url")
    ids = [data.get("video_id"), source]
    return source, [i for i in ids if i]


def _find_job_id(jobs_file: str, source: Optional[str]) -> Any:
    """Find the id of the job whose tasks contain the given source."""
    if not source or not os.path.exists(jobs_file):
        return None
    try:
        with open(jobs_file, "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    for job in jobs:
        for task in job.get("tasks", []):
            if task.get("source") == source:
                return job.get("id")
    return None


if __name__ == "__main__":
    import argparse

    output_dir = os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs")
    parser = argparse.ArgumentParser(
        description=(
            "Find empty .srt files, clear their progress/completed "
            "indicators and add them to the empty list"
        )
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=output_dir,
        help=f"Directory to scan (default: {output_dir})",
    )
    parser.add_argument(
        "--history",
        default=os.path.join(output_dir, "history.txt"),
        help="history.txt path (complete indicator)",
    )
    parser.add_argument(
        "--jobs",
        default=os.path.join(
            os.path.expanduser("~"), ".config", "WhisperSubs", "jobs.json"
        ),
        help="jobs.json path (progress indicator)",
    )
    parser.add_argument(
        "--list",
        dest="list_file",
        default=os.path.join(output_dir, "empty_srts.txt"),
        help="empty list file path",
    )
    args = parser.parse_args()

    found = scan_empty_srts(
        directory=args.directory,
        history_file=args.history,
        jobs_file=args.jobs,
        list_file=args.list_file,
    )
    if found:
        print(f"\n{len(found)} empty subtitle file(s):")
        for path in found:
            print(f"  {path}")
        print(f"List file: {args.list_file}")
    else:
        print("No empty subtitle files found.")
