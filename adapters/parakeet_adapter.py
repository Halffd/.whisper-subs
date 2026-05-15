"""ParakeetAdapter - NVIDIA NeMo Parakeet ASR models."""
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class ParakeetAdapter(TranscriptionAdapter):
    """Transcription via NVIDIA NeMo Parakeet models (CTC/RNNT)."""

    @property
    def prefix(self) -> str:
        return "parakeet"

    @property
    def display_name(self) -> str:
        return "NVIDIA Parakeet (NeMo)"

    def is_available(self) -> bool:
        try:
            import nemo
            return True
        except ImportError:
            return False

    def get_model_names(self) -> List[str]:
        return [
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
        import nemo.collections.asr as nemo_asr

        nemo_model_map = {
            'parakeet-ctc-1.1b': 'nvidia/parakeet-ctc-1.1b-asr',
            'parakeet-rnnt-1.1b': 'nvidia/parakeet-rnnt-1.1b-asr',
            'parakeet-ctc-0.6b': 'nvidia/parakeet-ctc-0.6b-asr',
            'parakeet-rnnt-0.6b': 'nvidia/parakeet-rnnt-0.6b-asr',
        }
        nemo_id = nemo_model_map.get(model, model)

        write(f"Loading Parakeet model: {nemo_id}")
        asr_model = nemo_asr.models.EncDecHybridRNNTCTCBPEModel.from_pretrained(
            model_name=nemo_id,
        )

        write("Transcribing with Parakeet...")
        results = asr_model.transcribe([audio_file], return_hypotheses=True)

        segments: List[Segment] = []
        for hyp in results:
            if hasattr(hyp, 'timestamp') and hyp.timestamp:
                for ts in hyp.timestamp:
                    segments.append(Segment(
                        start=ts.get('start', 0.0),
                        end=ts.get('end', 0.0),
                        text=ts.get('word', ''),
                    ))
            else:
                text = hyp.text if hasattr(hyp, 'text') else str(hyp)
                segments.append(Segment(start=0.0, end=0.0, text=text))

        info = type('Info', (), {
            'duration': segments[-1].end if segments else 0.0,
            'language': 'en',
        })()
        return segments, info
