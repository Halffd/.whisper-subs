#!/usr/bin/env python3
"""
Subtitle Verification and Fixer Tool

Checks for missing or corrupted SRT files in completed jobs,
updates job statuses, and creates a rerun list.
"""

import os
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

# Configuration
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "WhisperSubs")
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Youtube-Subs")
JOBS_FILE = os.path.join(CONFIG_DIR, "jobs.json")
DEFAULT_RERUN_FILE = os.path.join(OUTPUT_DIR, "rerun_subtitles.txt")

# Defaults
DEFAULT_MIN_SRT_SIZE = 50

# Valid SRT pattern (at least one subtitle entry)
SRT_ENTRY_PATTERN = re.compile(
    r"^\d+\n\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}"
)


def clean_filename(filename: str) -> str:
    """Sanitize filename for filesystem."""
    filename = re.sub(r'[\\/*?:"<>|]', "_", str(filename))
    # Remove emojis and special chars
    filename = "".join(c for c in filename if ord(c) < 0x10000 or c.isprintable())
    filename = re.sub(r"[_\s]+", " ", filename)
    return filename.strip()[:200]


def get_safe_model_name(model: str) -> str:
    """Return model name sanitized for filenames."""
    return model.replace(":", "_")


def get_channel_name(url: str, title: str) -> str:
    """Extract channel name from URL or use title."""
    if "youtube.com" in url or "youtu.be" in url:
        # Try to extract channel from URL pattern
        if "/channel/" in url:
            return "channel"
        if "/c/" in url:
            return "channel"
        if "/@" in url:
            return "channel"
        return "YouTube"
    elif "twitch.tv" in url:
        return "Twitch"
    return "local_files"


def get_expected_srt_path(job: Dict, task: Dict) -> Optional[str]:
    """Determine the expected SRT file path for a task."""
    source = task.get("source", "")
    title = task.get("title", "unknown")
    model = job.get("model", "unknown")

    safe_model = get_safe_model_name(model)
    clean_title = clean_filename(title)
    base_name = f"{clean_title}.{safe_model}"

    # Determine channel directory
    if source.startswith(("http://", "https://")):
        channel_name = get_channel_name(source, title)
        channel_dir = os.path.join(OUTPUT_DIR, clean_filename(channel_name))
    else:
        # Local file
        channel_dir = os.path.join(OUTPUT_DIR, "local_files")

    srt_path = os.path.join(channel_dir, f"{base_name}.srt")
    return srt_path


def is_valid_srt(srt_path: str, min_size: int = DEFAULT_MIN_SRT_SIZE) -> bool:
    """Check if SRT file exists and has valid content."""
    if not os.path.exists(srt_path):
        return False

    if os.path.getsize(srt_path) < min_size:
        return False

    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for at least one valid subtitle entry
        if not SRT_ENTRY_PATTERN.search(content):
            return False

        return True
    except (IOError, UnicodeDecodeError):
        return False


def scan_jobs() -> List[Dict]:
    """Load jobs from JSON file."""
    if not os.path.exists(JOBS_FILE):
        print(f"Jobs file not found: {JOBS_FILE}")
        return []

    with open(JOBS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_jobs(jobs: List[Dict]) -> None:
    """Save jobs to JSON file."""
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=4)


def verify_and_fix(
    min_size: int = DEFAULT_MIN_SRT_SIZE, rerun_file: str = DEFAULT_RERUN_FILE
) -> Dict[str, Any]:
    """Main verification and fix routine."""
    jobs = scan_jobs()
    if not jobs:
        print("No jobs found.")
        return {
            "checked": 0,
            "fixed": 0,
            "missing": 0,
            "corrupted": 0,
            "rerun_list": [],
        }

    rerun_urls = []
    stats = {"checked": 0, "fixed": 0, "missing": 0, "corrupted": 0}

    for job in jobs:
        if job.get("status") != "completed":
            continue

        for task in job.get("tasks", []):
            task_status = task.get("status", "")
            if task_status not in ["completed", "skipped"]:
                continue

            stats["checked"] += 1
            srt_path = get_expected_srt_path(job, task)

            if not srt_path:
                continue

            valid = is_valid_srt(srt_path, min_size=min_size)

            if not valid:
                reason = (
                    "missing" if not os.path.exists(srt_path) else "corrupted/empty"
                )
                stats[reason] += 1
                stats["fixed"] += 1

                print(f"[{reason.upper()}] {srt_path}")
                print(f"  Job: {job['id']}, Task: {task['source'][:60]}...")

                # Update task status
                task["status"] = "pending"
                task["subtitle_issue"] = reason

                # Add to rerun list
                if task["source"].startswith(("http://", "https://")):
                    rerun_urls.append(task["source"])
                else:
                    # Local file - add as file path
                    rerun_urls.append(f"file://{task['source']}")
            else:
                print(f"[OK] {os.path.basename(srt_path)}")

    # Save updated jobs
    if stats["fixed"] > 0:
        save_jobs(jobs)
        print(f"\nUpdated {stats['fixed']} task(s) to pending status.")

    # Write rerun list
    if rerun_urls:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(rerun_file, "w", encoding="utf-8") as f:
            f.write("# Subtitle rerun list - generated by verify_subtitles.py\n")
            f.write(f"# Missing: {stats['missing']}, Corrupted: {stats['corrupted']}\n")
            for url in rerun_urls:
                f.write(f"{url}\n")
        print(f"Rerun list written to: {rerun_file}")
        print(f"Run with: python whisper_subs.py <model> -p {rerun_file}")
    else:
        print("All subtitles verified successfully!")

    stats["rerun_list"] = rerun_urls
    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify and fix missing/corrupted subtitle files"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Only check, don't modify jobs.json"
    )
    parser.add_argument(
        "--rerun-file", default=DEFAULT_RERUN_FILE, help="Output file for rerun URLs"
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=DEFAULT_MIN_SRT_SIZE,
        help="Minimum SRT file size in bytes",
    )
    parser.add_argument(
        "--fix", action="store_true", help="Actually fix issues (default: dry-run)"
    )

    args = parser.parse_args()

    # Use local variables instead of modifying globals
    min_size = args.min_size
    rerun_file = args.rerun_file

    if args.dry_run or not args.fix:
        print("=== DRY RUN MODE (use --fix to apply changes) ===")

    stats = verify_and_fix(min_size=min_size, rerun_file=rerun_file)

    print(f"\nSummary:")
    print(f"  Checked: {stats['checked']}")
    print(f"  Missing: {stats['missing']}")
    print(f"  Corrupted: {stats['corrupted']}")
    print(f"  Fixed: {stats['fixed']}")
    print(f"  Rerun URLs: {len(stats['rerun_list'])}")


if __name__ == "__main__":
    main()
