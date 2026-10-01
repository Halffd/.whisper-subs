#!/usr/bin/env bash
# Launch the whisper-subs TUI, building it first if needed.
#
# Keeps the working directory at the repository root so relative paths in
# tui.toml and the resolved whisper_subs.py path behave the same every run.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here/tui"

if [[ ! -x target/debug/whisper-subs-tui ]]; then
    echo "building whisper-subs-tui (first run)..." >&2
    cargo build
fi

exec ./target/debug/whisper-subs-tui "$@"