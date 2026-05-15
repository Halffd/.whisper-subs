"""WhisperCppAdapter - whisper.cpp subprocess-based transcription."""
import os
import subprocess
import shutil
import tempfile
from typing import Any, Callable, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class WhisperCppAdapter(TranscriptionAdapter):
    """Transcription via whisper.cpp CLI (whisper-cpp or main binary)."""

    @property
    def prefix(self) -> str:
        return "whispercpp"

    @property
    def display_name(self) -> str:
        return "whisper.cpp"

    def is_available(self) -> bool:
        return shutil.which('whisper-cpp') is not None or shutil.which('main') is not None

    def get_model_names(self) -> List[str]:
        return ["base", "small", "medium", "large-v3", "tiny", "large-v2"]

    def _find_binary(self) -> str:
        for name in ('whisper-cpp', 'main', 'whisper'):
            path = shutil.which(name)
            if path:
                return path
        raise FileNotFoundError("whisper.cpp binary not found in PATH")

    def _find_model_file(self, model: str) -> str:
        model_name_map = {
            'tiny': 'ggml-tiny.bin',
            'base': 'ggml-base.bin',
            'small': 'ggml-small.bin',
            'medium': 'ggml-medium.bin',
            'large-v2': 'ggml-large-v2.bin',
            'large-v3': 'ggml-large-v3.bin',
        }
        ggml_name = model_name_map.get(model, f'ggml-{model}.bin')

        search_paths = [
            os.path.expanduser(f'~/.cache/whisper/{ggml_name}'),
            os.path.expanduser(f'~/models/{ggml_name}'),
            f'/usr/share/whisper-cpp/{ggml_name}',
            f'/opt/whisper-cpp/{ggml_name}',
            os.path.join(os.path.dirname(__file__), '..', 'models', ggml_name),
        ]
        for path in search_paths:
            if os.path.exists(path):
                return path

        return ggml_name

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        binary = self._find_binary()
        model_file = self._find_model_file(model)

        converted_audio = audio_file
        needs_conversion = not audio_file.lower().endswith('.wav')
        if needs_conversion:
            converted_audio = self._convert_to_wav(audio_file, write)

        try:
            cmd = [
                binary,
                '-m', model_file,
                '-f', converted_audio,
                '--output-srt',
                '-nt',
            ]
            if language and language != 'none':
                cmd.extend(['-l', language])
            if temperature != 0.0:
                cmd.extend(['--temp', str(temperature)])

            write(f"Running whisper.cpp: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

            if result.returncode != 0:
                raise Exception(f"whisper.cpp error: {result.stderr}")

            segments = self._parse_srt_output(result.stdout)
            info = type('Info', (), {
                'duration': segments[-1].end if segments else 0.0,
                'language': language,
            })()
            return segments, info

        finally:
            if needs_conversion and os.path.exists(converted_audio):
                try:
                    os.remove(converted_audio)
                except OSError:
                    pass

    @staticmethod
    def _convert_to_wav(audio_file: str, write: Callable = print) -> str:
        converted = audio_file + '.whispercpp.wav'
        write("Converting audio to WAV for whisper.cpp...")
        cmd = [
            'ffmpeg', '-y', '-i', audio_file,
            '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000',
            converted,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"Audio conversion failed: {result.stderr}")
        return converted

    @staticmethod
    def _parse_srt_output(srt_text: str) -> List['Segment']:
        import re
        from model import Segment
        segments: List[Segment] = []
        blocks = srt_text.strip().split('\n\n')
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) >= 3:
                try:
                    int(lines[0])
                    time_match = re.match(
                        r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})',
                        lines[1],
                    )
                    if time_match:
                        start = WhisperCppAdapter._srt_to_seconds(time_match.group(1))
                        end = WhisperCppAdapter._srt_to_seconds(time_match.group(2))
                        text = '\n'.join(lines[2:]).strip()
                        segments.append(Segment(start=start, end=end, text=text))
                except (ValueError, IndexError):
                    continue
        return segments

    @staticmethod
    def _srt_to_seconds(time_str: str) -> float:
        import re
        parts = re.split('[:,]', time_str)
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) + int(parts[3]) / 1000.0
