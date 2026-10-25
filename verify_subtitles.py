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

# Regex patterns to extract subtitle file paths from wrapper scripts
SH_SUB_PATTERN = re.compile(r'--sub-file=(?:"([^"]+)"|\'([^\']+)\'|(\S+))')
BAT_SUB_PATTERN = re.compile(r'--sub-file=(?:"([^"]+)"|(\S+))')
PS1_SUB_PATTERN = re.compile(r'--sub-file=(?:"([^"]+)"|\'([^\']+)\'|(\S+))')
HTM_URL_PATTERN = re.compile(r"URL=['\"]([^'\"]+)['\"]")
M3U_SUB_PATTERN = re.compile(r"#EXTINF:.*,\s*.*\n([^\n]+\.srt)")


def extract_sub_from_sh(filepath: str) -> List[str]:
    """Extract subtitle file paths from shell script."""
    subs = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        for match in SH_SUB_PATTERN.finditer(content):
            # match has 3 groups, only one will be non-None
            sub = match.group(1) or match.group(2) or match.group(3)
            if sub:
                subs.append(sub.strip("'\""))
    except Exception:
        pass
    return subs


def extract_sub_from_bat(filepath: str) -> List[str]:
    """Extract subtitle file paths from batch file."""
    subs = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        for match in BAT_SUB_PATTERN.finditer(content):
            sub = match.group(1) or match.group(2)
            if sub:
                subs.append(sub.strip('"'))
    except Exception:
        pass
    return subs


def extract_sub_from_ps1(filepath: str) -> List[str]:
    """Extract subtitle file paths from PowerShell script."""
    subs = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        for match in PS1_SUB_PATTERN.finditer(content):
            sub = match.group(1) or match.group(2) or match.group(3)
            if sub:
                subs.append(sub.strip("'\""))
    except Exception:
        pass
    return subs


