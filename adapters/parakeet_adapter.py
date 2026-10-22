"""ParakeetAdapter - NVIDIA NeMo Parakeet ASR models.

NeMo transcribes a whole file in one call, so nothing would be visible
until the very end. This adapter cuts the audio into overlapping chunks
and transcribes them one after another, yielding the segments of each
chunk as soon as it is done. The pipeline writes them into the
in-progress subtitle file, so a running transcription shows progress
and the growing (unfinished) subtitles.
"""

import os
import shutil
import subprocess
import tempfile
import wave
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class ParakeetAdapter(TranscriptionAdapter):
    """Transcription via NVIDIA NeMo Parakeet models (TDT/CTC/RNNT)."""

    #: Audio chunk length in seconds. Smaller chunks mean earlier
    #: progress, more boundary cuts.
    CHUNK_SECONDS = 30.0
    #: Overlap between two chunks in seconds. Covers words that straddle
    #: a chunk boundary.
    OVERLAP_SECONDS = 2.0
    #: Sample rate NeMo expects.
    SAMPLE_RATE = 16000

    @property
    def prefix(self) -> str:
        return "parakeet"

    @property
    def display_name(self) -> str:
        return "NVIDIA Parakeet (NeMo)"

    def is_available(self) -> bool:
        try:
            import nemo
            import hydra
            import fiddle

            return True
        except ImportError:
            return False

    def get_model_names(self) -> List[str]:
        return [
            "parakeet-tdt-0.6b-v2",
            "parakeet-tdt-0.6b-v3",
            "parakeet-ctc-1.1b",
            "parakeet-rnnt-1.1b",
            "parakeet-ctc-0.6b",
            "parakeet-rnnt-0.6b",
        ]

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        **kwargs,
    ) -> Tuple[Iterator[Segment], Any]:
        try:
            import nemo.collections.asr as nemo_asr
        except ImportError as e:
            raise ImportError(
                f"NeMo ASR dependencies not available: {e}. "
                f"Install with: pip install nemo-toolkit[asr] hydra-core fiddle"
            ) from e

        nemo_model_map = {
            "parakeet-tdt-0.6b-v2": "nvidia/parakeet-tdt-0.6b-v2",
            "parakeet-tdt-0.6b-v3": "nvidia/parakeet-tdt-0.6b-v3",
            "parakeet-ctc-1.1b": "nvidia/parakeet-ctc-1.1b",
            "parakeet-rnnt-1.1b": "nvidia/parakeet-rnnt-1.1b",
            "parakeet-ctc-0.6b": "nvidia/parakeet-ctc-0.6b",
            "parakeet-rnnt-0.6b": "nvidia/parakeet-rnnt-0.6b",
        }
        nemo_id = nemo_model_map.get(model, model)

        write(f"Loading Parakeet model: {nemo_id}")
        try:
            asr_model = nemo_asr.models.ASRModel.from_pretrained(
                model_name=nemo_id,
            )
        except Exception as e:
            err_msg = str(e)
            if (
                "401" in err_msg
                or "Unauthorized" in err_msg
                or "Repository Not Found" in err_msg
            ):
                raise RuntimeError(
                    f"Cannot access '{nemo_id}' on HuggingFace (gated model). "
                    f"You need to:\n"
                    f"  1. Request access at https://huggingface.co/{nemo_id}\n"
                    f"  2. Set your HF token: huggingface-cli login\n"
                    f"     or: export HF_TOKEN=your_token\n"
                    f"Original error: {e}"
                ) from e
            raise

        # The chunks are prepared before the first segment is yielded, so
        # the caller gets an iterator that produces segments while the
        # model is still working.
        workdir = tempfile.mkdtemp(prefix="parakeet-")
        try:
            wav_path = self._to_wav(audio_file, workdir, write)
            duration = self._duration(wav_path)
            chunks = self._chunk_wav(wav_path, workdir)
            write(
                f"Transcribing {len(chunks)} chunk(s) "
                f"({self.CHUNK_SECONDS:.0f}s each) with Parakeet..."
            )
            segments = self._stream_chunks(asr_model, chunks, write)
        except Exception:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

        info = type(
            "Info",
            (),
            {
                "duration": duration,
                "language": language or "en",
            },
        )()

        def _closing_iterator() -> Iterator[Segment]:
            try:
                for segment in segments:
                    yield segment
            finally:
                shutil.rmtree(workdir, ignore_errors=True)

        return _closing_iterator(), info

    # ---------- audio preparation ----------

    def _to_wav(self, audio_file: str, workdir: str, write: Callable) -> str:
        """16 kHz mono PCM wav of the source audio."""
        if audio_file.lower().endswith(".wav"):
            try:
                with wave.open(audio_file, "rb") as probe:
                    if (
                        probe.getframerate() == self.SAMPLE_RATE
                        and probe.getnchannels() == 1
                        and probe.getsampwidth() == 2
                    ):
                        return audio_file
            except (wave.Error, OSError):
                pass

        wav_path = os.path.join(workdir, "source.wav")
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            audio_file,
            "-ar",
            str(self.SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            wav_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except FileNotFoundError:
            raise RuntimeError("ffmpeg is required to prepare audio for Parakeet")
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"ffmpeg failed to convert audio: {detail}")
        return wav_path

    def _duration(self, wav_path: str) -> float:
        try:
            with wave.open(wav_path, "rb") as handle:
                return handle.getnframes() / float(handle.getframerate())
        except (wave.Error, OSError):
            return 0.0

    def _chunk_wav(self, wav_path: str, workdir: str) -> List[Tuple[str, float]]:
        """Split the wav into overlapping chunks.

        Returns (chunk path, offset in seconds) pairs. The chunks overlap
        so a word cut at a boundary is still heard whole by the next
        chunk.
        """
        chunks: List[Tuple[str, float]] = []
        with wave.open(wav_path, "rb") as source:
            rate = source.getframerate()
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            total_frames = source.getnframes()

            chunk_frames = int(self.CHUNK_SECONDS * rate)
            overlap_frames = int(self.OVERLAP_SECONDS * rate)
            step = max(1, chunk_frames - overlap_frames)

            index = 0
            position = 0
            while position < total_frames:
                frames = min(chunk_frames, total_frames - position)
                source.setpos(position)
                frames_data = source.readframes(frames)
                chunk_path = os.path.join(workdir, f"chunk-{index:04d}.wav")
                with wave.open(chunk_path, "wb") as out:
                    out.setnchannels(channels)
                    out.setsampwidth(sample_width)
                    out.setframerate(rate)
                    out.writeframes(frames_data)
                chunks.append((chunk_path, position / float(rate)))
                index += 1
                if frames < chunk_frames:
                    break
                position += step
        return chunks

    # ---------- transcription ----------

    def _stream_chunks(
        self,
        asr_model,
        chunks: List[Tuple[str, float]],
        write: Callable,
    ) -> Iterator[Segment]:
        """Transcribe chunk by chunk, yielding segments as they arrive."""
        covered_until = 0.0
        for chunk_index, (chunk_path, offset) in enumerate(chunks):
            output = asr_model.transcribe([chunk_path], timestamps=True)
            for segment in self._segments_of(output, offset):
                # A segment that starts before the already emitted audio
                # was transcribed by the previous chunk (the overlap
                # region) - skip it, except for the first segment of a
                # chunk, which carries the word that was cut at the
                # boundary.
                if chunk_index > 0 and segment.start < covered_until - 0.05:
                    continue
                covered_until = max(covered_until, segment.end)
                yield segment

    def _segments_of(self, output: Any, offset: float) -> List[Segment]:
        """Turn one NeMo result into segments with absolute timestamps."""
        segments: List[Segment] = []
        if output and isinstance(output, list) and len(output) > 0:
            result = output[0]
            ts = None
            if hasattr(result, "timestamp") and result.timestamp:
                ts = result.timestamp
            elif isinstance(result, dict) and "timestamp" in result:
                ts = result["timestamp"]

            if ts:
                seg_timestamps = ts.get("segment", []) if isinstance(ts, dict) else []
                if seg_timestamps:
                    for stamp in seg_timestamps:
                        if isinstance(stamp, dict):
                            segments.append(
                                Segment(
                                    start=offset + float(stamp.get("start", 0.0)),
                                    end=offset + float(stamp.get("end", 0.0)),
                                    text=stamp.get(
                                        "segment", stamp.get("word", "")
                                    ).strip(),
                                )
                            )
                        else:
                            segments.append(
                                Segment(
                                    start=offset + float(getattr(stamp, "start", 0.0)),
                                    end=offset + float(getattr(stamp, "end", 0.0)),
                                    text=getattr(
                                        stamp, "segment", getattr(stamp, "word", "")
                                    ).strip(),
                                )
                            )
                if not segments:
                    word_timestamps = ts.get("word", []) if isinstance(ts, dict) else []
                    for stamp in word_timestamps:
                        if isinstance(stamp, dict):
                            segments.append(
                                Segment(
                                    start=offset + float(stamp.get("start", 0.0)),
                                    end=offset + float(stamp.get("end", 0.0)),
                                    text=stamp.get(
                                        "word", stamp.get("text", "")
                                    ).strip(),
                                )
                            )
                        else:
                            segments.append(
                                Segment(
                                    start=offset + float(getattr(stamp, "start", 0.0)),
                                    end=offset + float(getattr(stamp, "end", 0.0)),
                                    text=getattr(
                                        stamp, "word", getattr(stamp, "text", "")
                                    ).strip(),
                                )
                            )

        if not segments:
            text = ""
            if output and isinstance(output, list) and len(output) > 0:
                result = output[0]
                text = result.text if hasattr(result, "text") else str(result)
            elif hasattr(output, "text"):
                text = output.text
            if text:
                segments.append(Segment(start=offset, end=offset, text=text))
        return segments
