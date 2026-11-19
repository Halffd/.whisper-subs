"""Pluggable Voice Activity Detection for whisper-subs.

Every VAD backend returns the same shape — a list of `(start, end)`
speech regions in seconds — so callers can trim audio before
transcription without caring which engine produced the regions.

Built-in engines:

- `silero`   — silero-vad, bundled weights, CPU-friendly (default)
- `pyannote` — pyannote's voice activity detection (shares HF auth)
- `webrtc`   — WebRTC VAD (very fast, English-tuned)
- `custom`   — any importable callable, e.g.
                `WHISPERSUBS_VAD=mypkg.mymodule:detect`

A custom callable may take either the audio path or the samples:

    detect(path, **params) -> [(start, end), ...]
    detect(samples, sample_rate) -> [(start, end), ...]

`params` are the key/value pairs given after a colon, so
`WHISPERSUBS_VAD=custom:mypkg.mod:detect --vad-param threshold=0.35`
passes `threshold="0.35"`.
"""

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

Region = Tuple[float, float]

DEFAULT_ENGINE = "silero"
ENGINES = ("silero", "pyannote", "webrtc", "custom")


def list_engines() -> List[str]:
    """All engine names, including any registered by a plugin."""
    return sorted(set(ENGINES) | set(_REGISTRY.keys()))


_REGISTRY: Dict[str, Callable[..., List[Region]]] = {}


def register_vad(name: str, fn: Callable[..., List[Region]]) -> None:
    """Register a VAD callable under `name` (plugin hook)."""
    _REGISTRY[name.strip().lower()] = fn


def resolve(
    requested: Optional[str] = None,
    params: Optional[Dict[str, str]] = None,
    write=print,
) -> Optional[Callable[..., List[Region]]]:
    """Return a ready-to-call VAD, or None when none is usable.

    An unknown or uninstalled engine degrades to "no VAD" rather than
    aborting the transcription: VAD is an optimization, and a missing
    optional dependency must not cost the user the subtitles.
    """
    wanted = (requested or os.environ.get("WHISPERSUBS_VAD") or DEFAULT_ENGINE)
    wanted = wanted.strip().lower() or DEFAULT_ENGINE

    if wanted in _REGISTRY:
        fn = _REGISTRY[wanted]
    elif wanted == "silero":
        fn = vad_silero
    elif wanted == "pyannote":
        fn = vad_pyannote
    elif wanted == "webrtc":
        fn = vad_webrtc
    elif wanted == "custom":
        fn = _load_custom(params, write)
        if fn is None:
            return None
    else:
        write(f"Unknown VAD '{wanted}'; running with no VAD")
        return None

    extra = dict(params or {})
    if not extra and os.environ.get("WHISPERSUBS_VAD_PARAMS"):
        extra = _parse_params(os.environ["WHISPERSUBS_VAD_PARAMS"])
    if extra:
        return functools_partial(fn, **extra)
    return fn


def detect(
    audio_path: str,
    requested: Optional[str] = None,
    params: Optional[Dict[str, str]] = None,
    write=print,
) -> List[Region]:
    """Speech regions for `audio_path`, empty when no engine is usable."""
    engine = resolve(requested, params, write)
    if engine is None:
        return []
    try:
        regions = engine(audio_path)
    except Exception as e:
        write(f"VAD '{requested or DEFAULT_ENGINE}' failed ({e}), using raw audio")
        return []
    return merge_regions(regions)


def merge_regions(regions: List[Region]) -> List[Region]:
    """Sort and coalesce touching/near-touching regions."""
    if not regions:
        return []
    ordered = sorted((float(a), float(b)) for a, b in regions if float(b) > float(a))
    if not ordered:
        return []
    merged: List[Region] = [ordered[0]]
    for start, end in ordered[1:]:
        if start <= merged[-1][1] + 0.01:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _read_samples(audio_path: str) -> Tuple[Optional[List[float]], Optional[int]]:
    """16 kHz mono samples for engines that take audio data."""
    try:
        import numpy as np

        import soundfile as sf

        data, rate = sf.read(audio_path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if rate != 16000:
            import librosa

            data = librosa.resample(data, orig_sr=rate, target_sr=16000)
            rate = 16000
        return data, rate
    except Exception:
        return None, None


def vad_silero(audio_path: str) -> List[Region]:
    """Speech regions via silero-vad."""
    try:
        from silero_vad import load_silero_vad, read_audio, get_speech_timestamps
    except ImportError as e:
        raise RuntimeError(f"silero-vad not installed ({e})")

    model = load_silero_vad()
    wav = read_audio(audio_path)
    timestamps = get_speech_timestamps(
        wav, model, return_seconds=True, min_silence_duration_ms=500
    )
    return [(t["start"], t["end"]) for t in timestamps]


def vad_webrtc(audio_path: str) -> List[Region]:
    """Speech regions via WebRTC VAD (very fast, English-tuned)."""
    try:
        import webrtcvad
        import wave
    except ImportError as e:
        raise RuntimeError(f"webrtcvad not installed ({e})")

    with wave.open(audio_path, "rb") as handle:
        rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())

    vad = webrtcvad.Vad(1)
    chunk = int(rate * 0.03) * width
    regions: List[Region] = []
    start: Optional[float] = None
    for index in range(0, len(frames) - chunk + 1, chunk):
        voiced = vad.is_speech(frames[index : index + chunk], rate)
        offset = index / (rate * width)
        if voiced and start is None:
            start = offset
        elif not voiced and start is not None:
            regions.append((start, offset))
            start = None
    if start is not None:
        regions.append((start, len(frames) / (rate * width)))
    return regions


