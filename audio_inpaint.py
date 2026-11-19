"""Audio inpainting — fill the gaps a transcription left behind.

The problem this solves: whisper writes its own timestamps verbatim, so when
it emits nothing for a stretch of audio, the finished SRT has a hole and no
later stage can tell the difference between "nothing to transcribe" and
"speech that was missed". The user sees exactly that — silent stretches in
the middle of otherwise complete subtitles.

The fix is to re-transcribe the missing audio on its own:

1. find the gaps in the finished SRT,
2. cut each one out of the original audio with ffmpeg,
3. run Whisper over that clip *alone*, with `condition_on_previous_text=False`
   so a hallucinated run cannot seed itself from the text that came before
   the hole, which is what makes a second attempt over broken up audio drift,
4. splice the cues back into the SRT, reordered and renumbered.

Because the re-run is a separate `WhisperModel` pass it can be retried with a
different model, and it never touches the cues that were already good.

Runs on the local faster-whisper backend (the same one the CLI's local path
uses); the adapter backends are not involved, since this needs a model object
to feed a clipped audio file to.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

Region = Tuple[float, float]


def srt_time_to_seconds(time_str: str) -> float:
    """`HH:MM:SS,mmm` -> seconds."""
    try:
        hours, minutes, rest = time_str.strip().split(":")
        seconds, millis = rest.split(",")
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0
    except (ValueError, AttributeError):
        return 0.0


def format_srt(seconds: float) -> str:
    """`seconds` -> `HH:MM:SS,mmm`."""
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours, rem = divmod(total_ms, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_srt(path: str) -> List[Dict[str, Any]]:
    """Cues of an SRT file as dicts (start/end in seconds, raw text)."""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []

    cue_re = re.compile(
        r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)"
    )
    cues: List[Dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        ts_index = None
        match = None
        for index, line in enumerate(lines):
            match = cue_re.search(line)
            if match:
                ts_index = index
                break
        if not match or ts_index is None:
            continue
        body = "\n".join(lines[ts_index + 1 :]).strip()
        if not body:
            continue
        cues.append(
            {
                "start": srt_time_to_seconds(match.group(1)),
                "end": srt_time_to_seconds(match.group(2)),
                "text": body,
            }
        )
    return cues


def find_gaps(
    cues: List[Dict[str, Any]],
    duration: Optional[float] = None,
    min_gap_seconds: float = 3.0,
    padding: float = 0.25,
) -> List[Region]:
    """Holes in a transcript, widened by `padding` on each side.

    A gap that starts mid-sentence is speech that was missed; a gap between
    finished sentences may just be silence. Both are returned — the caller
    decides — and the leading/trailing gaps (before the first cue and after
    the last) are included when `duration` is known.
    """
    if not cues:
        return []

    ordered = sorted(cues, key=lambda c: c["start"])
    spans: List[Region] = []
    if ordered[0]["start"] > min_gap_seconds:
        spans.append((0.0, ordered[0]["start"]))
    for prev, cur in zip(ordered, ordered[1:]):
        hole = cur["start"] - prev["end"]
        if hole >= min_gap_seconds:
            spans.append((prev["end"], cur["start"]))
    if duration is not None and duration - ordered[-1]["end"] > min_gap_seconds:
        spans.append((ordered[-1]["end"], duration))

    padded: List[Region] = []
    for start, end in spans:
        lo = max(0.0, start - padding)
        hi = end + padding
        # A trailing gap must not run past EOF: ffmpeg would hand Whisper a
        # clip shorter than claimed and the cue offsets would drift.
        if duration is not None:
            hi = min(hi, duration)
        if hi > lo:
            padded.append((lo, hi))
    return padded


def _merge_cues(existing: List[Dict[str, Any]], added: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Concatenate, deduplicated on identical timestamps, time-ordered."""
    seen = set()
    merged: List[Dict[str, Any]] = []
    for cue in list(existing) + list(added):
        key = (round(cue["start"], 2), round(cue["end"], 2))
        if key in seen:
            continue
        seen.add(key)
        merged.append(cue)
    return sorted(merged, key=lambda c: c["start"])


