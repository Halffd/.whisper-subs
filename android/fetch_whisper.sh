#!/bin/bash
# Fetch whisper.cpp for Android JNI build
# Run from android/ directory

set -e

WHISPER_DIR="app/src/main/cpp/whisper.cpp"
WHISPER_REPO="https://github.com/ggerganov/whisper.cpp"
WHISPER_COMMIT="v1.7.4"  # Stable release

echo "Fetching whisper.cpp..."
if [ -d "$WHISPER_DIR" ]; then
    echo "whisper.cpp already exists, updating..."
    cd "$WHISPER_DIR"
    git fetch origin
    git checkout "$WHISPER_COMMIT"
else
    git clone --depth 1 --branch "$WHISPER_COMMIT" "$WHISPER_REPO" "$WHISPER_DIR"
fi

echo "whisper.cpp ready at $WHISPER_DIR"