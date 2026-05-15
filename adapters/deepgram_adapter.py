"""DeepgramAdapter - Deepgram Speech-to-Text API transcription."""
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class DeepgramAdapter(TranscriptionAdapter):
    """Transcription via Deepgram's Speech-to-Text API."""

    @property
    def prefix(self) -> str:
        return "deepgram"

    @property
    def display_name(self) -> str:
        return "Deepgram API"

    def is_available(self) -> bool:
        try:
            import deepgram_sdk
            return bool(os.environ.get('DEEPGRAM_API_KEY'))
        except ImportError:
            return bool(os.environ.get('DEEPGRAM_API_KEY'))

    def get_model_names(self) -> List[str]:
        return ["nova-3", "nova-2", "whisper-turbo", "nova-2-phonecall", "enhanced"]

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        api_key = os.environ.get('DEEPGRAM_API_KEY')
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY environment variable is required")

        import requests

        url = "https://api.deepgram.com/v1/listen"
        params: Dict[str, Any] = {
            'model': model,
            'smart_format': True,
            'utterances': True,
            'punctuate': True,
        }
        if language and language != 'none':
            params['language'] = language

        headers = {
            'Authorization': f'Token {api_key}',
            'Content-Type': 'audio/wav',
        }

        converted_audio = audio_file
        if not audio_file.lower().endswith('.wav'):
            converted_audio = self._convert_to_wav(audio_file, write)

        try:
            with open(converted_audio, 'rb') as f:
                audio_data = f.read()

            write(f"Transcribing with Deepgram API using model: {model}")
            response = requests.post(
                url, params=params, headers=headers, data=audio_data, timeout=300,
            )

            if response.status_code != 200:
                raise Exception(f"Deepgram API error: {response.status_code} - {response.text}")

            result = response.json()
            segments: List[Segment] = []
            detected_lang = language

            results = result.get('results', {})
            channels = results.get('channels', [])
            if channels:
                channel = channels[0]
                alternatives = channel.get('alternatives', [])
                if alternatives:
                    alt = alternatives[0]
                    for word in alt.get('words', []):
                        pass
                    utterances = results.get('utterances', [])
                    if utterances:
                        for utt in utterances:
                            segments.append(Segment(
                                start=utt.get('start', 0.0),
                                end=utt.get('end', 0.0),
                                text=utt.get('transcript', ''),
                            ))
                    else:
                        para_segments = alt.get('paragraphs', {}).get('paragraphs', [])
                        if para_segments:
                            for para in para_segments:
                                for sent in para.get('sentences', []):
                                    segments.append(Segment(
                                        start=sent.get('start', 0.0),
                                        end=sent.get('end', 0.0),
                                        text=sent.get('text', ''),
                                    ))
                        else:
                            text = alt.get('transcript', '')
                            segments = [Segment(start=0.0, end=0.0, text=text)]

                    detected_lang = channels[0].get('detected_language', language)

            if not segments:
                text = results.get('channels', [{}])[0].get('alternatives', [{}])[0].get('transcript', '')
                segments = [Segment(start=0.0, end=0.0, text=text)]

            info = type('Info', (), {
                'duration': results.get('duration', 0.0),
                'language': detected_lang,
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
        write("Converting audio to WAV format for Deepgram API...")
        cmd = [
            'ffmpeg', '-y', '-i', audio_file,
            '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000',
            converted,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Audio conversion failed: {result.stderr}")
        return converted
