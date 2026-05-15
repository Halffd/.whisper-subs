# .whisper-subs

Transcribe YouTube videos, local audio/video files, and live streams to subtitles using multiple ASR backends. Supports 13 transcription adapters (local + cloud) through a unified `provider:model` interface.

## Features

- **Multi-backend transcription**: 13 adapters — local (faster-whisper, whisper.cpp, WhisperX, Moonshine, Voxtral, VibeVoice, Whisper Turbo) and cloud (Groq, Deepgram, Google Chirp, HuggingFace, NVIDIA Canary/Parakeet)
- **Unified model syntax**: Use `provider:model` (e.g. `groq:whisper-large-v3`) or bare names for local models
- **YouTube transcription**: Download and transcribe videos/channels via `yt-dlp`
- **MKV/file selector**: GUI for selecting and transcribing local files
- **Live captioner**: Real-time captioning with PyQt6/GTK4/tkinter interfaces
- **API server**: FastAPI/Flask transcription endpoints
- **Auto-adapter discovery**: Only adapters with installed dependencies appear as available
- **Provider-grouped model lists**: GUI dropdowns organized by provider with separator headers

## Quick Start

```bash
# Clone and install
git clone https://github.com/yourusername/.whisper-subs.git
cd .whisper-subs
pip install -r requirements.txt

# Transcribe a YouTube video (URL from clipboard)
python whisper_subs.py large-v3

# Transcribe a local file
python whisper_subs.py large-v3 /path/to/audio.wav

# Use a cloud backend
GROQ_API_KEY=gsk_... python whisper_subs.py groq:whisper-large-v3 /path/to/audio.wav

# List all available models
python -m model --list-models
```

## Transcription Adapters

All adapters implement the `TranscriptionAdapter` ABC and return `List[Segment]` with consistent `(start, end, text)` tuples. Models use the `provider:model` prefix syntax — bare model names default to the local faster-whisper backend.

### Adapter Reference

| Adapter | Prefix | Models | Type | Dependency / Env Var |
|---|---|---|---|---|
| **Faster Whisper** | *(bare name)* | `tiny`, `base`, `small`, `medium`, `large`, `large-v2`, `large-v3`, `*.en`, `distil-*` | Local | `faster-whisper` pip package |
| **whisper.cpp** | `whispercpp:` | `base`, `small`, `medium`, `large-v3`, `tiny`, `large-v2` | Local | `whisper-cpp` or `main` binary in PATH |
| **WhisperX** | `whisperx:` | `large-v3`, `medium`, `base`, `small`, `tiny`, `*.en` | Local | `whisperx` pip package |
| **Whisper Turbo** | `whisperturbo:` | `whisper-large-v3-turbo` | Local | `torch` + `transformers` |
| **Moonshine** | `moonshine:` | `moonshine/base`, `moonshine/tiny` | Local | `moonshine` or `transformers` |
| **Voxtral** | `voxtral:` | `voxtral-mini` | Local | `torch` + `transformers` |
| **VibeVoice** | `vibevoice:` | `vibevoice-1b` | Local | `torch` + `transformers` |
| **Groq** | `groq:` | `whisper-large-v3`, `whisper-large-v3-turbo`, `distil-whisper-large-v3-en` | Cloud | `GROQ_API_KEY` |
| **Deepgram** | `deepgram:` | `nova-3`, `nova-2`, `whisper-turbo`, `nova-2-phonecall`, `enhanced` | Cloud | `DEEPGRAM_API_KEY` |
| **Google Chirp** | `chirp:` | `chirp_2`, `chirp`, `long`, `latest_short`, `latest_long` | Cloud | `GOOGLE_APPLICATION_CREDENTIALS` |
| **HuggingFace** | `hf:` | `openai/whisper-large-v3`, `openai/whisper-large-v3-turbo`, `nvidia/parakeet-ctc-1.1b-asr`, `nvidia/canary-1b-flash` | Cloud | `HF_API_KEY` |
| **NVIDIA Canary** | `canary:` | `canary-1b-flash`, `canary-1b` | Local | `nemo` pip package |
| **NVIDIA Parakeet** | `parakeet:` | `parakeet-ctc-1.1b`, `parakeet-rnnt-1.1b`, `parakeet-ctc-0.6b`, `parakeet-rnnt-0.6b` | Local | `nemo` pip package |

### Usage Examples

