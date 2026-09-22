# .whisper-subs — Agent Instructions

## Quick Commands

```bash
# Install base (local faster-whisper)
uv pip install -r requirements.txt

# Install API deps
uv pip install -r requirements_api.txt

# Install GUI deps (PyQt5)
uv pip install -r requirements_gui.txt

# Run transcription (CLI)
python whisper_subs.py large-v3 video.mp4
python whisper_subs.py groq:whisper-large-v3 video.mp4   # cloud, needs GROQ_API_KEY

# List all models
python -m model --list-models

# Run unit tests (no API keys/audio needed)
python tests/run_tests.py

# Run transcription tests with audio file
python tests/run_tests.py --audio path/to/audio.wav
python tests/run_tests.py --audio path/to/audio.wav --model groq:whisper-large-v3
python tests/run_tests.py --list-adapters

# API server
pip install -r requirements_api.txt
python start_api.py --host 0.0.0.0 --port 8000
# API docs: http://localhost:8000/docs

# Docker
make build && make start
make exec bash
make stop
```

## Architecture — Adapter + Strategy Pattern

All transcription backends implement `TranscriptionAdapter` (in `model.py`):

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

`TranscriptionContext` resolves `provider:model` and dispatches:

```python
ctx = TranscriptionContext()
adapter, model = ctx.resolve("groq:whisper-large-v3")  # → (GroqAdapter, "whisper-large-v3")
adapter, model = ctx.resolve("large-v3")                # → (FasterWhisperAdapter, "large-v3")
segments, info = ctx.transcribe(audio_file="audio.wav", model_name="groq:whisper-large-v3")
```

- Bare model names (no prefix) route to `FasterWhisperAdapter` (default local backend)
- Prefixed names (`groq:`, `deepgram:`, `whispercpp:`, etc.) route to their adapter
- Adapters auto-discovered via `@register_adapter` decorator on import from `adapters/`
- Only adapters with `is_available() == True` are in the active map

## Key Files

| File | Purpose |
|------|---------|
| `model.py` | Segment dataclass, TranscriptionAdapter ABC, registry, TranscriptionContext, CLI arg parsing, model lists |
| `transcribe.py` | Core transcription engine, adapter dispatch, SRT writing, loop/hallucination detection |
| `whisper_subs.py` | YouTube/Twitch/local file downloader + job management + transcription orchestration |
| `adapters/*.py` | 13 adapter implementations (faster-whisper, whisper.cpp, WhisperX, Moonshine, Voxtral, VibeVoice, Whisper Turbo, Groq, Deepgram, Google Chirp, HuggingFace, NVIDIA Canary, NVIDIA Parakeet) |
| `ui/` | PyQt5, GTK4, tkinter GUIs with provider-grouped model dropdowns |
| `api/server.py` | FastAPI transcription endpoints |
| `tests/run_tests.py` | Comprehensive test runner (unit + transcription) |

## Adapter Reference (from README)

| Adapter | Prefix | Example Models | Type | Dependency |
|---------|--------|---------------|------|------------|
| Faster Whisper | *(bare)* | `tiny`, `base`, `small`, `medium`, `large`, `large-v2`, `large-v3`, `*.en`, `distil-*` | Local | `faster-whisper` |
| whisper.cpp | `whispercpp:` | `base`, `small`, `medium`, `large-v3`, `tiny`, `large-v2` | Local | `whisper-cpp` binary in PATH |
| WhisperX | `whisperx:` | `large-v3`, `medium`, `base`, `small`, `tiny`, `*.en` | Local | `whisperx` pip package |
| Whisper Turbo | `whisperturbo:` | `whisper-large-v3-turbo` | Local | `torch` + `transformers` |
| Moonshine | `moonshine:` | `moonshine/base`, `moonshine/tiny` | Local | `moonshine` or `transformers` |
| Voxtral | `voxtral:` | `voxtral-mini` | Local | `torch` + `transformers` |
| VibeVoice | `vibevoice:` | `vibevoice-1b` | Local | `torch` + `transformers` |
| Groq | `groq:` | `whisper-large-v3`, `whisper-large-v3-turbo`, `distil-whisper-large-v3-en` | Cloud | `GROQ_API_KEY` |
| Deepgram | `deepgram:` | `nova-3`, `nova-2`, `whisper-turbo`, `nova-2-phonecall` | Cloud | `DEEPGRAM_API_KEY` |
| Google Chirp | `chirp:` | `chirp_2`, `chirp`, `long`, `latest_short`, `latest_long` | Cloud | `GOOGLE_APPLICATION_CREDENTIALS` |
| HuggingFace | `hf:` | `openai/whisper-large-v3`, `nvidia/parakeet-ctc-1.1b-asr` | Cloud | `HF_API_KEY` |
| NVIDIA Canary | `canary:` | `canary-1b-flash`, `canary-1b` | Local | `nemo_toolkit` |
| NVIDIA Parakeet | `parakeet:` | `parakeet-ctc-1.1b`, `parakeet-rnnt-1.1b`, `parakeet-ctc-0.6b`, `parakeet-rnnt-0.6b` | Local | `nemo_toolkit` |

