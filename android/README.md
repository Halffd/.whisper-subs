# WhisperSubs Android

On-device subtitles for videos with [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — offline transcription, live captioning, and a local library that talks to a [whisper-subs](https://github.com/Halffd/.whisper-subs) API server when available.

## Build

```bash
bash fetch_whisper.sh   # clone whisper.cpp JNI sources (gitignored)
./gradlew assembleDebug
```

APK: `app/build/outputs/apk/debug/app-debug.apk`

Requires JDK 17 and an Android SDK (NDK 28.2.13676358, CMake 3.22.1 are
installed automatically by Gradle).

## CI

Every push builds the debug APK and uploads it as a workflow artifact.
Tagged pushes (`v*`) also publish a GitHub release with the APK.

[![android](https://github.com/Halffd/whispersubs-android/actions/workflows/android.yml/badge.svg)](https://github.com/Halffd/whispersubs-android/actions/workflows/android.yml)
