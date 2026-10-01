# whisper-subs-tui

A terminal UI for the subtitle library that `whisper_subs.py` writes, plus
YouTube search and transcription without leaving the terminal.

## Build and run

```bash
./run.sh
```

`run.sh` builds on first use and then launches the binary from the repository
root, so relative paths resolve the same way every run.

To build and run explicitly:

```bash
cd tui
cargo build
./target/debug/whisper-subs-tui
```

Dependencies: a Rust toolchain, `mpv`, and `yt-dlp` for the YouTube tab. The
Python side (`whisper_subs.py`, faster-whisper) is needed to transcribe.

## Tabs

| Tab | What it does |
|-----|--------------|
| `Library` | Every indexed subtitle, with metadata. Search titles, channels, models, URLs, or statistics (`1.5M`, `1500`, `12:30`). |
| `Subtitles` | Full-text search inside subtitle text, with the matching cue and its timings. |
| `Jobs` | History from `jobs.json`, including per-task progress. |
| `YouTube` | `yt-dlp` search, then transcribe a result straight into the library. |

## Keys

| Key | Action |
|-----|--------|
| `tab` / `shift-tab` | Next / previous tab |
| `/` | Start a search |
| `enter` | Open the selected row's details |
| `j` `k`, arrows | Move the selection |
| `p` | Play the selected subtitle in mpv (from its cue, when in the Subtitles tab) |
| `space` | Pause / resume |
| `[` `]` | Seek back / forward 10s |
| `s` | Stop playback |
| `r` | Rescan the library and reindex |
| `d` | Details panel |
| `b` | Results panel |
| `q` | Quit |

Playback opens an mpv window next to the terminal; mpv cannot draw inside a
terminal. The subtitle is attached, so seeking into a cue shows it immediately.

## Searching by statistics

The Library tab accepts a number in place of text and matches it against views,
likes, comments, and duration:

| Query | Matches |
|-------|---------|
| `1.5M`, `1500000`, `1,500,000` | 1,500,000 views |
| `4200` | 4,200 likes |
| `12:30`, `750` | a 12:30 (750 second) video |

Anything that is not a number is treated as text, so ordinary searches are
unaffected.

## Configuration

Defaults live in `src/config.rs` and can be overridden in
`~/.config/WhisperSubs/tui.toml`:

```toml
library_dir = "~/Documents/Youtube-Subs"
cache_dir = "~/.cache/whisper-subs"
mpv_socket = "/tmp/whisper-subs-tui-mpvsocket"
yt_dlp = "yt-dlp"
whisper_subs = "/path/to/whisper_subs.py"
python = "python3"
models = ["tiny.en", "base.en", "medium.en"]
jobs_file = "~/.config/WhisperSubs/jobs.json"
```

The index is a SQLite database at `~/.cache/whisper-subs/tui-index.sqlite`. It is
derived data: deleting it costs a rescan, nothing else.

## Media discovery

The TUI links each subtitle to the media it describes, trying the metadata's
`source_file`, then the audio cache in `~/.cache/whisper-subs/audio`, then
sibling files with the model and force-mode backup suffixes removed. Subtitles
with no media found are still listed and searchable, but cannot be played.

## Tests

```bash
cd tui
cargo test
```

The suite needs no API keys and no media files: `yt-dlp` and `whisper_subs.py`
are replaced by generated scripts, and the mpv test synthesises a silent WAV. The
mpv test is skipped when mpv is not installed.