## Environment Variables (set in `.env`, gitignored)

```
GROQ_API_KEY=gsk_...
DEEPGRAM_API_KEY=...
HF_API_KEY=hf_...
HF_TOKEN=...            # WhisperX diarization
GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-sa.json
```

## Testing Notes

- Unit tests run without API keys or audio files (`python tests/run_tests.py`)
- Transcription tests require audio file + available adapter (API key or local deps)
- `tests/run_tests.py --list-adapters` shows which adapters are available
- `tests/run_tests.py --generate-audio` creates test WAV (needs ffmpeg)

## Adding a New Adapter

1. Create `adapters/your_adapter.py` with `@register_adapter` class
2. Implement `prefix`, `display_name`, `is_available()`, `get_model_names()`, `transcribe()`
3. Add model names to `ADAPTER_MODEL_NAMES` in `model.py`
4. Auto-discovered on import — no other registration needed

## Gotchas

- Python 3.14 (`.python-version`)
- `fastwhisper.py`, `whispergui.py`, `wx.py` are backward-compat stubs → `ui/` module
- Local transcription uses subprocess-based pipeline with resume/loop detection
- Cloud adapters convert audio to WAV/MP3 via ffmpeg before API call
- YouTube downloads require `cookiesfrombrowser` (yt-dlp requirement)
- Model names with colons become underscores in filenames (`groq:whisper-large-v3` → `groq_whisper-large-v3`)

## Dependency Installation

When a dependency installation command fails:

* Do not immediately repeat the same command.
* Read the error and identify the package/environment manager responsible.
* Do not bypass environment protections merely to make the command succeed.
* Check the repository's dependency configuration and existing environments.
* If an alternative installation method is available, use it.
* Never repeat an identical failed command more than once without new information.

For Python projects, prefer an existing `uv`/virtualenv/project environment over system Python.

A PEP 668 "externally managed environment" error must trigger environment discovery, not `--break-system-packages`.

## Python Environment and Dependencies

Never install Python packages into the system Python environment.

Never use:

* `pip install ... --break-system-packages`
* `pip3 install ... --break-system-packages`
* `sudo pip install ...`
* `sudo pip3 install ...`

When a Python dependency is missing:

1. Check for an existing project virtual environment:

   * `.venv/`
   * `venv/`
   * `env/`

2. Check whether the project uses `uv`:

   * `uv.lock`
   * `pyproject.toml`
   * existing `uv` commands/configuration

3. Prefer the project's existing environment/package manager:

   * `uv run <command>`
   * `.venv/bin/python -m <module>`
   * `uv add <dependency>` when the dependency belongs in the project

4. Before installing anything, inspect `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, or equivalent dependency files.

5. Do not install a dependency merely because the system Python does not have it. The relevant question is whether the project's configured Python environment has it.

6. If no project environment exists, determine the project's dependency-management convention before creating or modifying an environment.

7. If dependency installation is required, modify the project's dependency configuration when appropriate rather than performing an ad-hoc global installation.

PEP 668 errors are not permission errors to bypass. Treat them as an instruction to use an isolated/project environment.

Once a valid project environment is identified, run tests through that environment.


## Mandatory Git Safety

NEVER use destructive commands on modified files without first preserving the
working-tree state.

Forbidden without explicit user approval:

- git checkout -- <file>
- git restore <file>
- git reset --hard
- git clean -fd
- git clean -fdx
- git stash --include-untracked
- rm -rf on project source/build directories
- destructive sed/perl/python rewrites

Before modifying a file:

1. Check `git status --short`.
2. If the file has uncommitted modifications, inspect the diff first.
3. Never assume uncommitted changes are yours.
4. Never discard existing modifications merely to recover from an edit.
5. If an edit goes wrong, restore ONLY the lines changed by the agent.
6. Prefer small, context-based edits over line-number-based `sed`.
7. After every edit, immediately inspect the affected region and `git diff`.
8. If the file becomes unexpectedly corrupted, STOP. Do not attempt another
   destructive command. Report the corruption and recover conservatively.

Before claiming a fix works:

- build/test it;
- inspect the actual exit code;
- report failures explicitly;
- never say "fixed", "passing", or "complete" based solely on intended changes.

### Uncommitted changes are user data

Treat every pre-existing uncommitted modification as valuable user work.
Do not revert, overwrite, reset, stash, or delete it unless explicitly
authorized.
