"""ChirpAdapter - Google Cloud Speech-to-Text (Chirp/Chirp 2) transcription."""
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class ChirpAdapter(TranscriptionAdapter):
    """Transcription via Google Cloud Speech-to-Text API (Chirp models)."""

    @property
    def prefix(self) -> str:
        return "chirp"

    @property
    def display_name(self) -> str:
        return "Google Chirp (Cloud STT)"

    def is_available(self) -> bool:
        try:
            from google.cloud import speech
            return True
        except ImportError:
            return bool(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'))

    def get_model_names(self) -> List[str]:
        return ["chirp_2", "chirp", "long", "latest_short", "latest_long"]

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        from google.cloud import speech

        client = speech.SpeechClient()

        converted_audio = audio_file
        if not audio_file.lower().endswith(('.wav', '.mp3', '.flac')):
            converted_audio = self._convert_to_wav(audio_file, write)

        try:
            with open(converted_audio, 'rb') as f:
                audio_content = f.read()

            audio = speech.RecognitionAudio(content=audio_content)

            lang_code = language or 'en-US'
            if len(lang_code) == 2:
                lang_map = {'en': 'en-US', 'ja': 'ja-JP', 'es': 'es-ES',
                            'fr': 'fr-FR', 'de': 'de-DE', 'pt': 'pt-BR',
                            'zh': 'zh-CN', 'ko': 'ko-KR', 'it': 'it-IT'}
                lang_code = lang_map.get(lang_code, f'{lang_code}-US')

            config = speech.RecognitionConfig(
                model=model,
                language_code=lang_code,
                enable_word_time_offsets=True,
                enable_automatic_punctuation=True,
            )

            write(f"Transcribing with Google Chirp ({model})...")
            response = client.recognize(config=config, audio=audio)

            segments: List[Segment] = []
            for result in response.results:
                alternative = result.alternatives[0]
                words = alternative.words

                if words:
                    for i, word_info in enumerate(words):
                        start = word_info.start_time.total_seconds()
                        end = word_info.end_time.total_seconds()
                        segments.append(Segment(
                            start=start,
                            end=end,
                            text=word_info.word,
                        ))
                else:
                    segments.append(Segment(
                        start=0.0,
                        end=0.0,
                        text=alternative.transcript,
                    ))

            if not segments:
                segments = [Segment(start=0.0, end=0.0, text='')]

            detected_lang = lang_code
            info = type('Info', (), {
                'duration': segments[-1].end if segments else 0.0,
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
        converted = audio_file + '.chirp.wav'
        write("Converting audio to WAV for Google Chirp...")
        cmd = [
            'ffmpeg', '-y', '-i', audio_file,
            '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000',
            converted,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Audio conversion failed: {result.stderr}")
        return converted