def extract_url_from_htm(filepath: str) -> Optional[str]:
    """Extract URL from HTML redirect file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        match = HTM_URL_PATTERN.search(content)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def extract_sub_from_m3u(filepath: str) -> List[str]:
    """Extract subtitle file paths from M3U playlist."""
    subs = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        for match in M3U_SUB_PATTERN.finditer(content):
            sub = match.group(1).strip()
            if sub:
                subs.append(sub)
    except Exception:
        pass
    return subs


def extract_subtitle_refs(wrapper_path: str) -> List[str]:
    """Extract all subtitle file references from a wrapper script."""
    ext = Path(wrapper_path).suffix.lower()
    if ext == ".sh":
        return extract_sub_from_sh(wrapper_path)
    elif ext == ".bat":
        return extract_sub_from_bat(wrapper_path)
    elif ext == ".ps1":
        return extract_sub_from_ps1(wrapper_path)
    elif ext == ".htm":
        url = extract_url_from_htm(wrapper_path)
        return []  # HTM files don't reference local subs directly
    elif ext == ".m3u":
        return extract_sub_from_m3u(wrapper_path)
    return []


def scan_wrapper_scripts(root_dir: str) -> Dict[str, List[str]]:
    """Recursively scan directory for wrapper scripts and their subtitle references.

    Returns dict mapping wrapper_script_path -> list of referenced subtitle paths.
    """
    wrapper_exts = {".sh", ".bat", ".ps1", ".htm", ".m3u"}
    results = {}

    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if Path(file).suffix.lower() in wrapper_exts:
                wrapper_path = os.path.join(root, file)
                subs = extract_subtitle_refs(wrapper_path)
                if subs:
                    results[wrapper_path] = subs
    return results


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


def assess_srt(srt_path: str, min_size: int = DEFAULT_MIN_SRT_SIZE) -> Dict[str, Any]:
    """The single verdict on whether a subtitle file is usable.

    Both this module and srt_checker used to decide this independently: this
    file with a size floor plus one regex hit, srt_checker by asking
    transcribe.verify_srt_file. There is now one rule, in
    transcribe.verify_srt_file, which actually parses the cues and separates
    fatal problems from warnings. The size floor stays because a file below
    it cannot hold a plausible cue even when the parser is lenient.

    Returns {"ok", "reason", "kind", "segments"} where kind is "missing",
    "empty", "stubbed", "corrupt", or "" when the file is usable.
    """
    import transcribe

    if not os.path.exists(srt_path):
        return {"ok": False, "reason": "missing", "kind": "missing", "segments": 0}

    size = os.path.getsize(srt_path)
    if size < min_size:
        # Separate the in-progress placeholder from genuinely empty output.
        try:
            with open(srt_path, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(200)
        except OSError:
            head = ""
        kind = "stubbed" if "Transcription in progress" in head else "empty"
        return {
            "ok": False,
            "reason": f"{kind} ({size} bytes)",
            "kind": kind,
            "segments": 0,
        }

    report = transcribe.verify_srt_file(srt_path, write=lambda m: None)
    if not report["ok"]:
        problems = "; ".join(report["problems"][:3])
        kind = "stubbed" if "placeholder" in problems else "corrupt"
        return {"ok": False, "reason": problems, "kind": kind, "segments": 0}

    return {"ok": True, "reason": "", "kind": "", "segments": report["segments"]}


def is_valid_srt(srt_path: str, min_size: int = DEFAULT_MIN_SRT_SIZE) -> bool:
    """Backwards-compatible wrapper around assess_srt()."""
    return assess_srt(srt_path, min_size=min_size)["ok"]


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
    min_size: int = DEFAULT_MIN_SRT_SIZE,
    rerun_file: str = DEFAULT_RERUN_FILE,
    apply_changes: bool = True,
    clean: bool = False,
) -> Dict[str, Any]:
    """Check finished subtitles, reset broken tasks, and optionally clean up.

    apply_changes=False is a true dry run: jobs.json is left untouched.
    clean=True additionally deletes empty/stubbed subtitles and wrapper
    scripts pointing nowhere (see cleanup_outputs).
    """
    stats = {
        "checked": 0,
        "fixed": 0,
        "missing": 0,
        "corrupted": 0,
        "removed": 0,
        "rerun_list": [],
    }

    if not apply_changes:
        print("=== DRY RUN: jobs.json will not be modified ===")

    jobs = scan_jobs()
    if not jobs:
        print("No jobs found.")
        if clean:
            import cleanup_outputs

            stats.update(
                cleanup_outputs.clean_outputs(OUTPUT_DIR, apply=True, min_size=min_size)
            )
        return stats

    rerun_urls: List[str] = []

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

            verdict = assess_srt(srt_path, min_size=min_size)

            if not verdict["ok"]:
                # Map onto the two reported buckets; empty/stubbed are counted
                # as corrupted since both mean "needs redoing".
                reason = "missing" if verdict["kind"] == "missing" else "corrupted"
                stats[reason] += 1
                stats["fixed"] += 1

                print(f"[{verdict['kind'].upper()}] {srt_path}")
                if verdict["reason"]:
                    print(f"  {verdict['reason']}")
                print(f"  Job: {job['id']}, Task: {task['source'][:60]}...")

                # Update task status (skipped in a dry run)
                if apply_changes:
                    task["status"] = "pending"
                    task["subtitle_issue"] = verdict["kind"]

                # Add to rerun list
                if task["source"].startswith(("http://", "https://")):
                    rerun_urls.append(task["source"])
                else:
                    # Local file - add as file path
                    rerun_urls.append(f"file://{task['source']}")
            else:
                print(f"[OK] {os.path.basename(srt_path)}")

    # Also scan wrapper scripts recursively for orphaned/broken references
    print("\n=== Scanning wrapper scripts for subtitle references ===")
    wrapper_refs = scan_wrapper_scripts(OUTPUT_DIR)
    wrapper_stats = {"checked": 0, "missing": 0, "corrupted": 0}
    seen_urls = set(rerun_urls)  # Deduplicate URLs

    for wrapper_path, sub_refs in wrapper_refs.items():
        for sub_ref in sub_refs:
            wrapper_stats["checked"] += 1
            # Normalize path
            sub_ref = sub_ref.strip("'\"")

            # Skip .unfinished.srt files (temporary)
            if ".unfinished.srt" in sub_ref:
                continue

            if not os.path.isabs(sub_ref):
                # Relative path - resolve relative to wrapper script directory
                sub_path = os.path.join(os.path.dirname(wrapper_path), sub_ref)
            else:
                sub_path = sub_ref

            # Convert Windows paths (C:\Users\...) to Linux paths
            # Handle pure Windows paths
            import re

            if sub_path.startswith("C:\\") or sub_path.startswith("C:/"):
                # Convert C:\Users\<any>\Documents\Youtube-Subs -> /home/.../Documents/Youtube-Subs
                sub_path = re.sub(
                    r"C[\\/]Users[\\/][^\\/]+[\\/]Documents[\\/]Youtube-Subs",
                    OUTPUT_DIR,
                    sub_path,
                    flags=re.IGNORECASE,
                )
                sub_path = sub_path.replace("\\", "/")
            # Also handle case where Windows path is embedded after Linux path
            # e.g., /home/.../Youtube-Subs/André Young/C:\Users\...
            elif "C:\\Users\\" in sub_path or "C:/Users/" in sub_path:
                # Find the last occurrence of 'Youtube-Subs' and keep everything after it
                parts = re.split(r"(?i)Youtube-Subs", sub_path)
                if len(parts) > 1:
                    # Keep the last part (after the last Youtube-Subs)
                    sub_path = os.path.join(OUTPUT_DIR, parts[-1].lstrip("/\\"))
                sub_path = sub_path.replace("\\", "/")

            sub_path = os.path.normpath(sub_path)

            wrapper_verdict = assess_srt(sub_path, min_size=min_size)

            if not wrapper_verdict["ok"]:
                reason_key = (
                    "missing" if wrapper_verdict["kind"] == "missing" else "corrupted"
                )
                wrapper_stats[reason_key] += 1
                stats["fixed"] += 1

                print(f"[{wrapper_verdict['kind'].upper()}] {sub_path}")
                print(f"  Referenced by: {wrapper_path}")

                # Try to find associated URL from HTML file
                htm_file = (
                    wrapper_path.replace(".sh", ".htm")
                    .replace(".bat", ".htm")
                    .replace(".ps1", ".htm")
                )
                if os.path.exists(htm_file):
                    url = extract_url_from_htm(htm_file)
                    if url and url not in seen_urls:
                        rerun_urls.append(url)
                        seen_urls.add(url)
                        print(f"  Found URL: {url}")
            else:
                print(
                    f"[OK] {os.path.basename(sub_path)} (from {os.path.basename(wrapper_path)})"
                )

    if wrapper_stats["checked"] > 0:
        stats["checked"] += wrapper_stats["checked"]
        stats["missing"] += wrapper_stats["missing"]
        stats["corrupted"] += wrapper_stats["corrupted"]
        print(
            f"\nWrapper scan: {wrapper_stats['checked']} refs, {wrapper_stats['missing']} missing, {wrapper_stats['corrupted']} corrupted"
        )

    # Save updated jobs
    if stats["fixed"] > 0:
        if apply_changes:
            save_jobs(jobs)
            print(f"\nUpdated {stats['fixed']} task(s) to pending status.")
        else:
            print(f"\nDry run: {stats['fixed']} task(s) would be reset to pending.")

    # Remove files that serve no purpose
    if clean:
        import cleanup_outputs

        print("\n=== Cleaning empty/stubbed subtitles and dangling wrappers ===")
        outcome = cleanup_outputs.clean_outputs(
            OUTPUT_DIR,
            apply=True,
            min_size=min_size,
            write=lambda m: print(m),
        )
        stats["removed"] = outcome["removed"]
        stats["cleaned"] = {
            "empty_srts": outcome["empty_srts"],
            "stubbed_srts": outcome["stubbed_srts"],
            "orphan_wrappers": outcome["orphan_wrappers"],
        }
        print(f"Removed {outcome['removed']} file(s).")

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
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete empty/stubbed subtitles and wrapper scripts pointing nowhere.",
    )

    args = parser.parse_args()

    # Use local variables instead of modifying globals
    min_size = args.min_size
    rerun_file = args.rerun_file
    apply_changes = bool(args.fix) and not args.dry_run

    if not apply_changes:
        print("=== DRY RUN MODE (use --fix to apply changes) ===")

    stats = verify_and_fix(
        min_size=min_size,
        rerun_file=rerun_file,
        apply_changes=apply_changes,
        clean=bool(args.clean),
    )

    print(f"\nSummary:")
    print(f"  Checked: {stats['checked']}")
    print(f"  Missing: {stats['missing']}")
    print(f"  Corrupted: {stats['corrupted']}")
    print(f"  Fixed: {stats['fixed']}")
    print(f"  Removed: {stats.get('removed', 0)}")
    print(f"  Rerun URLs: {len(stats['rerun_list'])}")


if __name__ == "__main__":
    main()
