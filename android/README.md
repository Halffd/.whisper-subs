# WhisperSubs Android

Android companion app for [whisper-subs](https://github.com/Halffd/.whisper-subs):
on-device transcription through a whisper.cpp JNI layer, plus browsing
and playback of everything a whisper-subs server has already
transcribed.

## Screens

| Tab | What it does |
|-----|--------------|
| **Home** | Server connection status and quick entry points |
| **Library** | Everything the server has transcribed (SRT + media), with local transcriptions merged in; works offline from the last successful load |
| **Live** | Live-stream transcription with subtitles updating as the stream grows |
| **Local** | On-device transcription: pick a media file, download a whisper model, transcribe with whisper.cpp, export SRT |
| **Settings** | Server URL + API key, playback options |

The player streams server media with the SRT side-loaded, including
picture-in-picture support.

## Server setup

The Library/Home/Live tabs talk to a running
[whisper-subs](https://github.com/Halffd/.whisper-subs) API server:

```bash
# on the machine running the server
uvicorn api.server:app --host 0.0.0.0 --port 8000
```

The server's auth config (`api/api_config.json`, created on first
boot) contains the default `admin` user and its API key — copy that
key into the app's Settings. Registration is disabled by default; to
enable it set `allow_registration: true` in the config and restart.

## Building

```bash
bash fetch_whisper.sh   # clone whisper.cpp JNI sources (gitignored)
./gradlew assembleDebug
```

APK: `app/build/outputs/apk/debug/app-debug.apk`

Requires JDK 17 and an Android SDK; NDK 28.2.13676358 and CMake 3.22.1
install automatically through Gradle.

### Signing

All debug builds are signed with the committed `app/debug.keystore`, so
newer builds install right over older ones. Do not replace it, or
users will have to uninstall first.

## Architecture

- **UI**: Jetpack Compose (Material 3), Navigation Compose
- **DI**: Hilt — singletons (`ApiClient`, `ServerConfig`,
  `LocalLibraryRepository`) are injected on `MainActivity` and handed
  to screens; view-models only wrap stateful flows
- **Native**: `app/src/main/cpp` — whisper.cpp via CMake, a thin JNI
  wrapper (`whisper_jni.cpp`) exposes init/transcribe/segments
- **Data**: Room for the local library, OkHttp/Ktor for the server
  API, Coil for thumbnails, Media3 (ExoPlayer) for playback

## CI

Every push builds the debug APK and uploads it as a workflow artifact.
`v*` tags publish a GitHub release with the APK.

[![android](https://github.com/Halffd/whispersubs-android/actions/workflows/android.yml/badge.svg)](https://github.com/Halffd/whispersubs-android/actions/workflows/android.yml)
