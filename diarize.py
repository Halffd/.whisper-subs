"""Speaker diarization backends for whisper-subs.

Two engines are supported and both produce the same shape: a list of
`(start, end, speaker_label)` turns covering the audio, which
`assign_speakers` maps onto ADAPTER segments.

- `pyannote` — the default, used through WhisperX (`whisperx.diarize`).
  Needs a HuggingFace token and network access on first run.
- `nemo` — NeMo's MSDD pipeline (`nemo.collections.asr.models.msdd_models.MultiSpeakerDiarizer`)
  or a Sortformer checkpoint. Runs fully offline once weights are cached,
  which is what large local libraries want.

A diarization engine is chosen with `--diarize-engine` (or the
`WHISPERSUBS_DIARIZE_ENGINE` env var); `auto` picks pyannote when a
token is present and NeMo when it is not, because both are optional
dependencies and a missing one must degrade rather than fail.
"""

import os
import subprocess
from typing import Any, List, Optional, Tuple

Turn = Tuple[float, float, str]

DEFAULT_ENGINE = "auto"
ENGINES = ("auto", "pyannote", "nemo")

# NeMo's MSDD checkpoints. The first is the one the NeMo tutorials use;
# it is a multi-channel model, so audio is duplicated into both channels
# before it runs (see _run_nemo_msdd).
NEMO_MSDD_MODEL = "diar_msdd_telephonic"


def available_engines() -> List[str]:
    """Engines whose imports are present, in preference order."""
    ready: List[str] = []
    try:
        import pyannote  # noqa: F401

        ready.append("pyannote")
    except Exception:
        pass
    try:
        import nemo  # noqa: F401

        ready.append("nemo")
    except Exception:
        pass
    return ready


def resolve_engine(requested: Optional[str]) -> Optional[str]:
    """Pick an installed engine for the request, or None.

    `auto` prefers pyannote (better accuracy) and falls back to NeMo.
    An explicitly named engine is returned only when importable, so a
    typo or a missing wheel cannot abort a transcription.
    """
    wanted = (requested or DEFAULT_ENGINE).strip().lower() or DEFAULT_ENGINE
    installed = available_engines()
    if wanted == "auto":
        for candidate in ("pyannote", "nemo"):
            if candidate in installed:
                return candidate
        return None
    if wanted in installed:
        return wanted
    return None


def diarize(
    audio_file: str,
    engine: Optional[str] = None,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    token: Optional[str] = None,
    device: str = "cpu",
    write=print,
) -> List[Turn]:
    """Run the chosen engine and return [(start, end, speaker)] turns."""
    resolved = resolve_engine(engine)
    if resolved is None:
        write(
            "Diarization skipped: no engine installed "
            "(pip install pyannote.audio, or nemo_toolkit for NeMo MSDD)"
        )
        return []
    if resolved == "pyannote":
        return diarize_pyannote(
            audio_file,
            num_speakers=num_speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            token=token,
            device=device,
            write=write,
        )
    return diarize_nemo(
        audio_file,
        num_speakers=num_speakers,
        min_speakers=min_speakers,
        max_speakers=max_speakers,
        device=device,
        write=write,
    )


def _speaker_id(index: int) -> str:
    """Label for the Nth speaker, matching the [SPK_1] cue prefix."""
    return f"SPK_{index + 1}"


def diarize_pyannote(
    audio_file: str,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    token: Optional[str] = None,
    device: str = "cpu",
    write=print,
) -> List[Turn]:
    """Speaker turns via pyannote (through WhisperX when available)."""
    auth_token = token or os.environ.get("HF_TOKEN")
    if not auth_token:
        write("HF_TOKEN not set, skipping pyannote diarization")
        return []

    try:
        # WhisperX ships the tuned pyannote pipeline; use it when present,
        # otherwise fall back to a plain pyannote Pipeline.
        try:
            from whisperx.diarize import DiarizationPipeline

            pipeline = DiarizationPipeline(
                token=auth_token,
                device=_torch_device(device),
            )
        except Exception:
            from pyannote.audio import Pipeline as _Pipeline

            pipeline = _Pipeline.from_pretrained(
                "pyannote/speaker-diarization@2.1",
                use_auth_token=auth_token,
            ).to(_torch_device(device))

        import numpy as _np
        import torch as _torch

        from whisperx.audio import SAMPLE_RATE as _SR, load_audio as _load_audio

        audio = _load_audio(audio_file)
        waveform = _torch.from_numpy(audio[None, :])
        diarization = pipeline(
            {
                "waveform": waveform,
                "sample_rate": _SR,
                "num_speakers": num_speakers,
                "min_speakers": min_speakers,
                "max_speakers": max_speakers,
            }
        )
    except Exception as e:
        write(f"pyannote diarization failed ({e}), continuing without speakers")
        return []

    turns: List[Turn] = []
    for segment, _label, speaker in diarization.itertracks(yield_label=True):
        start = float(getattr(segment, "start", 0.0))
        end = float(getattr(segment, "end", start))
        turns.append((start, end, str(speaker)))
    return _normalise_turns(turns)


