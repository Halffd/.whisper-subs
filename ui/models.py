"""
Shared model list provider for UI combo boxes.

Provides grouped model lists with provider prefixes so the GUI
can display models organized by backend (Local, Groq, HF, etc.).
"""
from typing import Dict, List, Tuple

try:
    import model as _model_mod
    _LOCAL: List[str] = list(_model_mod.MODEL_NAMES)
    _ADAPTER: List[str] = list(_model_mod.ADAPTER_MODEL_NAMES)
except ImportError:
    _LOCAL: List[str] = [
        "tiny", "base", "small", "medium", "large", "large-v2", "large-v3",
        "tiny.en", "base.en", "small.en", "medium.en",
        "distil-whisper/distil-large-v3", "distil-whisper/distil-large-v2",
    ]
    _ADAPTER: List[str] = []

ALL_MODELS: List[str] = _LOCAL + _ADAPTER


def get_grouped_models() -> List[Tuple[str, List[str]]]:
    """Return models grouped by provider prefix.

    Returns:
        List of (group_label, model_names) tuples, e.g.:
        [("Local (faster-whisper)", ["tiny", "base", ...]),
         ("Groq", ["groq:whisper-large-v3", ...]),
         ...]
    """
    groups: Dict[str, List[str]] = {}
    local: List[str] = []

    for name in ALL_MODELS:
        if ':' in name:
            prefix = name.split(':', 1)[0]
            groups.setdefault(prefix, []).append(name)
        else:
            local.append(name)

    result: List[Tuple[str, List[str]]] = []
    if local:
        result.append(("Local (faster-whisper)", local))
    for prefix in sorted(groups.keys()):
        label = _PROVIDER_LABELS.get(prefix, prefix.upper())
        result.append((label, groups[prefix]))
    return result


_PROVIDER_LABELS: Dict[str, str] = {
    "groq": "Groq",
    "hf": "HuggingFace",
    "whisperx": "WhisperX",
    "whispercpp": "whisper.cpp",
    "moonshine": "Moonshine",
    "deepgram": "Deepgram",
    "chirp": "Google Chirp",
    "voxtral": "Voxtral (Mistral)",
    "parakeet": "Parakeet (NVIDIA NeMo)",
    "canary": "Canary (NVIDIA NeMo)",
    "vibevoice": "VibeVoice",
    "whisperturbo": "Whisper Turbo",
}


def get_flat_display_list() -> List[str]:
    """Return a flat list with group separator headers for combo boxes.

    E.g. ["── Local (faster-whisper) ──", "tiny", "base", ...,
          "── Groq ──", "groq:whisper-large-v3", ...]
    """
    result: List[str] = []
    for label, models in get_grouped_models():
        result.append(f"\u2500\u2500 {label} \u2500\u2500")
        result.extend(models)
    return result


def is_separator(item: str) -> bool:
    """Check if a combo box item is a group separator header."""
    return item.startswith("\u2500\u2500") and item.endswith("\u2500\u2500")
