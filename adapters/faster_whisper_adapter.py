"""FasterWhisperAdapter - Local faster-whisper transcription (default backend)."""
import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class FasterWhisperAdapter(TranscriptionAdapter):
    """Default local transcription using faster-whisper (CTranslate2)."""

    @property
    def prefix(self) -> str:
        return ""

    @property
    def display_name(self) -> str:
        return "faster-whisper (local)"

    def is_available(self) -> bool:
        try:
            import faster_whisper
            return True
        except ImportError:
            return False

    def get_model_names(self) -> List[str]:
        from model import MODEL_NAMES
        return list(MODEL_NAMES)

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        device: str = 'cpu',
        compute_type: str = 'int8',
        cpu_threads: Optional[int] = None,
        vad_filter: bool = False,
        vad_params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        import faster_whisper

        if device == 'cuda':
            try:
                import torch
                if not torch.cuda.is_available():
                    device = 'cpu'
                    compute_type = 'int8'
                    write("CUDA not available, falling back to CPU")
            except ImportError:
                device = 'cpu'
                compute_type = 'int8'

        whisper_model = faster_whisper.WhisperModel(
            model,
            device=device,
            compute_type=compute_type,
            device_index=0,
            cpu_threads=cpu_threads if cpu_threads else os.cpu_count(),
        )

        is_distil = 'distil' in model.lower()
        transcribe_params: Dict[str, Any] = {
            'audio_file': audio_file,
            'language': language,
            'vad_filter': vad_filter,
        }

        if is_distil:
            transcribe_params.update({
                'condition_on_previous_text': False,
                'max_new_tokens': 128,
                'beam_size': 5,
            })
            write("Using distil-whisper optimized parameters")

        if vad_params:
            transcribe_params['vad_parameters'] = vad_params

        if temperature and temperature != 0.0:
            transcribe_params['temperature'] = temperature

        result_segments, info = whisper_model.transcribe(**transcribe_params)

        segments: List[Segment] = []
        for seg in result_segments:
            segments.append(Segment(start=seg.start, end=seg.end, text=seg.text))

        return segments, info
