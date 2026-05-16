"""ParakeetAdapter - NVIDIA NeMo Parakeet ASR models."""
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class ParakeetAdapter(TranscriptionAdapter):
    """Transcription via NVIDIA NeMo Parakeet models (TDT/CTC/RNNT)."""

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
    ) -> Tuple[List[Segment], Any]:
        try:
            import nemo.collections.asr as nemo_asr
        except ImportError as e:
            raise ImportError(
                f"NeMo ASR dependencies not available: {e}. "
                f"Install with: pip install nemo-toolkit[asr] hydra-core fiddle"
            ) from e

        nemo_model_map = {
            'parakeet-tdt-0.6b-v2': 'nvidia/parakeet-tdt-0.6b-v2',
            'parakeet-tdt-0.6b-v3': 'nvidia/parakeet-tdt-0.6b-v3',
            'parakeet-ctc-1.1b': 'nvidia/parakeet-ctc-1.1b-asr',
            'parakeet-rnnt-1.1b': 'nvidia/parakeet-rnnt-1.1b-asr',
            'parakeet-ctc-0.6b': 'nvidia/parakeet-ctc-0.6b-asr',
            'parakeet-rnnt-0.6b': 'nvidia/parakeet-rnnt-0.6b-asr',
        }
        nemo_id = nemo_model_map.get(model, model)

        write(f"Loading Parakeet model: {nemo_id}")
        asr_model = nemo_asr.models.ASRModel.from_pretrained(
            model_name=nemo_id,
        )

        write("Transcribing with Parakeet...")
        output = asr_model.transcribe([audio_file], timestamps=True)

        segments: List[Segment] = []
        if output and hasattr(output, 'timestamp') and output.timestamp:
            seg_timestamps = output.timestamp.get('segment', [])
            if seg_timestamps:
                for stamp in seg_timestamps:
                    segments.append(Segment(
                        start=float(stamp.get('start', 0.0)),
                        end=float(stamp.get('end', 0.0)),
                        text=stamp.get('segment', stamp.get('word', '')).strip(),
                    ))
            else:
                word_timestamps = output.timestamp.get('word', [])
                for stamp in word_timestamps:
                    segments.append(Segment(
                        start=float(stamp.get('start', 0.0)),
                        end=float(stamp.get('end', 0.0)),
                        text=stamp.get('word', stamp.get('text', '')).strip(),
                    ))

        if not segments:
            text = ''
            if isinstance(output, list) and output:
                entry = output[0]
                text = entry.text if hasattr(entry, 'text') else str(entry)
            elif hasattr(output, 'text'):
                text = output.text
            segments = [Segment(start=0.0, end=0.0, text=text)]

        info = type('Info', (), {
            'duration': segments[-1].end if segments else 0.0,
            'language': language or 'en',
        })()
        return segments, info
