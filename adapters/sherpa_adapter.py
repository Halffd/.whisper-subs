"""SherpaAdapter - ONNX Runtime transcription via sherpa-onnx.

Ported from inaudio (github.com/shikki841/inaudio), which runs the same
NVIDIA Parakeet / Nemotron encoders through sherpa-onnx instead of the much
heavier NeMo runtime. The useful pieces carried over:

* verified model download (pinned SHA-256, staged, atomically promoted)
  -- see sherpa_models.py
* a resident recognizer, so a 650 MB model is loaded once and reused for
  every task in a run instead of being reloaded per file
* CPU execution with a configurable thread count, and CUDA when requested

What inaudio does not need and this adapter adds: word-level timestamps.
sherpa's offline transducer returns per-token times, which are regrouped into
readable subtitle segments. Streaming models (Nemotron) are decoded in chunks
with endpoint detection, so segments are produced as speech ends.

Both paths work on plain 16 kHz mono WAV, decoded with the stdlib `wave`
module after ffmpeg normalises whatever yt-dlp downloaded.
"""

import os
import subprocess
import sys
import wave
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter

SAMPLE_RATE = 16000

# sherpa's offline encoder cannot take unbounded input: past a few minutes the
# attention mask stops broadcasting and ONNX Runtime aborts with
# "Attempting to broadcast an axis by a dimension other than 1" (seen at ~12
# minutes of audio). Long media is therefore decoded in overlapping windows.
# Values are overridable for unusual material.
WINDOW_SECONDS = float(os.environ.get("WHISPERSUBS_SHERPA_WINDOW", "30"))
OVERLAP_SECONDS = float(os.environ.get("WHISPERSUBS_SHERPA_OVERLAP", "2"))

# Timestamps are frame-quantised (10 ms), so float noise around a boundary is
# expected; this keeps a token the previous window already emitted.
_TIMESTAMP_EPSILON = 0.02

# Subtitles read badly when a line runs long or sits on screen too briefly.
MAX_SEGMENT_CHARS = 84
MAX_SEGMENT_SECONDS = 6.0
MIN_SEGMENT_SECONDS = 0.2
# A cue shorter than this is not worth its own timestamp range, so an
# overflowing cue keeps its full text rather than splitting too early.
MIN_SEGMENT_CHARS = 24

# One loaded recognizer per (model, provider). Reloading a 650 MB encoder for
# every file dominated runtime before; this keeps it resident.
_RECOGNIZERS: Dict[Tuple[str, str], Any] = {}


def clear_recognizer_cache() -> None:
    """Drop cached recognizers (used by tests and after a model swap)."""
    _RECOGNIZERS.clear()


def _read_wav_mono(path: str) -> Tuple[Any, int]:
    """Read a PCM WAV file into mono float samples in [-1, 1].

    Returns an array('f') rather than a list: a 13-minute video is ~12M
    samples, which as a list of Python floats costs hundreds of megabytes
    (a pointer plus an object per element) against 49 MB packed.
    """
    import array as _array

    with wave.open(path, "rb") as f:
        channels = f.getnchannels()
        width = f.getsampwidth()
        rate = f.getframerate()
        frames = f.readframes(f.getnframes())

    if width == 2:
        raw = _array.array("h")
        raw.frombytes(frames)
        del frames
        samples = _array.array("f", [s / 32768.0 for s in raw])
        del raw
    elif width == 4:
        raw = _array.array("i")
        raw.frombytes(frames)
        del frames
        samples = _array.array("f", [s / 2147483648.0 for s in raw])
        del raw
    elif width == 1:
        samples = _array.array("f", [(b - 128) / 128.0 for b in frames])
    else:
        raise RuntimeError(f"Unsupported WAV sample width: {width} bytes")

    if channels > 1:
        # Interleaved: keep every channels-th sample.
        samples = samples[::channels]

    return samples, rate


def _to_wav(audio_file: str, write: Callable = print) -> str:
    """Normalise any input to 16 kHz mono PCM WAV.

    Returns the original path when it already is 16 kHz mono, so a file that
    needs no conversion is never copied.
    """
    try:
        with wave.open(audio_file, "rb") as f:
            if f.getnchannels() == 1 and f.getframerate() == SAMPLE_RATE:
                return audio_file
    except (wave.Error, EOFError, OSError):
        pass

    converted = f"{audio_file}.sherpa.wav"
    write("Converting audio to 16 kHz mono WAV for sherpa-onnx...")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        audio_file,
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        converted,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(converted):
        raise RuntimeError(f"Audio conversion failed: {result.stderr[-400:]}")
    return converted


