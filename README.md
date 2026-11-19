# .whisper-subs

Transcribe YouTube videos, local audio/video files, and live streams to subtitles using multiple ASR backends. Supports 13 transcription adapters (local + cloud) through a unified `provider:model` interface.

## Features

- **Multi-backend transcription**: 13 adapters — local (faster-whisper, whisper.cpp, WhisperX, Moonshine, Voxtral, VibeVoice, Whisper Turbo) and cloud (Groq, Deepgram, Google Chirp, HuggingFace, NVIDIA Canary/Parakeet)
- **Unified model syntax**: Use `provider:model` (e.g. `groq:whisper-large-v3`) or bare names for local models
- **distil models**: `distil-whisper/distil-medium.en` and friends work from the local path (HF repo ids are translated to what faster-whisper accepts)
- **YouTube captions**: `--fetch-caps` / `--no-fetch-caps` / `--fetch-auto` / `--fetch-langs` use existing human-made captions instead of transcribing (automatic captions are opt-in)
- **Pluggable VAD**: `--vad-engine silero|pyannote|webrtc|custom`, plus your own detector via `WHISPERSUBS_VAD_CUSTOM` — see [Custom VAD](#custom-vad)
- **NeMo diarization**: `--diarize-engine nemo` (MSDD/Sortformer) alongside pyannote
- **YouTube discovery & feed**: find channels, follow them, and get a ranked feed of their new videos — no accounts, no tracking, all on-device
- **YouTube transcription**: Download and transcribe videos/channels via `yt-dlp`
- **MKV/file selector**: GUI for selecting and transcribing local files
- **Live captioner**: Real-time captioning with PyQt6/GTK4/tkinter interfaces
- **API server**: FastAPI/Flask transcription endpoints
- **Auto-adapter discovery**: Only adapters with installed dependencies appear as available
- **Provider-grouped model lists**: GUI dropdowns organized by provider with separator headers
- **Segment preview**: `--show` prints each subtitle line as it is written
- **Force-mode backups**: `-f`/`-r` keep the previous subtitle as `name.2.srt`, `name.3.srt`, ... instead of overwriting
- **Subtitle metadata**: every run writes `name.metadata.json` with channel, stats, thumbnails, duration, and the build (version + commit) that produced it
- **Terminal UI** (`tui/`): browse and search the subtitle library, full-text cue search, job history, YouTube search + transcription, and mpv playback — see [tui/README.md](tui/README.md)

## Quick Start

Transcribe one video, find channels to follow, and look at the feed:

```bash
# Transcribe (the usual path)
wsub large-v3 --url https://www.youtube.com/watch?v=L3MFjZXyMcI

# Find a channel, follow it, then see its newest videos ranked
wsub --yt-search-channels "Kurzgesagt"
wsub --yt-subscribe kurzgesagt
wsub --yt-feed

# Channels you follow
wsub --yt-subscriptions
wsub --yt-unsubscribe https://www.youtube.com/@kurzgesagt
```

`--yt-*` commands are metadata-only: they never download or transcribe
media. Subscriptions live in `~/.config/WhisperSubs/subscriptions.json` and
the feed is ranked locally (recency + watches + watchable length + live),
with the reason for each entry shown so the ranking is inspectable.

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
| **sherpa-onnx** | `sherpa:` | `parakeet-tdt-0.6b-v2`, `parakeet-tdt-0.6b-v3`, `nemotron-streaming-en-0.6b` | Local | `sherpa-onnx` pip package |

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
python whisper_subs.py whisper.cpp audio.wav              # provider alias -> whispercpp:base
python whisper_subs.py whisperturbo:whisper-large-v3-turbo audio.wav  # needs torch+transformers
python whisper_subs.py moonshine:moonshine-tiny audio.wav # needs moonshine or transformers
python whisper_subs.py voxtral:voxtral-mini audio.wav     # needs torch+transformers
python whisper_subs.py vibevoice:vibevoice-1b audio.wav   # needs torch+transformers
python whisper_subs.py whisperx:large-v3 audio.wav        # needs whisperx package
python whisper_subs.py canary:canary-1b-flash audio.wav   # needs nemo package
python whisper_subs.py parakeet:parakeet-ctc-1.1b audio.wav # needs nemo package

# Parakeet TDT via ONNX Runtime — same encoder, far lighter install
python whisper_subs.py sherpa:parakeet-tdt-0.6b-v3 audio.wav

# Cache-aware streaming encoder, segment decoded at each endpoint
python whisper_subs.py sherpa:nemotron-streaming-en-0.6b audio.wav --gpu
```

### Output files

Each transcription writes next to the media:

- `name.srt` — the subtitle (a symlink to `name.unfinished.srt` while transcribing, so players see progress live)
- `name.metadata.json` — one file per subtitle, always via `app_meta.write_metadata()`

The metadata contains transcription facts (`model`, `language`, `segments_count`, `duration_seconds`, settings) merged with source facts:

| Field | Source |
|---|---|
| `channel_name`, `channel_id`, `channel_url` | yt-dlp video info (`local_files` for local files) |
| `thumbnail_url`, `channel_thumbnail_url` | best yt-dlp thumbnail; channel avatar from the channel page `og:image` |
| `views`, `likes`, `dislikes`, `comments_count` | yt-dlp stats (`None` when not published) |
| `upload_timestamp` | yt-dlp `timestamp` / `release_timestamp` / `upload_date` |
| `has_human_subs`, `has_automatic_subs` | yt-dlp `subtitles` / `automatic_captions` |
| `transcription_timestamp`, `version`, `commit_hash` | the build that produced the file |

```bash
# Print each new subtitle line as it is written
python whisper_subs.py base.en video.mp4 --show

# Force re-transcription; the old subtitle is kept:
#   name.srt -> name.2.srt (then .3.srt, ...), metadata moves with it
python whisper_subs.py base.en video.mp4 -r

# Play with the existing subtitle; one mpv window per video
python whisper_subs.py 2 --mpv https://youtu.be/VIDEOID

# Queue videos in an mpv playlist; each is appended as it finishes
python whisper_subs.py 2 --mpv --playlist https://youtu.be/VIDEOID

# Queue a channel's finished subtitles, writing the playlist where you want
python whisper_subs.py 2 --mpv --playlist-channel --playlist-file ~/queue.m3u
```

### sherpa-onnx models

`sherpa:` runs NVIDIA Parakeet and Nemotron encoders on ONNX Runtime instead of
NeMo. Same weights, much smaller install (`pip install sherpa-onnx`, prebuilt
wheels — no `nemo-toolkit`/`hydra`/`fiddle`, no gated HuggingFace login).

Models are downloaded on first use into
`$WHISPERSUBS_SHERPA_DIR`, else `~/.cache/whispersubs/sherpa-onnx`. Every
artifact has a pinned SHA-256 and exact byte count; downloads are staged,
verified, then promoted by an atomic rename, so an interrupted or corrupt
fetch can never look like an installed model.

The loaded recognizer stays resident for the whole run, so a 650 MB encoder is
loaded once instead of per file:

| Model | Languages | Path |
|---|---|---|
| `sherpa:parakeet-tdt-0.6b-v2` | en | offline, per-token timestamps |
| `sherpa:parakeet-tdt-0.6b-v3` | 25 European | offline, per-token timestamps |
| `sherpa:nemotron-streaming-en-0.6b` | en | streaming, cue per endpoint |

`--gpu` selects the CUDA execution provider; thread count follows
`--cpu-threads`.

### Choosing an audio track

A file with several audio streams (`JP dub`, `EN original`, commentary tracks)
uses the first one unless told otherwise, and the log says which track was
picked and how many there were, so a mistaken language is visible rather than
silent:

```bash
# 0-based audio-stream ordinal, as reported by ffprobe
python whisper_subs.py large --file ./anm/Show --audio-track 1
```

`-lang`/`--language` selects the *target* language; with a model that can be
ordered to a language (e.g. `whisperx:`) it is passed through to the decoder,
so a Japanese lead-in is transcribed as Japanese rather than degrading every
later window.

Long media is decoded in **overlapping windows**. sherpa's offline encoder
cannot take unbounded input — past a few minutes ONNX Runtime aborts with
`Attempting to broadcast an axis by a dimension other than 1`. Audio is
therefore cut into 30 s windows with 2 s of shared context.

A token is kept unless an *earlier* window already transcribed audio reaching
its start time. Dropping each window's whole leading overlap instead would
duplicate most words at a cut, and would silently lose any word the encoder
failed to emit because it straddled the previous window's end.

Audio is held in a packed `array('f')` rather than a list of Python floats: a
13-minute video is ~12M samples, which costs ~392 MB as a list against 49 MB
packed. The window slice is converted to a list only for the native call.

Tune with:

| Variable | Default | Effect |
|---|---|---|
| `WHISPERSUBS_SHERPA_WINDOW` | `30` | seconds per decode window |
| `WHISPERSUBS_SHERPA_OVERLAP` | `2` | seconds of shared context between windows |
| `WHISPERSUBS_SHERPA_DIR` | `~/.cache/whispersubs/sherpa-onnx` | model cache |

### Comparing finished subtitles

`--compare` scores the subtitle files you already have — hallucination and
corruption checks, mid-word split heuristic, zero-length and overlapping cues,
leftover in-progress metadata blocks — and suggests a winner:

```bash
python whisper_subs.py --compare a.srt b.srt
python whisper_subs.py --compare a.srt b.srt --choose 1   # keep b.srt
```

`--choose N` moves the losing files aside as `<name>.2.srt`, `<name>.3.srt`,
the same numbering `--force-retry` uses, leaving the winner under its original
name.

### Player and existing subtitles

`--mpv` (also `--run`/`-m` and `--play`) opens one mpv window per video. The
window is locked per media source, so model fallback, loop retry and two-pass
runs do not reopen it.

When a task is already processed, the subtitle on disk is found by video id and
validated before it is trusted: it must parse as real SRT and hold at least two
entries. A usable subtitle is reported with its path and wrapper scripts, and
played when a player flag was passed. An empty or near-empty one is rejected —
the completion marker is cleared and the video is re-transcribed.

Playlist flags:

| Flag | Effect |
|---|---|
| `--playlist` | Queue this job's videos, appending each as it finishes |
| `--playlist-channel` | Queue the channel's finished subtitles |
| `--playlist-file FILE` | Write the m3u to `FILE` (default `<output>/playlist.m3u`) |

Note: `-f/--force` bypasses the audio cache and human-subtitle checks; the "already processed" history is only overridden by `-r/--force-retry`, and the backup runs for either flag.

### Environment Variables

| Variable | Adapter | How to Get |
|---|---|---|
| `GROQ_API_KEY` | Groq | [console.groq.com](https://console.groq.com/keys) |
| `DEEPGRAM_API_KEY` | Deepgram | [console.deepgram.com](https://console.deepgram.com/) |
| `HF_API_KEY` | HuggingFace | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `HF_TOKEN` | WhisperX (diarization) | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Chirp | [cloud.google.com/iam](https://cloud.google.com/iam/docs/creating-managing-service-account-keys) |
| `WHISPERSUBS_VAD` | Adapter models | See [Custom VAD](#custom-vad) |
| `WHISPERSUBS_VAD_CUSTOM` | Adapter models | See [Custom VAD](#custom-vad) |
| `WHISPERSUBS_VAD_PARAMS` | Adapter models | See [Custom VAD](#custom-vad) |

Set them in your shell or in the `.env` file (already gitignored):

```bash
# .env
GROQ_API_KEY=gsk_...
DEEPGRAM_API_KEY=...
HF_API_KEY=hf_...
GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-sa.json
```

### Custom VAD

Adapter models (`whisperx:…`) trim silence with a VAD before transcribing.
The engine is pluggable in `vad.py`: `silero` (default, weights ship with
WhisperX), `pyannote` (WhisperX's own, needs `HF_TOKEN`), `webrtc`, or
`custom` pointing at any importable callable.

```bash
# Pick an engine
whisper_subs.py whisperx:large-v3 clip.mp4 --vad-engine webrtc

# Point at your own detector — it must return [(start, end), ...] in seconds
export WHISPERSUBS_VAD_CUSTOM=mypkg.vads:detect
whisper_subs.py whisperx:large-v3 clip.mp4 --vad-engine custom

# Pass engine parameters (repeat the flag for more keys)
whisper_subs.py whisperx:large-v3 clip.mp4 --vad-param threshold=0.35
```

Notes:

- A missing dependency or unknown engine degrades to *no VAD* and keeps
  transcribing — VAD is an optimization, never a hard requirement.
- A custom callable takes the audio path: `detect(path, **params) -> regions`.
- Regions are sorted and coalesced before use, so overlapping or
  out-of-order output is accepted.

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
#
# The ggml model file is separate from the binary. Download it from
# https://huggingface.co/ggerganov/whisper.cpp (e.g. ggml-base.bin) and put
# it where the adapter looks, or point the adapter at its directory:
#   export WHISPERCPP_MODELS_DIR=/path/to/models
# Searched by default: ~/.cache/whisper.cpp, ~/.cache/whisper,
# ~/.local/share/whisper.cpp, ~/models/whisper.cpp, ~/models,
# /usr/share/whisper.cpp/models, /usr/share/whisper-cpp,
# /opt/whisper.cpp/models, ./models

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
│   └── fixtures/            # Test audio (test_sine.wav is committed; regenerate
│                            # speech audio with tests/generate_test_audio.py)
├── tui/                     # Rust terminal UI (subtitle search, jobs, YouTube, mpv playback)
│   ├── run.sh               # Launcher: builds then starts
│   ├── src/
│   │   ├── index.rs         # SQLite index + FTS5 cue search + metadata parsing
│   │   ├── app.rs           # Tabs, event loop, key handling
│   │   ├── youtube.rs       # yt-dlp search + transcription subprocess
│   │   ├── player.rs        # mpv JSON IPC
│   │   ├── srt.rs           # Subtitle parsing
│   │   └── config.rs        # Paths and tui.toml
│   └── README.md            # TUI keys, config, and media discovery
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

### Caption endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/captions?url=…` | List caption tracks (human + automatic) without downloading anything |
| `GET /api/v1/captions?url=…&dest=name.srt` | Write the best track to `OUTPUT_DIR/captions/` and return its URL |
| `GET /api/v1/search/history` | This account's recent searches |
| `GET /api/v1/youtube/channels/search?q=…` | Find YouTube channels by name or @handle |
| `GET /api/v1/youtube/channel?channel=…` | Resolve a typed channel reference to a channel |
| `GET /api/v1/youtube/channel/videos?channel=…` | A channel's video list (cached 30 min; `?refresh=true`) |
| `GET/POST/DELETE /api/v1/youtube/subscriptions` | List / follow / unfollow channels |
| `GET /api/v1/youtube/feed` | Ranked videos from followed channels (local algorithm) |
| `POST /api/v1/search/history?q=…` | Record a search |

Human-made captions are preferred; automatic ones require
`allow_automatic=true`. Both the CLI and the Android app use these, so a
link that already has human captions never gets transcribed.

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
