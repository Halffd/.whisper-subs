#!/usr/bin/env python3
"""Test the adapter registry, model resolution, and dispatch system.

Usage:
    python tests/test_adapter_registry.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_segment_dataclass():
    from model import Segment
    s = Segment(start=1.5, end=3.0, text="hello world")
    assert s.start == 1.5
    assert s.end == 3.0
    assert s.text == "hello world"
    print("  [PASS] Segment dataclass")


def test_adapter_classes_registered():
    from model import _ADAPTER_CLASSES
    assert len(_ADAPTER_CLASSES) >= 13, f"Expected >= 13 adapter classes, got {len(_ADAPTER_CLASSES)}"
    prefixes = set()
    for cls in _ADAPTER_CLASSES:
        inst = cls.__new__(cls)
        p = inst.prefix
        assert p not in prefixes or p == "", f"Duplicate prefix: {p}"
        prefixes.add(p)
    print(f"  [PASS] Adapter classes registered: {len(_ADAPTER_CLASSES)}")


def test_context_resolve_prefixed():
    from model import TranscriptionContext
    ctx = TranscriptionContext()
    ctx._ensure_initialized()

    for prefix, adapter in ctx._adapter_map.items():
        models = adapter.get_model_names()
        if models:
            model_name = f"{prefix}:{models[0]}"
            resolved_adapter, resolved_model = ctx.resolve(model_name)
            assert resolved_adapter is adapter
            assert resolved_model == models[0]
    print(f"  [PASS] Context.resolve() for all available adapters")


def test_context_resolve_bare():
    from model import TranscriptionContext
    ctx = TranscriptionContext()
    try:
        adapter, model = ctx.resolve("large-v3")
        assert model == "large-v3"
        print("  [PASS] Context.resolve() bare name -> default adapter")
    except ValueError:
        print("  [SKIP] No default adapter available (faster-whisper not installed)")


def test_is_api_model():
    from model import TranscriptionContext
    ctx = TranscriptionContext()

    is_api, prefix, model = ctx.is_api_model("groq:whisper-large-v3")
    assert is_api is True
    assert prefix == "groq"
    assert model == "whisper-large-v3"

    is_api, prefix, model = ctx.is_api_model("large-v3")
    assert is_api is False

    is_api, prefix, model = ctx.is_api_model("deepgram:nova-2")
    assert is_api is True
    assert prefix == "deepgram"
    print("  [PASS] Context.is_api_model()")


def test_model_names_no_duplicates():
    from model import ALL_MODEL_NAMES
    assert len(ALL_MODEL_NAMES) == len(set(ALL_MODEL_NAMES)), \
        f"Duplicates found: {[m for m in ALL_MODEL_NAMES if ALL_MODEL_NAMES.count(m) > 1]}"
    print(f"  [PASS] ALL_MODEL_NAMES has no duplicates ({len(ALL_MODEL_NAMES)} models)")


def test_adapter_prefix_format():
    from model import _ADAPTER_CLASSES
    for cls in _ADAPTER_CLASSES:
        inst = cls.__new__(cls)
        prefix = inst.prefix
        if prefix:
            assert ':' not in prefix, f"Prefix '{prefix}' should not contain ':'"
            assert prefix == prefix.lower(), f"Prefix '{prefix}' should be lowercase"
            assert ' ' not in prefix, f"Prefix '{prefix}' should not contain spaces"
    print("  [PASS] All adapter prefixes are valid identifiers")


def test_adapter_model_names_format():
    from model import ADAPTER_MODEL_NAMES
    for name in ADAPTER_MODEL_NAMES:
        assert ':' in name, f"Adapter model name '{name}' must contain ':' separator"
        prefix, model = name.split(':', 1)
        assert prefix, f"Empty prefix in '{name}'"
        assert model, f"Empty model in '{name}'"
    print(f"  [PASS] All ADAPTER_MODEL_NAMES use provider:model format ({len(ADAPTER_MODEL_NAMES)})")


def test_ui_models():
    from ui.models import get_flat_display_list, is_separator, ALL_MODELS
    flat = get_flat_display_list()
    seps = [x for x in flat if is_separator(x)]
    models = [x for x in flat if not is_separator(x)]

    assert len(seps) >= 5, f"Expected >= 5 separators, got {len(seps)}"
    assert len(models) >= 20, f"Expected >= 20 models, got {len(models)}"
    for s in seps:
        assert s.startswith('\u2500'), f"Separator '{s}' should start with box-drawing char"
    print(f"  [PASS] UI models: {len(flat)} items ({len(seps)} groups, {len(models)} models)")


def test_adapter_auto_discovery():
    from model import _ADAPTER_CLASSES
    class_names = [cls.__name__ for cls in _ADAPTER_CLASSES]
    expected = [
        'CanaryAdapter', 'ChirpAdapter', 'DeepgramAdapter',
        'FasterWhisperAdapter', 'GroqAdapter', 'HuggingFaceAdapter',
        'MoonshineAdapter', 'ParakeetAdapter', 'VibeVoiceAdapter',
        'VoxtralAdapter', 'WhisperCppAdapter', 'WhisperTurboAdapter',
        'WhisperXAdapter',
    ]
    for name in expected:
        assert name in class_names, f"Missing adapter: {name}"
    print(f"  [PASS] All 13 adapters auto-discovered")


def main():
    tests = [
        test_segment_dataclass,
        test_adapter_classes_registered,
        test_adapter_auto_discovery,
        test_context_resolve_prefixed,
        test_context_resolve_bare,
        test_is_api_model,
        test_model_names_no_duplicates,
        test_adapter_prefix_format,
        test_adapter_model_names_format,
        test_ui_models,
    ]

    print("=" * 60)
    print("Adapter Registry & Dispatch Tests")
    print("=" * 60)
    passed = 0
    failed = 0
    skipped = 0
    for test in tests:
        name = test.__name__
        try:
            result = test()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            failed += 1

    print("-" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
