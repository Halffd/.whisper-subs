"""
WhisperSubs Model Module

Centralized model name management, validation, and transcription adapter registry.
Uses the Adapter + Strategy patterns to support multiple transcription backends
through a unified interface.
"""

import sys
import os
import argparse
import importlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# ============ Segment Data Class ============


@dataclass
class Segment:
    start: float
    end: float
    text: str
    # Word-level detail (WhisperX alignment). Empty when the backend is
    # segment-only — the writer treats absent words as plain text cues.
    words: Optional[List[Dict[str, Any]]] = None
    # Mean per-word alignment confidence, 0.0-1.0. None = not computed.
    confidence: Optional[float] = None
    # BCP-47-ish language tag from the backend (ja, en, ...). Drives
    # furigana rendering and SRT metadata.
    language: Optional[str] = None
    # Speaker label from diarization (pyannote). None when not diarized.
    speaker: Optional[str] = None


# ============ Transcription Adapter (Strategy Interface) ============


class TranscriptionAdapter(ABC):
    """Abstract base class for transcription backends (Strategy pattern)."""

    @abstractmethod
    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        """Transcribe audio and return (segments, info).

        The segments may be a list or an iterator. An iterator lets the
        caller write the cues into the in-progress subtitle file while
        the model is still working (see the parakeet adapter).
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this adapter's dependencies are installed."""
        ...

    @abstractmethod
    def get_model_names(self) -> List[str]:
        """Return model names this adapter supports (without prefix)."""
        ...

    @property
    def prefix(self) -> str:
        """Prefix used to route models to this adapter (e.g. 'groq', 'whispercpp')."""
        return ""

    @property
    def display_name(self) -> str:
        """Human-readable name for logging."""
        return self.__class__.__name__

    def install_hint(self) -> str:
        """Command that makes this adapter usable, shown when it is missing."""
        return ""


# ============ Adapter Registry ============

_ADAPTER_CLASSES: List[Type[TranscriptionAdapter]] = []


def register_adapter(cls: Type[TranscriptionAdapter]) -> Type[TranscriptionAdapter]:
    """Class decorator to register an adapter."""
    _ADAPTER_CLASSES.append(cls)
    return cls


def get_adapter_instances() -> List[TranscriptionAdapter]:
    """Instantiate all registered adapters (filters only those that crash on init)."""
    instances = []
    for cls in _ADAPTER_CLASSES:
        try:
            inst = cls()
            instances.append(inst)
        except Exception:
            pass
    return instances


def build_adapter_map() -> Dict[str, TranscriptionAdapter]:
    """Build prefix -> adapter instance map for routing (includes unavailable adapters)."""
    adapter_map: Dict[str, TranscriptionAdapter] = {}
    for adapter in get_adapter_instances():
        p = adapter.prefix
        if p:
            adapter_map[p] = adapter
    return adapter_map


# ============ Transcription Context (Adapter Dispatcher) ============