```bash
# Local faster-whisper (default)
python whisper_subs.py large-v3 video.mp4
python whisper_subs.py base.en audio.wav

# Cloud backends (set API key first)
export GROQ_API_KEY="gsk_your_key_here"
python whisper_subs.py groq:whisper-large-v3 video.mp4

export DEEPGRAM_API_KEY="your_key_here"
python whisper_subs.py deepgram:nova-2 audio.wav

export HF_API_KEY="hf_your_key_here"
python whisper_subs.py hf:openai/whisper-large-v3 audio.wav

export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
python whisper_subs.py chirp:chirp_2 audio.wav

# Local alternative backends
python whisper_subs.py whispercpp:base audio.wav          # needs whisper-cpp binary
python whisper_subs.py whisperturbo:whisper-large-v3-turbo audio.wav  # needs torch+transformers
python whisper_subs.py moonshine:moonshine-tiny audio.wav # needs moonshine or transformers
python whisper_subs.py voxtral:voxtral-mini audio.wav     # needs torch+transformers
python whisper_subs.py vibevoice:vibevoice-1b audio.wav   # needs torch+transformers
python whisper_subs.py whisperx:large-v3 audio.wav        # needs whisperx package
python whisper_subs.py canary:canary-1b-flash audio.wav   # needs nemo package
python whisper_subs.py parakeet:parakeet-ctc-1.1b audio.wav # needs nemo package
```

### Environment Variables

