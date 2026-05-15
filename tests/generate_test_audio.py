#!/usr/bin/env python3
"""Generate a short test WAV file with synthesized speech for testing adapters.

Uses ffmpeg to create a 440Hz sine tone as a minimal valid WAV file.
For real speech testing, provide your own audio file.
"""
import os
import subprocess
import sys


def generate_sine_wav(output_path: str, duration: float = 3.0, sample_rate: int = 16000) -> str:
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'anullsrc=r={sample_rate}:cl=mono',
        '-t', str(duration),
        '-acodec', 'pcm_s16le',
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: ffmpeg failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return output_path


def generate_tts_wav(output_path: str, text: str = "Hello, this is a test of the transcription system.",
                      voice: str = "en-us", speed: int = 150) -> str:
    if shutil.which('espeak-ng') or shutil.which('espeak'):
        binary = shutil.which('espeak-ng') or shutil.which('espeak')
        wav_tmp = output_path + '.raw.wav'
        cmd = [binary, '-v', voice, '-s', str(speed), '-w', wav_tmp, text]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            cmd = [
                'ffmpeg', '-y', '-i', wav_tmp,
                '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000',
                output_path,
            ]
            subprocess.run(cmd, capture_output=True, text=True)
            try:
                os.remove(wav_tmp)
            except OSError:
                pass
            if os.path.exists(output_path):
                return output_path
    return generate_sine_wav(output_path)


import shutil

if __name__ == '__main__':
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'tests', 'fixtures')
    os.makedirs(out_dir, exist_ok=True)

    sine_path = os.path.join(out_dir, 'test_sine.wav')
    generate_sine_wav(sine_path)
    print(f"Generated: {sine_path}")

    speech_path = os.path.join(out_dir, 'test_speech.wav')
    generate_tts_wav(speech_path)
    print(f"Generated: {speech_path}")

    print("\nFor better test results, provide your own audio file with real speech.")
    print("Usage: python tests/generate_test_audio.py [output_path]")
