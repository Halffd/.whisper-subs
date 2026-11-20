# WhisperSubs Android

Android companion app for [whisper-subs](https://github.com/Halffd/.whisper-subs):
on-device transcription through a whisper.cpp JNI layer, plus browsing
and playback of everything a whisper-subs server has already
transcribed.

## Screens

| Tab | What it does |
|-----|--------------|
| **Home** | Server connection status, quick entry points (Channels / Live / Library / Local / Search / YouTube), and a setup banner when no server is configured |
| **Search** | Four scopes — **Local** device subtitles, **Subtitles**, **YouTube**, **Twitch** — plus a link fast path: paste a media URL and pick from its caption languages (no transcription needed), or transcribe instead |
| **YouTube** | Flow-style discovery: **Discover** (search channels by name or @handle), **Subscriptions** (channels you follow, with follow/unfollow inline), and **Feed** (videos from followed channels, ranked by the server — recency, watches, watchable length, live — with each item's reasons shown). Tapping a feed video hands its URL to Search's link path, which fetches captions or queues a transcription |
| **History** | Every search recorded on this server account; tap a row to re-run it. Link rows are marked, since they go through the caption/download path |
| **Library** | Everything the server has transcribed (SRT + media), with local transcriptions merged in; works offline from the last successful load |
| **Live** | Live-stream transcription with subtitles updating as the stream grows |
| **Local** | On-device transcription: pick an audio/video file, **paste a direct media URL** (`.m3u8`, `.mp3`, `.mp4` — fetched on the device, no server needed), or use the microphone; download a whisper model and transcribe with whisper.cpp |
| **Settings** | Server URL + API key, playback options |

The player streams server media with the SRT side-loaded, including
picture-in-picture support.

### Player layout (Flow-style)

The player adapts to the window, following Flow's layout pattern:

| Window | Layout |
|---|---|
| Compact (phone portrait, < 840dp) | Player on top, info pane below it — one scroll |
| Expanded (tablet / foldable / landscape, ≥ 840dp) | Player pinned left, 380dp pane in its own scroll column right |

The pane shows title and uploader above a details card (duration,
resolution, format, cue count), then a transcript preview — the opening
subtitle cues with timestamps — the now-playing cue, the SRT path, and the
source URL (opens in the browser). There are no chapter or comment APIs in
this app, so those sections are omitted entirely rather than shown empty.
Fullscreen and picture-in-picture stay full-bleed with no pane.

## Captions vs transcription

YouTube videos that carry human-uploaded captions do not need to be
transcribed. Pasting a link into Search lists the available caption
languages first — the user picks one, and it plays immediately with the
original SRT. YouTube offers several *formats* per language (`srt`, `vtt`,
`json3`, `ttml`, `srv*`); the app shows one row per language and lets the
server convert whichever is cheapest, so the choice is by language, not
format. Automatic captions are behind a toggle, off by default, matching
the CLI's `--fetch-auto`.

Only when no human track exists — or the user picks **Transcribe instead** —
does the link fall through to the download queue and transcription.

## Deep links

The activity answers `whispersubs://` links (declared in the manifest with
a `BROWSABLE` filter, so they also work from a browser or QR scan):

| Link | Opens |
|------|-------|
| `whispersubs://search?query=…` | Search screen, query pre-filled and run |
| `whispersubs://history` | Search history |
| `whispersubs://connect`, `/home`, `/live`, `/local`, `/library`, `/channels`, `/settings` | That screen |

Sharing a `text/plain` media URL from any app (YouTube, Twitch, direct
`.m3u8`/`.mp3`/`.mp4` links) routes into the search screen's link path —
this includes YouTube's own share button, which sends `youtu.be` links.

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
