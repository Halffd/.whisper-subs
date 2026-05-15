#!/usr/bin/env python3
"""Test transcription with a specific adapter backend.

Usage:
    # Test with a specific model (auto-detects local vs. adapter)
    python tests/test_transcribe.py <audio_file> <model_name>

    # Examples:
    python tests/test_transcribe.py audio.wav large-v3
    python tests/test_transcribe.py audio.wav groq:whisper-large-v3
    python tests/test_transcribe.py audio.wav deepgram:nova-2
    python tests/test_transcribe.py audio.wav whispercpp:base
    python tests/test_transcribe.py audio.wav moonshine:moonshine-tiny
    python tests/test_transcribe.py audio.wav hf:openai/whisper-large-v3
    python tests/test_transcribe.py audio.wav whisperturbo:whisper-large-v3-turbo
    python tests/test_transcribe.py audio.wav voxtral:voxtral-mini
    python tests/test_transcribe.py audio.wav whisperx:large-v3
    python tests/test_transcribe.py audio.wav canary:canary-1b-flash
    python tests/test_transcribe.py audio.wav parakeet:parakeet-ctc-1.1b
    python tests/test_transcribe.py audio.wav chirp:chirp_2
    python tests/test_transcribe.py audio.wav vibevoice:vibevoice-1b
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def log(msg: str):
    print(f"  {msg}")


def test_transcribe(audio_file: str, model_name: str, language: str = None):
    from model import TranscriptionContext, Segment

    if not os.path.exists(audio_file):
        print(f"ERROR: Audio file not found: {audio_file}")
        return 1

    ctx = TranscriptionContext()

    log(f"Resolving model: {model_name}")
    try:
        adapter, resolved_model = ctx.resolve(model_name)
        log(f"  Adapter: {adapter.display_name}")
        log(f"  Model:   {resolved_model}")
        log(f"  Prefix:  {adapter.prefix or '(local)'}")
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    is_api, prefix, _ = ctx.is_api_model(model_name)
    log(f"  API/Remote: {is_api}")

    log(f"\nTranscribing: {audio_file}")
    log(f"  File size: {os.path.getsize(audio_file):,} bytes")

    start_time = time.time()
    try:
        segments, info = ctx.transcribe(
            audio_file=audio_file,
            model_name=model_name,
            language=language,
            write=log,
        )
        elapsed = time.time() - start_time
    except Exception as e:
        print(f"\nERROR during transcription: {e}")
        import traceback
        traceback.print_exc()
        return 1

    log(f"\n{'=' * 50}")
    log(f"RESULTS ({elapsed:.1f}s)")
    log(f"{'=' * 50}")
    log(f"Segments: {len(segments)}")
    if hasattr(info, 'language') and info.language:
        log(f"Language: {info.language}")
    if hasattr(info, 'duration') and info.duration:
        log(f"Duration: {info.duration:.1f}s")

    log(f"\n--- Transcript ---")
    for i, seg in enumerate(segments, 1):
        start_ts = f"[{seg.start:.2f}" if seg.start else "[0.00"
        end_ts = f"-{seg.end:.2f}]" if seg.end else "-0.00]"
        log(f"  {i:3d}. {start_ts}{end_ts} {seg.text}")

    if segments:
        full_text = " ".join(s.text for s in segments)
        log(f"\n--- Full Text ---")
        log(f"  {full_text}")

    output = {
        "model": model_name,
        "adapter": adapter.display_name,
        "resolved_model": resolved_model,
        "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in segments],
        "elapsed_seconds": round(elapsed, 2),
        "language": getattr(info, 'language', None),
        "duration": getattr(info, 'duration', None),
    }

    out_file = audio_file + f".{model_name.replace(':', '_').replace('/', '_')}.transcription.json"
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"\nJSON output: {out_file}")

    return 0


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 1

    audio_file = sys.argv[1]
    model_name = sys.argv[2]
    language = sys.argv[3] if len(sys.argv) > 3 else None

    print("=" * 60)
    print(f"Transcription Test: {model_name}")
    print("=" * 60)

    return test_transcribe(audio_file, model_name, language)


if __name__ == '__main__':
    sys.exit(main())
