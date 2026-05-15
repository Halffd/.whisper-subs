"""WhisperTurboAdapter - OpenAI Whisper Large V3 Turbo (transformers)."""
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class WhisperTurboAdapter(TranscriptionAdapter):
    """Transcription via OpenAI Whisper Large V3 Turbo (HuggingFace transformers)."""

    @property
    def prefix(self) -> str:
        return "whisperturbo"

    @property
    def display_name(self) -> str:
        return "Whisper Turbo (transformers)"

    def is_available(self) -> bool:
        try:
            from transformers import AutoModelForSpeechSeq2Seq
            return True
        except ImportError:
            return False

    def get_model_names(self) -> List[str]:
        return ["whisper-large-v3-turbo"]

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        device: str = 'cpu',
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

        hf_model_map = {
            'whisper-large-v3-turbo': 'openai/whisper-large-v3-turbo',
        }
        hf_model_id = hf_model_map.get(model, model)

        write(f"Loading Whisper Turbo: {hf_model_id}")
        torch_device = 'cuda:0' if device == 'cuda' and torch.cuda.is_available() else 'cpu'
        torch_dtype = torch.float16 if torch_device != 'cpu' else torch.float32

        hf_model = AutoModelForSpeechSeq2Seq.from_pretrained(
            hf_model_id, torch_dtype=torch_dtype, low_cpu_mem_usage=True,
        )
        hf_model.to(torch_device)

        processor = AutoProcessor.from_pretrained(hf_model_id)

        generate_kwargs = {}
        if language and language != 'none':
            generate_kwargs['language'] = language
        if temperature != 0.0:
            generate_kwargs['temperature'] = temperature

        pipe = pipeline(
            'automatic-speech-recognition',
            model=hf_model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            torch_dtype=torch_dtype,
            device=torch_device,
            return_timestamps=True,
            generate_kwargs=generate_kwargs or None,
        )

        write("Transcribing with Whisper Turbo...")
        result = pipe(audio_file)

        segments: List[Segment] = []
        if 'chunks' in result:
            for chunk in result['chunks']:
                ts = chunk.get('timestamp', (0.0, 0.0))
                segments.append(Segment(
                    start=ts[0] if ts[0] is not None else 0.0,
                    end=ts[1] if ts[1] is not None else 0.0,
                    text=chunk.get('text', ''),
                ))
        else:
            segments = [Segment(start=0.0, end=0.0, text=result.get('text', ''))]

        detected_lang = language
        info = type('Info', (), {'duration': 0.0, 'language': detected_lang})()
        return segments, info
