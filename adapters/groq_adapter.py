"""GroqAdapter - Groq Cloud Whisper API transcription."""
import os
from typing import Any, Callable, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class GroqAdapter(TranscriptionAdapter):
    """Transcription via Groq's hosted Whisper API."""

    @property
    def prefix(self) -> str:
        return "groq"

    @property
    def display_name(self) -> str:
        return "Groq API"

    def is_available(self) -> bool:
        return bool(os.environ.get('GROQ_API_KEY'))

    def get_model_names(self) -> List[str]:
        return [
            "whisper-large-v3",
            "whisper-large-v3-turbo",
            "distil-whisper-large-v3-en",
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

        api_key = os.environ.get('GROQ_API_KEY')
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable is required")

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}

        converted_audio = audio_file
        if not audio_file.lower().endswith(('.wav', '.mp3', '.m4a')):
            converted_audio = self._convert_to_wav(audio_file, write)

        try:
            with open(converted_audio, 'rb') as f:
                files = {'file': (os.path.basename(converted_audio), f)}
                data: Dict[str, Any] = {'model': model, 'response_format': 'verbose_json'}
                if language and language != 'none':
                    data['language'] = language
                if temperature != 0.0:
                    data['temperature'] = temperature

            write(f"Transcribing with Groq API using model: {model}")
            with open(converted_audio, 'rb') as f:
                files = {'file': (os.path.basename(converted_audio), f)}
                response = requests.post(
                    url, headers=headers, files=files, data=data, timeout=300,
                )

            if response.status_code != 200:
                raise Exception(f"Groq API error: {response.status_code} - {response.text}")

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

        finally:
            if converted_audio != audio_file and os.path.exists(converted_audio):
                try:
                    os.remove(converted_audio)
                except OSError:
                    pass

    @staticmethod
    def _convert_to_wav(audio_file: str, write: Callable = print) -> str:
        import subprocess
        converted = audio_file + '.converted.wav'
        write("Converting audio to WAV format for Groq API...")
        cmd = [
            'ffmpeg', '-y', '-i', audio_file,
            '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000',
            converted,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Audio conversion failed: {result.stderr}")
        return converted
