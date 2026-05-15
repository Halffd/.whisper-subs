"""WhisperXAdapter - WhisperX with forced alignment and diarization."""
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class WhisperXAdapter(TranscriptionAdapter):
    """Transcription via WhisperX (faster-whisper + alignment + diarization)."""

    @property
    def prefix(self) -> str:
        return "whisperx"

    @property
    def display_name(self) -> str:
        return "WhisperX"

    def is_available(self) -> bool:
        try:
            import whisperx
            return True
        except ImportError:
            return False

    def get_model_names(self) -> List[str]:
        return ["large-v3", "large-v2", "medium", "small", "base", "tiny",
                "medium.en", "small.en", "base.en", "tiny.en"]

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        device: str = 'cpu',
        compute_type: str = 'int8',
        diarize: bool = False,
        hf_token: Optional[str] = None,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        import whisperx
        import torch

        _device = 'cuda' if torch.cuda.is_available() else 'cpu'
        if device == 'cuda' and not torch.cuda.is_available():
            _device = 'cpu'

        write(f"Loading WhisperX model: {model}")
        whisper_model = whisperx.load_model(
            model,
            _device,
            compute_type=compute_type,
            language=language,
        )

        write("Loading audio...")
        audio = whisperx.load_audio(audio_file)

        write("Transcribing...")
        result = whisper_model.transcribe(audio, batch_size=16, language=language)

        if language and language != 'none' and result.get('language') != language:
            write(f"Aligning with language: {result.get('language')}")
            align_model, metadata = whisperx.load_align_model(
                language_code=result['language'], device=_device,
            )
            result = whisperx.align(
                result['segments'], align_model, metadata, audio, _device,
            )

        if diarize:
            _hf_token = hf_token or os.environ.get('HF_TOKEN')
            if _hf_token:
                write("Running diarization...")
                diarize_model = whisperx.DiarizationPipeline(
                    use_auth_token=_hf_token, device=_device,
                )
                diarize_segments = diarize_model(audio)
                result = whisperx.assign_word_speakers(diarize_segments, result)
            else:
                write("HF_TOKEN not set, skipping diarization")

        segments: List[Segment] = []
        for seg in result.get('segments', []):
            text = seg.get('text', '')
            speaker = seg.get('speaker', '')
            if speaker:
                text = f"[{speaker}] {text}"
            segments.append(Segment(
                start=seg.get('start', 0.0),
                end=seg.get('end', 0.0),
                text=text,
            ))

        info = type('Info', (), {
            'duration': result.get('segments', [{}])[-1].get('end', 0.0) if segments else 0.0,
            'language': result.get('language', language),
        })()
        return segments, info