def _group_tokens(
    tokens: List[str],
    times: List[float],
    max_chars: int = MAX_SEGMENT_CHARS,
    max_seconds: float = MAX_SEGMENT_SECONDS,
) -> List[Segment]:
    """Group token/time pairs into subtitle-sized segments.

    sherpa returns BPE-ish pieces (" " , "M", "onday") with per-token times,
    so cues are accumulated until they would run too long or too wide. A cue
    never ends mid-word: when the limit is crossed the cut falls back to the
    last whitespace, which is why "grandinha" stays in one piece instead of
    surfacing as "grandin" / "ha".
    """
    segments: List[Segment] = []
    if not tokens:
        return segments

    def emit(begin: int, end: int) -> None:
        text = "".join(tokens[begin:end]).strip()
        if not text:
            return
        segments.append(
            Segment(
                start=round(max(0.0, times[begin]), 3),
                end=round(max(times[begin], times[end - 1]), 3),
                text=text,
            )
        )

    def word_break(begin: int, limit: int) -> Optional[int]:
        """Largest k in (begin, limit] where a cue may end without cutting a
        word in half.

        A cue may end at k only when token k is the last token of its word,
        i.e. when the token after k starts a new word. Both conventions in
        the wild have to be handled:

        - whitespace-marked tokens (" grandin"), where the *next* token
          begins with a space;
        - a word split across bare BPE tokens ("grandin", "ha", "."),
          where the next token " o" begins with a space.

        Returning the *start* of the next word (the previous behaviour)
        made cue 1 end on "…grandin" with "ha." opening the next cue,
        because the token that follows a bare word-initial token is
        usually bare too.
        """
        # The scan starts one past `limit`: `limit` is the token that
        # overflowed, and the word it belongs to may legitimately be
        # completed by it. Starting at `limit` itself (the old behaviour)
        # never saw that token, so the cue was cut on the token before it.
        for k in range(min(limit + 1, total - 1), begin, -1):
            nxt = tokens[k + 1] if k + 1 < total else None
            if nxt is None:
                return k + 1
            if nxt[:1] in (" ", "\n", "\t"):
                return k + 1
        # No boundary inside the cue: fall back to the last token that is
        # short enough, so a mid-word cut at max_chars is still preferred
        # over an unusably short cue.
        return None

    total = len(tokens)
    index = 0
    while index < total:
        end = index + 1
        # Grow while the cue stays inside both limits.
        while end < total:
            candidate = "".join(tokens[index : end + 1]).strip()
            if (
                len(candidate) >= max_chars
                or (times[end] - times[index]) >= max_seconds
            ):
                break
            end += 1

        if end < total:
            # Overflow: prefer ending on a whole word, unless that would
            # leave an unusably short cue.
            split = word_break(index, end)
            if split and len("".join(tokens[index:split]).strip()) >= MIN_SEGMENT_CHARS:
                end = split

        emit(index, end)
        index = end

    return segments