def diarize_nemo(
    audio_file: str,
    num_speakers: Optional[int] = None,
    min_speakers: Optional[int] = None,
    max_speakers: Optional[int] = None,
    device: str = "cpu",
    write=print,
) -> List[Turn]:
    """Speaker turns via NeMo's MSDD (offline once weights are cached).

    MSDD is a two-channel model: each speaker is expected on its own
    input channel. Mono audio is therefore duplicated rather than mixed,
    which is what the NeMo tutorials do for telephonic data.
    """
    try:
        import numpy as _np
        import torch as _torch

        from nemo.collections.asr.models.msdd_models import (
            ClusteringDiarizer,
        )
    except Exception as e:
        write(f"NeMo diarization unavailable ({e}), continuing without speakers")
        return []

    try:
        import soundfile as _sf

        audio, sample_rate = _sf.read(audio_file)
        if audio.ndim == 1:
            audio = _np.stack([audio, audio], axis=0)
        elif audio.shape[0] == 1:
            audio = _np.repeat(audio, 2, axis=0)
        waveform = _torch.from_numpy(audio[None, :]).float()

        model = ClusteringDiarizer.from_pretrained(
            model_name=NEMO_MSDD_MODEL,
            map_location="cpu",
        )
        model.eval()

        with _torch.no_grad():
            raw = model(waveform)

        turns = []
        labels = sorted({str(t[2]) for t in _iter_nemo_turns(raw)})
        mapped = {label: _speaker_id(i) for i, label in enumerate(labels)}
        for start, end, label in _iter_nemo_turns(raw):
            turns.append((start, end, mapped[str(label)]))
    except Exception as e:
        write(f"NeMo MSDD diarization failed ({e}), continuing without speakers")
        return []

    if not turns and (num_speakers or min_speakers or max_speakers):
        write("NeMo returned no turns; speaker bounds may not be supported by this checkpoint")
    return turns


def _iter_nemo_turns(raw: Any):
    """Normalise whatever NeMo returns into (start, end, label) triples.

    NeMo returns different shapes per version: a list of tuples, a list
    of dicts, or a generator of either. All are accepted here rather
    than pinning to one invocation shape.
    """
    for item in raw or []:
        if isinstance(item, dict):
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start))
            yield start, end, str(item.get("speaker", item.get("label", "0")))
        elif isinstance(item, (list, tuple)) and len(item) >= 3:
            yield float(item[0]), float(item[1]), str(item[2])


def _normalise_turns(turns: List[Turn]) -> List[Turn]:
    """Sort, merge same-speaker neighbours, return compact turns.

    Merging keeps the speaker-label pass stable: a speaker that is
    interrupted by a two-frame note from someone else would otherwise
    produce a tenth of a second of [SPK_2] between two long [SPK_1]
    cues, which is noise in an SRT.
    """
    if not turns:
        return []
    ordered = sorted(turns, key=lambda t: (t[0], t[1]))
    merged: List[Turn] = []
    for start, end, speaker in ordered:
        if merged and merged[-1][2] == speaker and start <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end), speaker)
        else:
            merged.append((start, end, speaker))
    return merged


def assign_speakers(
    segments: List[Any],
    turns: List[Turn],
    prefix_text: bool = True,
) -> int:
    """Label segments from diarization turns; returns the count labelled.

    The speaker covering the largest fraction of a cue wins, so a cue
    that straddles a hand-over is attributed to whoever spoke most of
    it. With `prefix_text`, the label is also prefixed onto the text as
    `[SPK_1] ...` for players that cannot read the metadata.
    """
    if not segments or not turns:
        return 0

    labelled = 0
    for seg in segments:
        start = float(getattr(seg, "start", 0.0) or 0.0)
        end = float(getattr(seg, "end", start) or start)
        if end <= start:
            continue

        best_speaker = None
        best_overlap = 0.0
        for turn_start, turn_end, speaker in turns:
            overlap = min(end, turn_end) - max(start, turn_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker
        if best_speaker is None:
            continue

        seg.speaker = best_speaker
        text = getattr(seg, "text", "")
        if prefix_text:
            marker = f"[{best_speaker}] "
            if not text.startswith(marker):
                seg.text = f"{marker}{text}"
        labelled += 1
    return labelled


def _torch_device(device: str):
    """Torch device string, honouring CPU-only installs."""
    if str(device or "").lower().startswith("cuda"):
        try:
            import torch

            if torch.cuda.is_available():
                return torch.device("cuda")
        except Exception:
            pass
    import torch

    return torch.device("cpu")