class TranscriptionContext:
    """Resolves a model identifier to the correct adapter and dispatches transcription."""

    def __init__(self):
        self._adapter_map: Optional[Dict[str, TranscriptionAdapter]] = None
        self._default_adapter: Optional[TranscriptionAdapter] = None

    def _ensure_initialized(self):
        if self._adapter_map is None:
            self._adapter_map = build_adapter_map()
            from adapters.faster_whisper_adapter import FasterWhisperAdapter

            try:
                self._default_adapter = FasterWhisperAdapter()
            except Exception:
                self._default_adapter = None

    def resolve(self, model_name: str) -> Tuple[TranscriptionAdapter, str]:
        """Resolve model_name to (adapter, stripped_model_name).

        For prefixed models like 'groq:whisper-large-v3', returns
        (GroqAdapter, 'whisper-large-v3').
        For bare names like 'large-v3', returns (FasterWhisperAdapter, 'large-v3').
        """
        self._ensure_initialized()
        if ":" in model_name:
            prefix, rest = model_name.split(":", 1)
            adapter = self._adapter_map.get(prefix)
            if adapter is None:
                all_prefixes = list(self._adapter_map.keys())
                raise ValueError(
                    f"Unknown adapter prefix '{prefix}'. Available: {all_prefixes}"
                )
            if not adapter.is_available():
                hint = adapter.install_hint()
                install = f" Install with: {hint}" if hint else ""
                raise ValueError(
                    f"Adapter '{prefix}' ({adapter.display_name}) is not available."
                    f"{install}"
                )
            return adapter, rest
        if self._default_adapter and self._default_adapter.is_available():
            return self._default_adapter, model_name
        raise ValueError(
            f"No default transcription adapter available for model '{model_name}'"
        )

    def transcribe(
        self,
        audio_file: str,
        model_name: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        """Dispatch transcription to the correct adapter.

        An adapter returns ``(segments, info)``. For a streaming adapter
        the segments may be an iterator that produces cues while the
        model is still running - the caller consumes it once. A streaming
        adapter written as a generator function returns the iterator
        itself; that is accepted too.
        """
        adapter, resolved_model = self.resolve(model_name)
        write(f"Using {adapter.display_name} with model {resolved_model}")
        result = adapter.transcribe(
            audio_file=audio_file,
            model=resolved_model,
            language=language,
            write=write,
            temperature=temperature,
            **kwargs,
        )
        if isinstance(result, tuple) and len(result) == 2:
            return result
        # Generator-function adapter: the segments are the result.
        return result, None

    def is_api_model(self, model_name: str) -> Tuple[bool, str, str]:
        """Check if model_name refers to a non-local (API/subprocess) backend.

        Returns (is_remote, provider_prefix, actual_model_name).
        """
        self._ensure_initialized()
        if ":" in model_name:
            prefix, rest = model_name.split(":", 1)
            return True, prefix, rest
        return False, "", model_name

    def list_available_adapters(self) -> List[Dict[str, Any]]:
        """List all registered adapters and their models (including unavailable)."""
        self._ensure_initialized()
        result = []
        if self._default_adapter:
            result.insert(
                0,
                {
                    "prefix": "(local/faster-whisper)",
                    "name": self._default_adapter.display_name,
                    "models": self._default_adapter.get_model_names(),
                    "available": self._default_adapter.is_available(),
                },
            )
        for prefix, adapter in self._adapter_map.items():
            result.append(
                {
                    "prefix": prefix,
                    "name": adapter.display_name,
                    "models": adapter.get_model_names(),
                    "available": adapter.is_available(),
                }
            )
        return result


_context: Optional[TranscriptionContext] = None


def get_context() -> TranscriptionContext:
    """Get or create the singleton TranscriptionContext."""
    global _context
    if _context is None:
        _context = TranscriptionContext()
    return _context


# ============ Model Configuration ============

MODEL_NAMES: List[str] = [
    "tiny",
    "base",
    "small",
    "medium",
    "large",
    "large-v2",
    "large-v3",
    "tiny.en",
    "base.en",
    "small.en",
    "medium.en",
    "distil-whisper/distil-large-v3",
    "distil-whisper/distil-large-v2",
    "distil-whisper/distil-medium.en",
    "distil-whisper/distil-small.en",
    "jlondonobo/whisper-medium-pt",
    "clu-ling/whisper-large-v2-japanese-5k-steps",
    "distil-whisper/distil-base",
    "distil-whisper/distil-small",
    "distil-whisper/distil-medium",
    "distil-whisper/distil-large",
    "japanese-asr/distil-whisper-large-v3-ja-reazonspeech-large",
]

# Adapter-prefixed model identifiers
ADAPTER_MODEL_NAMES: List[str] = [
    "groq:whisper-large-v3",
    "groq:whisper-large-v3-turbo",
    "groq:distil-whisper-large-v3-en",
    "hf:openai/whisper-large-v3",
    "hf:openai/whisper-large-v3-turbo",
    "hf:nvidia/parakeet-ctc-1.1b-asr",
    "hf:nvidia/canary-1b-flash",
    "whisperx:large-v3",
    "whisperx:medium",
    "whisperx:base",
    "whisperx:small",
    "whispercpp:base",
    "whispercpp:small",
    "whispercpp:medium",
    "whispercpp:large-v3",
    # Quantized whisper.cpp models (ggml-*.bin); keep the plain variants
    # first so `whispercpp` as a provider alias still resolves to `base`.
    "whispercpp:large-v3-turbo",
    "whispercpp:tiny-q5_1",
    "whispercpp:tiny-q8_0",
    "whispercpp:base-q5_1",
    "whispercpp:base-q8_0",
    "whispercpp:small-q5_1",
    "whispercpp:small-q8_0",
    "whispercpp:medium-q5_0",
    "whispercpp:medium-q8_0",
    "whispercpp:large-v2-q5_0",
    "whispercpp:large-v2-q8_0",
    "whispercpp:large-v3-q5_0",
    "whispercpp:large-v3-turbo-q5_0",
    "whispercpp:large-v3-turbo-q8_0",
    "whispercpp:tiny.en-q5_1",
    "whispercpp:tiny.en-q8_0",
    "whispercpp:base.en-q5_1",
    "whispercpp:base.en-q8_0",
    "whispercpp:small.en-q5_1",
    "whispercpp:small.en-q8_0",
    "whispercpp:medium.en-q5_0",
    "whispercpp:medium.en-q8_0",
    "moonshine:moonshine/base",
    "moonshine:moonshine/tiny",
    "deepgram:nova-3",
    "deepgram:nova-2",
    "deepgram:whisper-turbo",
    "chirp:chirp_2",
    "chirp:chirp",
    "voxtral:voxtral-mini",
    "parakeet:parakeet-tdt-0.6b-v2",
    "parakeet:parakeet-tdt-0.6b-v3",
    "parakeet:parakeet-ctc-1.1b",
    "parakeet:parakeet-rnnt-1.1b",
    "parakeet:parakeet-ctc-0.6b",
    "parakeet:parakeet-rnnt-0.6b",
    "sherpa:parakeet-tdt-0.6b-v2",
    "sherpa:parakeet-tdt-0.6b-v3",
    "sherpa:nemotron-streaming-en-0.6b",
    "canary:canary-1b-flash",
    "canary:canary-1b",
    "vibevoice:vibevoice-1b",
    "whisperturbo:whisper-large-v3-turbo",
]

ALL_MODEL_NAMES: List[str] = MODEL_NAMES + ADAPTER_MODEL_NAMES


def getIndex(model_name: str) -> int:
    try:
        return ALL_MODEL_NAMES.index(model_name)
    except ValueError:
        return -1


def _normalize_provider_alias(value: str) -> str:
    """Fold a provider name to a comparable key ('whisper.cpp' -> 'whispercpp')."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _default_model_for_prefix(prefix: str, adapter: TranscriptionAdapter) -> Optional[str]:
    """Canonical model used when a provider is named without a model."""
    for name in ADAPTER_MODEL_NAMES:
        if name.startswith(prefix + ":"):
            return name
    models = adapter.get_model_names()
    return f"{prefix}:{models[0]}" if models else None


_alias_map: Optional[Dict[str, str]] = None
_alias_adapters: Optional[Dict[str, TranscriptionAdapter]] = None


def _provider_alias_map() -> Tuple[Dict[str, str], Dict[str, TranscriptionAdapter]]:
    """Map every provider spelling (prefix, display name) to its prefix."""
    global _alias_map, _alias_adapters
    if _alias_map is None or _alias_adapters is None:
        alias_map: Dict[str, str] = {}
        adapters = build_adapter_map()
        for prefix, adapter in adapters.items():
            alias_map[_normalize_provider_alias(prefix)] = prefix
            alias_map[_normalize_provider_alias(adapter.display_name)] = prefix
        _alias_map = alias_map
        _alias_adapters = adapters
    return _alias_map, _alias_adapters


def resolve_provider_prefix(value: str) -> Optional[str]:
    """Canonical adapter prefix for a provider spelling, or None."""
    key = _normalize_provider_alias(value)
    if not key:
        return None
    alias_map, _adapters = _provider_alias_map()
    return alias_map.get(key)


def resolve_provider_alias(value: str) -> Optional[str]:
    """Map a provider name to '<prefix>:<model>'.

    Accepts the adapter prefix ('whispercpp') and the display name
    ('whisper.cpp', 'WhisperX'), so a backend can be selected without
    remembering its exact spelling. Returns None when the value is not a
    provider name.
    """
    prefix = resolve_provider_prefix(value)
    if not prefix:
        return None
    _alias_map, adapters = _provider_alias_map()
    adapter = adapters.get(prefix)
    if adapter is None:
        return None
    return _default_model_for_prefix(prefix, adapter)


def list_available_models() -> None:
    print("Available models:")
    print("\n  -- Local (faster-whisper) --")
    for i, model in enumerate(MODEL_NAMES):
        print(f"  {i:2d}: {model}")
    offset = len(MODEL_NAMES)
    print("\n  -- Adapter Backends --")
    for i, model in enumerate(ADAPTER_MODEL_NAMES):
        print(f"  {offset + i:2d}: {model}")
    print(
        "\n  Use 'provider:model' syntax for adapter models (e.g., groq:whisper-large-v3)"
    )
    try:
        ctx = get_context()
        adapters = ctx.list_available_adapters()
        if adapters:
            print("\n  -- Available Adapters --")
            for a in adapters:
                status = "OK" if a.get("models") else "no models"
                print(f"  {a['prefix']}: {a['name']} [{status}]")
    except Exception:
        pass


# ============ Argument Parsing ============


def getName(value: str) -> Optional[str]:
    if ":" in value:
        # The provider part may contain dots ('whisper.cpp:small'), so try
        # every colon from the left and take the first known provider.
        for index, char in enumerate(value):
            if char != ":":
                continue
            canonical = resolve_provider_prefix(value[:index])
            if canonical:
                return f"{canonical}:{value[index + 1:]}"
        return value
    if value in ALL_MODEL_NAMES or value in MODEL_NAMES:
        return value
    alias = resolve_provider_alias(value)
    if alias:
        return alias
    try:
        model_index = int(value)
        if 0 <= model_index < len(ALL_MODEL_NAMES):
            return ALL_MODEL_NAMES[model_index]
        else:
            raise argparse.ArgumentTypeError(
                f"Model index {model_index} is out of range (0-{len(ALL_MODEL_NAMES) - 1})."
            )
    except ValueError:
        if value in ALL_MODEL_NAMES:
            return value
        import difflib

        matches = difflib.get_close_matches(value, ALL_MODEL_NAMES)
        error_msg = f"Invalid model name: '{value}'. Not found in available models."
        if matches:
            error_msg += f" Did you mean: '{', '.join(matches)}'?"
        raise argparse.ArgumentTypeError(error_msg)


def parse_arguments(description: str = "Whisper Model CLI"):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "model",
        nargs="?",
        type=getName,
        help="The primary model to use (name, index, or provider:model).",
        default=None,
    )
    parser.add_argument(
        "realtime_model",
        nargs="?",
        type=getName,
        help="[Captioner Mode] The faster, real-time model to use.",
        default=None,
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Language code (e.g., 'en', 'ja'). 'none' for auto-detect.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all available models and their indices, then exit.",
    )
    captioner_group = parser.add_argument_group("Captioner Mode Options")
    captioner_group.add_argument(
        "-w", "--web", action="store_true", help="Enable the web UI for the captioner."
    )
    captioner_group.add_argument(
        "-g", "--gui", action="store_true", help="Enable the GUI for the captioner."
    )
    captioner_group.add_argument(
        "--debug", dest="debug_mode", action="store_true", help="Enable debug mode."
    )
    captioner_group.add_argument(
        "--test", dest="test_mode", action="store_true", help="Enable test mode."
    )
    parser.add_argument(
        "-m", "--model-flag", dest="model", type=getName, help=argparse.SUPPRESS
    )

    args = parser.parse_args()

    if args.list_models:
        list_available_models()
        sys.exit(0)

    if args.model is None:
        list_available_models()
        try:
            selection = input("Choose a model by its index or name: ")
            args.model = getName(selection)
        except (EOFError, KeyboardInterrupt):
            print("\nNo model selected. Exiting.")
            sys.exit(1)
        except argparse.ArgumentTypeError as e:
            print(f"Error: {e}")
            sys.exit(1)

    if args.realtime_model is None:
        args.realtime_model = args.model

    if args.lang and args.lang.lower() == "none":
        args.lang = None

    return args


# ============ Auto-discover and import adapters ============


def _import_adapters():
    """Import all adapter modules from the adapters/ package."""
    adapters_dir = os.path.join(os.path.dirname(__file__), "adapters")
    if not os.path.isdir(adapters_dir):
        return
    for fname in sorted(os.listdir(adapters_dir)):
        if fname.endswith("_adapter.py") and not fname.startswith("_"):
            module_name = f"adapters.{fname[:-3]}"
            try:
                importlib.import_module(module_name)
            except Exception as e:
                print(f"Warning: could not import adapter {module_name}: {e}")


_import_adapters()

if __name__ == "__main__":
    print("--- Running Argument Parser Example ---")
    try:
        config = parse_arguments()
        print("\n--- Parsed Configuration ---")
        print(f"Primary Model: {config.model}")
        print(f"Real-time Model:{config.realtime_model}")
        print(f"Language: {config.lang or 'Auto-Detect'}")
        print(f"Web UI: {'Enabled' if config.web else 'Disabled'}")
        print(f"GUI: {'Enabled' if config.gui else 'Disabled'}")
        print(f"Debug Mode: {'Enabled' if config.debug_mode else 'Disabled'}")
        print(f"Test Mode: {'Enabled' if config.test_mode else 'Disabled'}")
        print("--------------------------")
    except SystemExit as e:
        if e.code != 0:
            print(
                f"\nExited with code {e.code}. Likely due to --help, --list-models, or an error."
            )