def vad_pyannote(audio_path: str) -> List[Region]:
    """Speech regions via pyannote's VAD."""
    try:
        from pyannote.audio import Pipeline
    except ImportError as e:
        raise RuntimeError(f"pyannote.audio not installed ({e})")

    token = os.environ.get("HF_TOKEN")
    pipeline = Pipeline.from_pretrained(
        "pyannote/voice-activity-detection",
        use_auth_token=token,
    )
    import torch

    from whisperx.audio import SAMPLE_RATE, load_audio

    waveform = torch.from_numpy(load_audio(audio_file=None, audio=audio_path)[None, :])
    result = pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE})
    return [(seg.start, seg.end) for seg in result.itersegments()]


def _parse_params(text: str) -> Dict[str, str]:
    """`a=1,b=two` into {"a": "1", "b": "two"}."""
    params: Dict[str, str] = {}
    for chunk in text.split(","):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        params[key.strip()] = value.strip()
    return params


def parse_vad_params(items: Optional[List[str]]) -> Dict[str, str]:
    """`["a=1", "b=two"]` into {"a": "1", "b": "two"} (repeated flag form)."""
    params: Dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        params[key.strip()] = value.strip()
    return params


def _load_custom(
    params: Optional[Dict[str, str]],
    write,
) -> Optional[Callable[..., List[Region]]]:
    """Load `module:callable` from WHISPERSUBS_VAD=...:... params."""
    target = None
    if params:
        target = params.pop("target", None)
    target = target or os.environ.get("WHISPERSUBS_VAD_CUSTOM")
    if not target:
        write("Custom VAD requested but no target given (module:callable)")
        return None

    module_name, _, callable_name = target.rpartition(":")
    if not module_name or not callable_name:
        write(f"Custom VAD target {target!r} must be 'module:callable'")
        return None
    try:
        import importlib

        module = importlib.import_module(module_name)
        fn = getattr(module, callable_name)
    except Exception as e:
        write(f"Custom VAD {target} could not be loaded ({e})")
        return None
    return fn


def functools_partial(fn: Callable[..., Any], **params: Any) -> Callable[..., Any]:
    """Bind keyword params (avoids importing functools for one call)."""
    def bound(*args: Any, **kwargs: Any) -> Any:
        merged = dict(params)
        merged.update(kwargs)
        return fn(*args, **merged)

    return bound


class WhisperXVAD:
    """Adapts precomputed regions to WhisperX's Vad protocol.

    WhisperX only ever calls `preprocess_audio`, then the callable
    itself, then merges chunks. Regions are precomputed once from the
    audio path, so `__call__` just replays them. `issubclass(type(model), Vad)`
    in `asr.py` selects the wrapper path, so the returned object must
    actually subclass `whisperx.vads.vad.Vad` — see
    `build_whisperx_vad`, which creates the subclass at runtime because
    pyannote (a WhisperX dependency) is optional here.
    """

    def __init__(self, regions: List[Region]):
        self.regions = regions

    @staticmethod
    def preprocess_audio(audio):
        """WhisperX passes the raw waveform; keep it for VADs needing samples."""
        return audio

    @staticmethod
    def merge_chunks(segments, chunk_size, onset, offset):
        from whisperx.vads.vad import Vad

        return Vad.merge_chunks(segments, chunk_size, onset, offset)

    def __call__(self, *args, **kwargs):
        # whisperx.diarize.Segment, not pyannote.core.Segment:
        # Vad.merge_chunks reads seg.speaker, and whisperx's own Silero
        # VAD returns exactly these objects.
        from whisperx.diarize import Segment

        return [
            Segment(float(start), float(end), "UNKNOWN") for start, end in self.regions
        ]


def build_whisperx_vad(
    audio_path: str,
    requested: Optional[str],
    params: Optional[Dict[str, str]] = None,
    write=print,
):
    """Run the selected engine and wrap the regions for WhisperX.

    Returns None when the engine is unusable so callers can fall back
    to WhisperX's built-in VAD (which needs no wrapper).
    """
    regions = detect(audio_path, requested=requested, params=params, write=write)
    if not regions:
        return None

    try:
        from whisperx.vads.vad import Vad

        class WhisperXVad(Vad, WhisperXVAD):
            """A WhisperXVAD that also satisfies issubclass(..., Vad)."""

            def __init__(self, regions: List[Region]):
                # Vad.__init__ validates vad_onset only; the wrapper's
                # __init__ stores the regions. Keep the wrapper's.
                WhisperXVAD.__init__(self, regions)

        return WhisperXVad(regions)
    except Exception as e:
        write(f"WhisperX VAD wrapper unavailable ({e}); using raw WhisperX VAD")
        return None