@register_adapter
class SherpaAdapter(TranscriptionAdapter):
    """Transcription through sherpa-onnx (ONNX Runtime)."""

    @property
    def prefix(self) -> str:
        return "sherpa"

    @property
    def display_name(self) -> str:
        return "sherpa-onnx (ONNX)"

    def install_hint(self) -> str:
        detail = getattr(self, "_import_error", "")
        base = "pip install sherpa-onnx"
        return f"{base}  # {detail}" if detail else base

    def is_available(self) -> bool:
        try:
            import sherpa_onnx  # noqa: F401

            return True
        except ImportError as exc:
            # Keep the cause: a missing wheel for this Python/platform looks
            # identical to a missing package otherwise.
            self._import_error = f"{exc} (Python {sys.version.split()[0]})"
            return False

    def get_model_names(self) -> List[str]:
        import sherpa_models

        return list(sherpa_models.MODEL_IDS)

    # --- recognizer construction ---

    @staticmethod
    def _provider(device: str) -> str:
        """Map whisper-subs' device flag onto an ONNX Runtime provider."""
        return "cuda" if str(device).lower().startswith("cuda") else "cpu"

    @staticmethod
    def _threads(cpu_threads: Optional[int]) -> int:
        if cpu_threads:
            return max(1, int(cpu_threads))
        return max(1, (os.cpu_count() or 2))

    def _build_recognizer(
        self,
        model_id: str,
        provider: str,
        threads: int,
        write: Callable = print,
    ) -> Tuple[Any, Any]:
        """Create the recognizer for a model, reusing a resident one.

        Returns (recognizer, sherpa_model).
        """
        import sherpa_models

        model = sherpa_models.get_model(model_id)
        if model is None:
            raise KeyError(f"Unknown sherpa-onnx model: {model_id}")

        key = (model_id, provider)
        cached = _RECOGNIZERS.get(key)
        if cached is not None:
            write(f"Reusing loaded {model.name} ({provider})")
            return cached, model

        directory = sherpa_models.ensure_model(model_id, write=write)
        model = sherpa_models.get_model(model_id)

        import sherpa_onnx

        layout = model.layout
        tokens = model.resolve("tokens")
        encoder = model.resolve("encoder")
        decoder = model.resolve("decoder")
        joiner = model.resolve("joiner")

        if model.streaming:
            recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=tokens,
                encoder=encoder,
                decoder=decoder,
                joiner=joiner,
                num_threads=threads,
                sample_rate=float(layout.get("sample_rate", SAMPLE_RATE)),
                feature_dim=int(layout.get("feature_dim", 80)),
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=0.6,
                rule2_min_trailing_silence=0.4,
                rule3_min_utterance_length=1.0,
                decoding_method="greedy_search",
                provider=provider,
                model_type=str(layout.get("model_type") or ""),
            )
            # Nemotron and friends are cache-aware: their encoder state must
            # persist across chunks, so they are decoded online.
            state = {"streaming": True}
        else:
            recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                tokens=tokens,
                encoder=encoder,
                decoder=decoder,
                joiner=joiner,
                num_threads=threads,
                sample_rate=int(layout.get("sample_rate", SAMPLE_RATE)),
                feature_dim=int(layout.get("feature_dim", 80)),
                decoding_method="greedy_search",
                provider=provider,
                model_type="nemo_transducer",
            )
            state = {"streaming": False}

        _RECOGNIZERS[key] = (recognizer, state)
        write(f"Loaded {model.name} on {provider} with {threads} thread(s)")
        return _RECOGNIZERS[key], model

    # --- decoding ---

    def _decode_offline(
        self,
        recognizer: Any,
        samples: List[float],
        sample_rate: int,
        write: Callable,
    ) -> List[Segment]:
        """Decode in overlapping windows, then group token timestamps.

        A single pass over the whole file works for short clips but aborts
        inside ONNX Runtime on anything long, so the audio is cut into
        `WINDOW_SECONDS` pieces with `OVERLAP_SECONDS` of shared context.

        A token is kept unless an earlier window already emitted audio
        reaching its start time. Dropping the whole leading overlap instead
        would silently lose any word that began just before a cut and was
        therefore never emitted by the previous window.
        """
        rate = float(sample_rate or SAMPLE_RATE)
        total = len(samples)
        duration = total / rate
        window = max(1.0, WINDOW_SECONDS)
        overlap = max(0.0, min(OVERLAP_SECONDS, window / 2 - 0.1))

        # Short clips take the single-pass path: it keeps timestamps exact and
        # avoids splitting a sentence that would fit in one window anyway.
        if duration <= window:
            tokens, times = self._decode_offline_window(
                recognizer, samples, rate, offset=0.0, emitted_until=0.0, write=write
            )
            return _group_tokens(tokens, times)

        step = window - overlap
        all_tokens: List[str] = []
        all_times: List[float] = []
        # Absolute time up to which earlier windows already transcribed audio.
        emitted_until = 0.0
        position = 0.0
        windows = 0
        while position < duration:
            start_index = int(round(position * rate))
            end_index = int(round(min(duration, position + window) * rate))
            piece = samples[start_index:end_index]
            if not piece:
                break
            windows += 1
            tokens, times = self._decode_offline_window(
                recognizer,
                piece,
                rate,
                offset=position,
                emitted_until=emitted_until,
                write=write,
            )
            all_tokens.extend(tokens)
            all_times.extend(times)
            if times:
                emitted_until = max(emitted_until, times[-1])
            if end_index >= total:
                break
            position += step

        if windows > 1:
            write(
                f"Decoded {duration:.0f}s in {windows} windows of "
                f"{window:.0f}s (+{overlap:.0f}s overlap)"
            )
        return _group_tokens(all_tokens, all_times)

    def _decode_offline_window(
        self,
        recognizer: Any,
        samples: Any,
        sample_rate: float,
        offset: float,
        emitted_until: float,
        write: Callable,
    ) -> Tuple[List[str], List[float]]:
        """Decode one window, returning tokens and absolute times.

        A token is withheld only when an earlier window already transcribed
        audio past its start, so nothing is duplicated and nothing is lost.
        """
        stream = recognizer.create_stream()
        # sherpa binds waveform as Sequence[float]; the window is a plain list
        # so the native call does not have to walk an array.
        stream.accept_waveform(int(sample_rate), list(samples))
        recognizer.decode_stream(stream)

        result = stream.result
        tokens = list(result.tokens or [])
        times = list(result.timestamps or [])

        if not tokens or len(tokens) != len(times):
            # No per-token timing: return a single whole-window pseudo-token so
            # the caller still gets the text with a usable time span.
            text = (result.text or "").strip()
            if not text:
                return [], []
            return [text], [offset]

        kept_tokens: List[str] = []
        kept_times: List[float] = []
        for token, when in zip(tokens, times):
            absolute = offset + when
            # Already covered by an earlier window's output.
            if absolute < emitted_until - _TIMESTAMP_EPSILON:
                continue
            kept_tokens.append(token)
            kept_times.append(absolute)
        return kept_tokens, kept_times

    def _decode_streaming(
        self,
        recognizer: Any,
        samples: List[float],
        sample_rate: int,
        chunk_ms: int,
        write: Callable,
    ) -> List[Segment]:
        """Decode chunk by chunk, emitting a cue at every detected endpoint."""
        stream = recognizer.create_stream()
        chunk_size = max(1, int(sample_rate * chunk_ms / 1000))
        segments: List[Segment] = []

        total = 0.0
        # Timestamps restart from zero after each reset, so keep the absolute
        # base of the current utterance and add it back on the way out.
        base = 0.0

        def drain() -> None:
            nonlocal base
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
            while recognizer.is_endpoint(stream):
                text = recognizer.get_result(stream)
                times = list(recognizer.timestamps(stream) or [])
                if text.strip():
                    start = base + (times[0] if times else 0.0)
                    end = base + (times[-1] if times else 0.0)
                    segments.append(
                        Segment(
                            start=round(max(0.0, start), 3),
                            end=round(max(start, end), 3),
                            text=text.strip(),
                        )
                    )
                recognizer.reset(stream)
                base = total

        for offset in range(0, len(samples), chunk_size):
            piece = samples[offset : offset + chunk_size]
            stream.accept_waveform(float(sample_rate), piece)
            total += len(piece) / float(sample_rate)
            drain()

        stream.input_finished()
        drain()

        tail = recognizer.get_result(stream)
        if tail.strip():
            segments.append(
                Segment(
                    start=round(max(0.0, base), 3),
                    end=round(total, 3),
                    text=tail.strip(),
                )
            )
        return segments

    # --- entry point ---

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        device: str = "cpu",
        cpu_threads: Optional[int] = None,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        import sherpa_models

        model_id = model
        descriptor = sherpa_models.get_model(model_id)
        if descriptor is None:
            raise KeyError(
                f"Unknown sherpa-onnx model '{model}'. "
                f"Available: {', '.join(sherpa_models.MODEL_IDS)}"
            )

        provider = self._provider(device)
        threads = self._threads(cpu_threads)
        (recognizer, state), _ = self._build_recognizer(
            model_id, provider, threads, write
        )

        converted = _to_wav(audio_file, write)
        temporary = converted != audio_file
        try:
            samples, sample_rate = _read_wav_mono(converted)
        finally:
            if temporary:
                try:
                    os.remove(converted)
                except OSError:
                    pass

        if not samples:
            raise RuntimeError(f"No audio samples decoded from {audio_file}")

        write(f"Transcribing {len(samples) / sample_rate:.1f}s of audio...")
        if state["streaming"]:
            segments = self._decode_streaming(
                recognizer, samples, sample_rate, descriptor.chunk_ms, write
            )
        else:
            segments = self._decode_offline(recognizer, samples, sample_rate, write)

        duration = len(samples) / float(sample_rate or SAMPLE_RATE)
        info = type(
            "Info",
            (),
            {
                "duration": duration,
                "language": language
                or (descriptor.languages[0] if descriptor.languages else ""),
                "segments_count": len(segments),
            },
        )()
        return segments, info
