"""CanaryAdapter - NVIDIA NeMo Canary multilingual ASR."""
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class CanaryAdapter(TranscriptionAdapter):
    """Transcription via NVIDIA NeMo Canary models (multilingual, with punctuation)."""

    @property
    def prefix(self) -> str:
        return "canary"

    @property
    def display_name(self) -> str:
        return "NVIDIA Canary (NeMo)"

    def is_available(self) -> bool:
        try:
            import nemo.collections.asr as nemo_asr
            return True
        except ImportError:
            return False

    def get_model_names(self) -> List[str]:
        return ["canary-1b-flash", "canary-1b"]

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
            'canary-1b-flash': 'nvidia/canary-1b-flash',
            'canary-1b': 'nvidia/canary-1b',
        }
        nemo_id = nemo_model_map.get(model, model)

        write(f"Loading Canary model: {nemo_id}")
        asr_model = nemo_asr.models.EncDecMultiTaskModel.from_pretrained(
            model_name=nemo_id,
        )

        src_lang = language or 'en'
        tgt_lang = src_lang
        pnc = 'pnc' if 'flash' in model else 'no_pnc'

        write(f"Transcribing with Canary (src={src_lang}, tgt={tgt_lang})...")
        output = asr_model.transcribe(
            [audio_file],
            source_lang=src_lang,
            target_lang=tgt_lang,
            pnc=pnc,
        )

        segments: List[Segment] = []
        if output:
            for entry in output:
                if isinstance(entry, str):
                    segments.append(Segment(start=0.0, end=0.0, text=entry))
                elif hasattr(entry, 'text'):
                    segments.append(Segment(start=0.0, end=0.0, text=entry.text))
                elif isinstance(entry, (list, tuple)):
                    for seg in entry:
                        text = seg if isinstance(seg, str) else str(seg)
                        segments.append(Segment(start=0.0, end=0.0, text=text))

        if not segments:
            segments = [Segment(start=0.0, end=0.0, text='')]

        info = type('Info', (), {
            'duration': 0.0,
            'language': language or 'en',
        })()
        return segments, info
