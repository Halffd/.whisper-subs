"""HuggingFaceAdapter - HuggingFace Inference API transcription."""
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class HuggingFaceAdapter(TranscriptionAdapter):
    """Transcription via HuggingFace Inference API."""

    @property
    def prefix(self) -> str:
        return "hf"

    @property
    def display_name(self) -> str:
        return "HuggingFace API"

    def is_available(self) -> bool:
        return bool(os.environ.get('HF_API_KEY'))

    def get_model_names(self) -> List[str]:
        return [
            "openai/whisper-large-v3",
            "openai/whisper-large-v3-turbo",
            "nvidia/parakeet-ctc-1.1b-asr",
            "nvidia/canary-1b-flash",
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
        import requests

        api_key = os.environ.get('HF_API_KEY')
        if not api_key:
            raise ValueError("HF_API_KEY environment variable is required")

        url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {"Authorization": f"Bearer {api_key}"}

        with open(audio_file, 'rb') as f:
            audio_data = f.read()

        write(f"Transcribing with HuggingFace API using model: {model}")
        response = requests.post(url, headers=headers, data=audio_data, timeout=300)

        if response.status_code != 200:
            ct = response.headers.get('content-type', '')
            if ct.startswith('application/json'):
                error_msg = response.json().get('error', response.text)
            else:
                error_msg = response.text
            raise Exception(f"HuggingFace API error: {response.status_code} - {error_msg}")

        result = response.json()
        segments: List[Segment] = []

        if 'segments' in result and isinstance(result['segments'], list):
            for seg_data in result['segments']:
                segments.append(Segment(
                    start=seg_data.get('start', 0.0),
                    end=seg_data.get('end', 0.0),
                    text=seg_data.get('text', ''),
                ))
        else:
            text = result.get('text', '')
            segments = [Segment(start=0.0, end=0.0, text=text)]

        info = type('Info', (), {
            'duration': 0.0,
            'language': result.get('language', language),
        })()
        return segments, info
