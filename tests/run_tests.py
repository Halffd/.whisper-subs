#!/usr/bin/env python3
"""Comprehensive test runner for the whisper-subs adapter system.

Runs all test suites and reports results. Can also run transcription
tests against audio files if provided.

Usage:
    # Run unit tests only (no API keys or audio needed)
    python tests/run_tests.py

    # Run unit tests + transcription tests with an audio file
    python tests/run_tests.py --audio path/to/audio.wav

    # Run transcription test for a specific model
    python tests/run_tests.py --audio path/to/audio.wav --model groq:whisper-large-v3

    # Run with specific language
    python tests/run_tests.py --audio path/to/audio.wav --model large-v3 --lang en

    # List available adapters and exit
    python tests/run_tests.py --list-adapters

    # Generate test audio file
    python tests/run_tests.py --generate-audio
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.results = []

    def _record(self, name, status, detail=""):
        self.results.append({"name": name, "status": status, "detail": detail})
        if status == "PASS":
            self.passed += 1
        elif status == "FAIL":
            self.failed += 1
        elif status == "SKIP":
            self.skipped += 1

    def run_unit_tests(self):
        print("\n" + "=" * 60)
        print("UNIT TESTS")
        print("=" * 60)

        from model import (
            Segment, TranscriptionContext, ALL_MODEL_NAMES,
            ADAPTER_MODEL_NAMES, MODEL_NAMES, _ADAPTER_CLASSES,
        )

        # --- Segment ---
        try:
            s = Segment(start=1.0, end=2.0, text="test")
            assert s.start == 1.0 and s.end == 2.0 and s.text == "test"
            self._record("Segment dataclass", "PASS")
        except Exception as e:
            self._record("Segment dataclass", "FAIL", str(e))

        # --- Adapter count ---
        try:
            assert len(_ADAPTER_CLASSES) >= 13
            self._record("Adapter classes >= 13", "PASS", f"{len(_ADAPTER_CLASSES)} registered")
        except Exception as e:
            self._record("Adapter classes >= 13", "FAIL", str(e))

        # --- No duplicate model names ---
        try:
            dupes = [m for m in ALL_MODEL_NAMES if ALL_MODEL_NAMES.count(m) > 1]
            assert len(dupes) == 0, f"Duplicates: {set(dupes)}"
            self._record("No duplicate model names", "PASS", f"{len(ALL_MODEL_NAMES)} unique")
        except Exception as e:
            self._record("No duplicate model names", "FAIL", str(e))

        # --- Adapter prefix format ---
        try:
            for cls in _ADAPTER_CLASSES:
                inst = cls.__new__(cls)
                p = inst.prefix
                if p:
                    assert ':' not in p and ' ' not in p and p == p.lower()
            self._record("Adapter prefix format", "PASS")
        except Exception as e:
            self._record("Adapter prefix format", "FAIL", str(e))

        # --- ADAPTER_MODEL_NAMES format ---
        try:
            for name in ADAPTER_MODEL_NAMES:
                assert ':' in name
                prefix, model = name.split(':', 1)
                assert prefix and model
            self._record("ADAPTER_MODEL_NAMES format", "PASS", f"{len(ADAPTER_MODEL_NAMES)} names")
        except Exception as e:
            self._record("ADAPTER_MODEL_NAMES format", "FAIL", str(e))

        # --- Context resolve ---
        try:
            ctx = TranscriptionContext()
            ctx._ensure_initialized()
            for prefix, adapter in ctx._adapter_map.items():
                models = adapter.get_model_names()
                if models:
                    a, m = ctx.resolve(f"{prefix}:{models[0]}")
                    assert a is adapter
            self._record("Context.resolve() prefixed", "PASS",
                         f"tested {len(ctx._adapter_map)} adapters")
        except Exception as e:
            self._record("Context.resolve() prefixed", "FAIL", str(e))

        # --- is_api_model ---
        try:
            ctx = TranscriptionContext()
            assert ctx.is_api_model("groq:whisper-large-v3") == (True, "groq", "whisper-large-v3")
            assert ctx.is_api_model("large-v3")[0] is False
            self._record("Context.is_api_model()", "PASS")
        except Exception as e:
            self._record("Context.is_api_model()", "FAIL", str(e))

        # --- UI models ---
        try:
            from ui.models import get_flat_display_list, is_separator
            flat = get_flat_display_list()
            seps = [x for x in flat if is_separator(x)]
            models = [x for x in flat if not is_separator(x)]
            assert len(seps) >= 5 and len(models) >= 20
            self._record("UI model list", "PASS", f"{len(seps)} groups, {len(models)} models")
        except Exception as e:
            self._record("UI model list", "FAIL", str(e))

        # --- All Python files compile ---
        try:
            import py_compile
            errors = []
            for root, dirs, files in os.walk(os.path.join(os.path.dirname(__file__), '..')):
                if '__pycache__' in root or '.git' in root:
                    continue
                for f in files:
                    if f.endswith('.py'):
                        path = os.path.join(root, f)
                        try:
                            py_compile.compile(path, doraise=True)
                        except py_compile.PyCompileError as e:
                            errors.append(f"{path}: {e}")
            if errors:
                self._record("All files compile", "FAIL", f"{len(errors)} errors")
            else:
                self._record("All files compile", "PASS")
        except Exception as e:
            self._record("All files compile", "FAIL", str(e))

    def run_adapter_status(self):
        print("\n" + "=" * 60)
        print("ADAPTER STATUS")
        print("=" * 60)

        from model import TranscriptionContext
        ctx = TranscriptionContext()
        ctx._ensure_initialized()

        all_adapters = {}
        from model import _ADAPTER_CLASSES
        for cls in _ADAPTER_CLASSES:
            try:
                inst = cls()
                all_adapters[inst.prefix or "(local)"] = {
                    "class": cls.__name__,
                    "available": inst.is_available(),
                    "models": inst.get_model_names(),
                    "prefix": inst.prefix,
                }
            except Exception as e:
                all_adapters[f"error:{cls.__name__}"] = {
                    "class": cls.__name__,
                    "available": False,
                    "models": [],
                    "prefix": "",
                    "error": str(e),
                }

        available = {k: v for k, v in all_adapters.items() if v["available"]}
        unavailable = {k: v for k, v in all_adapters.items() if not v["available"]}

        print(f"\n  Available ({len(available)}):")
        for prefix, info in sorted(available.items()):
            models_str = ", ".join(info["models"][:3])
            if len(info["models"]) > 3:
                models_str += f" (+{len(info['models']) - 3} more)"
            print(f"    {prefix:20s}  {info['class']:25s}  [{models_str}]")

        print(f"\n  Unavailable ({len(unavailable)}):")
        for prefix, info in sorted(unavailable.items()):
            reason = info.get("error", "missing dependency/key")
            print(f"    {prefix:20s}  {info['class']:25s}  ({reason})")

        self._record("Adapters available", "PASS" if available else "SKIP",
                      f"{len(available)}/{len(all_adapters)}")

    def run_transcribe_test(self, audio_file: str, model_name: str, language: str = None):
        print("\n" + "=" * 60)
        print(f"TRANSCRIPTION TEST: {model_name}")
        print("=" * 60)

        if not os.path.exists(audio_file):
            self._record(f"Transcribe {model_name}", "SKIP", f"audio not found: {audio_file}")
            return

        from model import TranscriptionContext

        ctx = TranscriptionContext()
        try:
            adapter, resolved = ctx.resolve(model_name)
            print(f"  Adapter:  {adapter.display_name}")
            print(f"  Model:    {resolved}")
        except ValueError as e:
            self._record(f"Transcribe {model_name}", "FAIL", str(e))
            return

        start = time.time()
        try:
            segments, info = ctx.transcribe(
                audio_file=audio_file,
                model_name=model_name,
                language=language,
                write=lambda m: print(f"    {m}"),
            )
            elapsed = time.time() - start

            full_text = " ".join(s.text for s in segments)
            print(f"\n  Segments: {len(segments)}")
            print(f"  Time:     {elapsed:.1f}s")
            print(f"  Text:     {full_text[:200]}{'...' if len(full_text) > 200 else ''}")

            if segments and any(s.text.strip() for s in segments):
                self._record(f"Transcribe {model_name}", "PASS",
                             f"{len(segments)} segments, {elapsed:.1f}s")
            else:
                self._record(f"Transcribe {model_name}", "FAIL",
                             "no text in segments")

        except Exception as e:
            elapsed = time.time() - start
            self._record(f"Transcribe {model_name}", "FAIL", f"{e} ({elapsed:.1f}s)")

    def run_all_transcribe_tests(self, audio_file: str, language: str = None):
        from model import TranscriptionContext
        ctx = TranscriptionContext()
        ctx._ensure_initialized()

        models_to_test = []

        if ctx._default_adapter and ctx._default_adapter.is_available():
            models_to_test.append("tiny")

        for prefix, adapter in ctx._adapter_map.items():
            models = adapter.get_model_names()
            if models:
                models_to_test.append(f"{prefix}:{models[0]}")

        if not models_to_test:
            print("\n  No adapters available for transcription testing.")
            print("  Set API keys or install dependencies to enable adapters.")
            return

        print(f"\n  Will test {len(models_to_test)} models: {models_to_test}")

        for model_name in models_to_test:
            self.run_transcribe_test(audio_file, model_name, language)

    def generate_audio(self):
        print("Generating test audio...")
        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), 'generate_test_audio.py')],
            check=True,
        )

    def list_adapters(self):
        from model import TranscriptionContext, _ADAPTER_CLASSES
        ctx = TranscriptionContext()
        ctx._ensure_initialized()

        print("\nAll registered adapters:")
        for cls in _ADAPTER_CLASSES:
            try:
                inst = cls()
                available = inst.is_available()
                prefix = inst.prefix or "(local)"
                models = inst.get_model_names()
                status = "AVAILABLE" if available else "unavailable"
                print(f"\n  {cls.__name__} [{status}]")
                print(f"    Prefix:  {prefix}")
                print(f"    Display: {inst.display_name}")
                print(f"    Models:  {', '.join(models)}")
            except Exception as e:
                print(f"\n  {cls.__name__} [ERROR: {e}]")

        print(f"\nActive adapter map: {list(ctx._adapter_map.keys())}")
        if ctx._default_adapter:
            print(f"Default adapter: {ctx._default_adapter.display_name}")

    def print_summary(self):
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        for r in self.results:
            icon = {"PASS": "+", "FAIL": "X", "SKIP": "o"}[r["status"]]
            detail = f" ({r['detail']})" if r["detail"] else ""
            print(f"  [{icon}] {r['name']}{detail}")

        total = self.passed + self.failed + self.skipped
        print(f"\n  {self.passed}/{total} passed, {self.failed} failed, {self.skipped} skipped")
        print("=" * 60)
        return 0 if self.failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="whisper-subs test runner")
    parser.add_argument('--audio', help="Audio file for transcription tests")
    parser.add_argument('--model', help="Specific model to test (e.g. groq:whisper-large-v3)")
    parser.add_argument('--lang', help="Language code (e.g. en, ja, es)")
    parser.add_argument('--list-adapters', action='store_true', help="List all adapters and exit")
    parser.add_argument('--generate-audio', action='store_true', help="Generate test audio files")
    args = parser.parse_args()

    runner = TestRunner()

    if args.list_adapters:
        runner.list_adapters()
        return 0

    if args.generate_audio:
        runner.generate_audio()
        return 0

    runner.run_unit_tests()
    runner.run_adapter_status()

    if args.audio:
        if args.model:
            runner.run_transcribe_test(args.audio, args.model, args.lang)
        else:
            runner.run_all_transcribe_tests(args.audio, args.lang)

    return runner.print_summary()


if __name__ == '__main__':
    sys.exit(main())