def write_srt(path: str, cues: List[Dict[str, Any]]) -> bool:
    """Write cues as a sequential SRT file."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            for index, cue in enumerate(cues, 1):
                handle.write(f"{index}\n")
                handle.write(f"{format_srt(cue['start'])} --> {format_srt(cue['end'])}\n")
                handle.write(f"{cue['text']}\n\n")
        return True
    except OSError:
        return False


def cut_segment(
    audio_path: str,
    output_path: str,
    start: float,
    end: float,
    audio_track: Optional[str] = None,
) -> bool:
    """Cut `[start, end)` out of `audio_path` into a 16 kHz mono M4A."""
    import audio_io

    return audio_io.cut_audio(
        audio_path,
        output_path,
        start=str(start),
        end=str(end),
        audio_track=audio_track,
    )


@dataclass
class InpaintResult:
    """What one inpainting pass did."""

    gaps: int = 0
    filled: int = 0
    added_cues: int = 0
    recovered_seconds: float = 0.0
    failures: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "gaps": self.gaps,
            "filled": self.filled,
            "added_cues": self.added_cues,
            "recovered_seconds": round(self.recovered_seconds, 2),
            "failures": self.failures,
        }


def inpaint_srt(
    srt_path: str,
    audio_path: str,
    model: str = "medium.en",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    min_gap_seconds: float = 3.0,
    audio_track: Optional[str] = None,
    write: Callable = print,
    work_dir: Optional[str] = None,
) -> InpaintResult:
    """Re-transcribe the holes in `srt_path` and splice the cues back.

    Never overwrites on failure: the new cues are only written once the whole
    pass has produced something, so a crash mid-way leaves the original file
    intact.
    """
    import audio_io

    write = write or (lambda _m: None)
    result = InpaintResult()

    cues = parse_srt(srt_path)
    if not cues:
        write("No usable cues to inpaint against")
        return result

    duration = audio_io.probe_duration(audio_path)
    gaps = find_gaps(cues, duration, min_gap_seconds=min_gap_seconds)
    result.gaps = len(gaps)
    if not gaps:
        write(f"No gaps >= {min_gap_seconds:.1f}s to inpaint")
        return result

    total = sum(b - a for a, b in gaps)
    write(
        f"Inpainting {len(gaps)} gap(s) totalling {total:.1f}s "
        f"with model {model}"
    )

    try:
        import faster_whisper
    except ImportError:
        write("faster-whisper is required for inpainting")
        result.failures.append("faster-whisper not installed")
        return result

    try:
        whisper = faster_whisper.WhisperModel(
            model, device=device, compute_type=compute_type,
            cpu_threads=os.cpu_count() or 4,
        )
    except Exception as exc:
        write(f"Could not load {model}: {exc}")
        result.failures.append(str(exc))
        return result

    tmp_dir = work_dir or tempfile.mkdtemp(prefix="wsub_inpaint_")
    added: List[Dict[str, Any]] = []

    for index, (start, end) in enumerate(gaps, 1):
        clip = os.path.join(tmp_dir, f"gap_{index}.m4a")
        if not cut_segment(audio_path, clip, start, end, audio_track):
            result.failures.append(f"gap {index}: cut failed")
            continue
        try:
            segments, _info = whisper.transcribe(
                clip,
                language=language,
                # The whole point of re-transcribing the clip alone: a
                # hallucinated run cannot seed itself from the text that ran
                # up to the hole, which is what makes a second attempt over
                # broken-up audio drift.
                condition_on_previous_text=False,
            )
            new = [
                {
                    "start": start + float(seg.start),
                    "end": start + float(seg.end),
                    "text": seg.text.strip(),
                }
                for seg in segments
                if seg.text.strip()
            ]
        except Exception as exc:
            result.failures.append(f"gap {index}: {exc}")
            new = []

        if not new:
            result.failures.append(f"gap {index}: no speech found")
            continue

        added.extend(new)
        result.filled += 1
        result.recovered_seconds += sum(c["end"] - c["start"] for c in new)
        write(
            f"  gap {index}/{len(gaps)} [{start:.1f}s-{end:.1f}s] -> "
            f"{len(new)} cue(s)"
        )
        try:
            os.unlink(clip)
        except OSError:
            pass

    if added:
        merged = _merge_cues(cues, added)
        if write_srt(srt_path, merged):
            result.added_cues = len(merged) - len(cues)
            write(
                f"Inpainting added {result.added_cues} cue(s) "
                f"({result.recovered_seconds:.1f}s recovered)"
            )
        else:
            result.failures.append("could not write the merged SRT")
    if not work_dir:
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    return result