| Variable | Adapter | How to Get |
|---|---|---|
| `GROQ_API_KEY` | Groq | [console.groq.com](https://console.groq.com/keys) |
| `DEEPGRAM_API_KEY` | Deepgram | [console.deepgram.com](https://console.deepgram.com/) |
| `HF_API_KEY` | HuggingFace | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `HF_TOKEN` | WhisperX (diarization) | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Chirp | [cloud.google.com/iam](https://cloud.google.com/iam/docs/creating-managing-service-account-keys) |

Set them in your shell or in the `.env` file (already gitignored):

```bash
# .env
GROQ_API_KEY=gsk_...
DEEPGRAM_API_KEY=...
HF_API_KEY=hf_...
GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-sa.json
```

## Installation

### Base (local faster-whisper)

```bash
pip install -r requirements.txt
```

### Cloud API backends

```bash
pip install requests    # Groq, Deepgram, HuggingFace adapters use requests
```

### Specific adapter dependencies

```bash
# whisper.cpp — install the binary
# Arch: yay -S whisper-cpp
# Ubuntu: see https://github.com/ggerganov/whisper.cpp
# macOS: brew install whisper-cpp

# WhisperX
pip install whisperx

# Whisper Turbo / Moonshine / Voxtral / VibeVoice (transformers-based)
pip install torch transformers

# NVIDIA NeMo (Canary, Parakeet)
pip install nemo_toolkit

# Google Chirp
pip install google-cloud-speech

# Groq SDK (optional, uses requests by default)
pip install groq

# Deepgram SDK (optional, uses requests by default)
pip install deepgram-sdk
```

### GUI dependencies

```bash
pip install -r requirements_gui.txt # PyQt6 GUI
# For GTK4: system packages (python-gobject, gtk4)
# For tkinter: usually included with Python
```

### API server

```bash
pip install -r requirements_api.txt
```

## Project Structure

```
.whisper-subs/
├── model.py                 # Segment dataclass, TranscriptionAdapter ABC, adapter registry, CLI parsing
├── transcribe.py            # Core transcription engine + adapter dispatch
├── whisper_subs.py          # YouTube/file transcription CLI
├── adapters/                # Transcription adapter implementations
│   ├── __init__.py
│   ├── faster_whisper_adapter.py   # Default local backend (CTranslate2)
│   ├── whispercpp_adapter.py       # whisper.cpp subprocess
│   ├── whisperx_adapter.py         # WhisperX (alignment + diarization)
│   ├── whisperturbo_adapter.py     # Whisper Large V3 Turbo (transformers)
│   ├── moonshine_adapter.py        # Moonshine edge ASR
│   ├── voxtral_adapter.py          # Mistral Voxtral multimodal
│   ├── vibevoice_adapter.py        # VibeVoice (transformers)
│   ├── groq_adapter.py             # Groq Cloud API
│   ├── deepgram_adapter.py         # Deepgram API
│   ├── chirp_adapter.py            # Google Cloud Speech-to-Text
│   ├── huggingface_adapter.py      # HuggingFace Inference API
│   ├── canary_adapter.py           # NVIDIA NeMo Canary
│   └── parakeet_adapter.py         # NVIDIA NeMo Parakeet
├── ui/                      # GUI applications
│   ├── __init__.py
│   ├── models.py            # Shared provider-grouped model list for GUIs
│ ├── pyqt_app.py # PyQt6 file selector GUI
│   ├── gtk_app.py           # GTK4 file selector GUI
│   └── tk_app.py            # tkinter file selector GUI
├── fastwhisper.py           # Backward-compat stub → ui.pyqt_app
├── whispergui.py            # Backward-compat stub → ui.gtk_app
├── wx.py                    # Backward-compat stub → ui.tk_app
├── whisper_model_chooser.py # VRAM-based model selection (local only)
├── transcription_service.py # Flask transcription API
├── livestream_transcriber.py# Live stream transcription
├── twitch_vod.py            # Twitch VOD downloader
├── tests/                   # Test suite
│   ├── run_tests.py         # Comprehensive test runner
│   ├── test_adapter_registry.py  # Adapter registry unit tests
│   ├── test_transcribe.py   # Single-model transcription test
│   ├── generate_test_audio.py # Generate test WAV files
│   └── fixtures/            # Test audio files
├── scripts/                 # Docker/build scripts
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements_api.txt
└── requirements_gui.txt
```

## Architecture

### Adapter + Strategy Pattern

All transcription backends implement `TranscriptionAdapter`:

```python
class TranscriptionAdapter(ABC):
    @abstractmethod
    def transcribe(self, audio_file, model, language=None, write=print, temperature=0.0, **kwargs) -> Tuple[List[Segment], Any]: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def get_model_names(self) -> List[str]: ...

    @property
    def prefix(self) -> str: ...      # e.g. "groq", "whispercpp"

    @property
    def display_name(self) -> str: ... # e.g. "Groq API", "whisper.cpp"
```

`TranscriptionContext` resolves model names and dispatches to the correct adapter:

```python
ctx = TranscriptionContext()

# Prefixed → routes to specific adapter
adapter, model = ctx.resolve("groq:whisper-large-v3")  # → (GroqAdapter, "whisper-large-v3")

# Bare name → default adapter (FasterWhisperAdapter)
adapter, model = ctx.resolve("large-v3")               # → (FasterWhisperAdapter, "large-v3")

# Transcribe through context (auto-dispatches)
segments, info = ctx.transcribe(audio_file="audio.wav", model_name="groq:whisper-large-v3")
```

### Auto-Discovery

Adapters are registered via the `@register_adapter` class decorator and auto-imported from the `adapters/` package at module load. Only adapters whose `is_available()` returns `True` are included in the active adapter map.

### Backward Compatibility

- Bare model names (no prefix) route to `FasterWhisperAdapter` — existing scripts and CLI usage work unchanged
- `fastwhisper.py`, `whispergui.py`, `wx.py` are now stubs that re-export from `ui/` — `python fastwhisper.py` still works
- `transcription_service.py` and `livestream_transcriber.py` are unaffected

## GUI Applications

Three GUI frontends with provider-grouped model dropdowns:

```bash
# PyQt6 (recommended)
python fastwhisper.py

# GTK4
python whispergui.py

# tkinter (fallback, no extra deps)
python wx.py
```

Model dropdowns show separator headers like `── Groq ──`, `── Deepgram ──` to organize models by provider.

## API Server

```bash
pip install -r requirements_api.txt
python start_api.py --host 0.0.0.0 --port 8000
```

API docs at http://localhost:8000/docs

## Testing

```bash
# Run all unit tests (no API keys or audio needed)
python tests/run_tests.py

# List available adapters and their status
python tests/run_tests.py --list-adapters

# Test transcription with an audio file (all available adapters)
python tests/run_tests.py --audio path/to/audio.wav

# Test a specific model
python tests/run_tests.py --audio path/to/audio.wav --model groq:whisper-large-v3
python tests/run_tests.py --audio path/to/audio.wav --model large-v3

# Test with a specific language
python tests/run_tests.py --audio path/to/audio.wav --model deepgram:nova-2 --lang en

# Generate test audio files (requires ffmpeg)
python tests/run_tests.py --generate-audio

# Run adapter registry unit tests only
python tests/test_adapter_registry.py

# Test a single model directly
python tests/test_transcribe.py audio.wav groq:whisper-large-v3
python tests/test_transcribe.py audio.wav large-v3
python tests/test_transcribe.py audio.wav whispercpp:base --lang en
```

## Docker

```bash
make build
make start
make exec bash
make stop
```

## Development

### Adding a new adapter

1. Create `adapters/your_adapter.py`:

```python
from model import Segment, TranscriptionAdapter, register_adapter

@register_adapter
class YourAdapter(TranscriptionAdapter):
    @property
    def prefix(self) -> str:
        return "yourprefix"

    @property
    def display_name(self) -> str:
        return "Your Adapter"

    def is_available(self) -> bool:
        try:
            import your_dependency
            return True
        except ImportError:
            return bool(os.environ.get('YOUR_API_KEY'))

    def get_model_names(self) -> list:
        return ["model-a", "model-b"]

    def transcribe(self, audio_file, model, language=None, write=print, temperature=0.0, **kwargs):
        # ... your implementation ...
        return segments, info  # List[Segment], info object
```

2. Add model names to `ADAPTER_MODEL_NAMES` in `model.py`:

```python
"yourprefix:model-a",
"yourprefix:model-b",
```

3. The adapter is auto-discovered at import time. No other registration needed.

## License

See repository for license information.
