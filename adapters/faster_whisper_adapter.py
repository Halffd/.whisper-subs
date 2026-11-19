"""FasterWhisperAdapter - Local faster-whisper transcription (default backend)."""

import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter

# MODEL_NAMES carries HuggingFace repo ids ("distil-whisper/distil-medium.en",
# "jlondonobo/whisper-medium-pt") while faster-whisper only accepts the short
# distil names ("distil-medium.en"). An HF repo id it does not know raises
# "No such file or directory", so it must be translated before the model is
# handed over; anything with no entry here is passed through untouched.
_FW_MODEL_ALIASES = {
    "distil-whisper/distil-large-v3": "distil-large-v3",
    "distil-whisper/distil-large-v2": "distil-large-v2",
    "distil-whisper/distil-large": "distil-large",
    "distil-whisper/distil-medium": "distil-medium",
    "distil-whisper/distil-medium.en": "distil-medium.en",
    "distil-whisper/distil-small": "distil-small",
    "distil-whisper/distil-small.en": "distil-small.en",
    "distil-whisper/distil-base": "distil-base",
}


def _resolve_fw_model(model: str) -> str:
    """Translate a MODEL_NAMES entry to what faster-whisper accepts."""
    return _FW_MODEL_ALIASES.get(model, model)


@register_adapter
class FasterWhisperAdapter(TranscriptionAdapter):
    """Default local transcription using faster-whisper (CTranslate2)."""

    @property
    def prefix(self) -> str:
        return ""

    @property
    def display_name(self) -> str:
        return "faster-whisper (local)"

    def install_hint(self) -> str:
        return "pip install faster-whisper"

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
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: Optional[int] = None,
        vad_filter: bool = False,
        vad_params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        import faster_whisper

        # Model names in MODEL_NAMES may be HF repo ids; translate before
        # handing over.
        resolved_model = _resolve_fw_model(model)
        if resolved_model != model:
            write(f"Using faster-whisper model: {resolved_model}")

        if device == "cuda":
            try:
                import torch

                if not torch.cuda.is_available():
                    device = "cpu"
                    compute_type = "int8"
                    write("CUDA not available, falling back to CPU")
            except ImportError:
                device = "cpu"
                compute_type = "int8"

        whisper_model = faster_whisper.WhisperModel(
            resolved_model,
            device=device,
            compute_type=compute_type,
            device_index=0,
            cpu_threads=cpu_threads if cpu_threads else os.cpu_count(),
        )

        is_distil = "distil" in resolved_model.lower()
        # faster-whisper names the first parameter `audio`; passing
        # `audio_file=` raises TypeError. Bare models never reach this code
        # through the normal CLI (transcribe.py has its own local path), which
        # is why the wrong name went unnoticed.
        transcribe_params: Dict[str, Any] = {
            "audio": audio_file,
            "language": language,
            "vad_filter": vad_filter,
        }

        if is_distil:
            transcribe_params.update(
                {
                    "condition_on_previous_text": False,
                    "max_new_tokens": 128,
                    "beam_size": 5,
                }
            )
            write("Using distil-whisper optimized parameters")

        if vad_params:
            transcribe_params["vad_parameters"] = vad_params

        if temperature and temperature != 0.0:
            transcribe_params["temperature"] = temperature

        result_segments, info = whisper_model.transcribe(**transcribe_params)

        segments: List[Segment] = []
        for seg in result_segments:
            segments.append(Segment(start=seg.start, end=seg.end, text=seg.text))

        return segments, info
