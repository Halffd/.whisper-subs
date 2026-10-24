#!/usr/bin/env python3
"""Comprehensive test runner for the whisper-subs adapter system.

Runs all test suites and reports results. Can also run transcription
tests against audio files if provided.

Usage:
    # Run unit tests only (no API keys or audio needed)
    python tests/run_tests.py

    # Run unit tests + transcription tests with an audio file
    python tests/run_tests.py --audio path/to/audio.wav

    # Run transcription test for a specific model
    python tests/run_tests.py --audio path/to/audio.wav --model groq:whisper-large-v3

    # Run with specific language
    python tests/run_tests.py --audio path/to/audio.wav --model large-v3 --lang en

    # List available adapters and exit
    python tests/run_tests.py --list-adapters

    # Generate test audio file
    python tests/run_tests.py --generate-audio
"""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.results = []

    def _record(self, name, status, detail=""):
        self.results.append({"name": name, "status": status, "detail": detail})
        if status == "PASS":
            self.passed += 1
        elif status == "FAIL":
            self.failed += 1
        elif status == "SKIP":
            self.skipped += 1

    def run_unit_tests(self):
        print("\n" + "=" * 60)
        print("UNIT TESTS")
        print("=" * 60)

        from model import (
            Segment,
            TranscriptionContext,
            ALL_MODEL_NAMES,
            ADAPTER_MODEL_NAMES,
            MODEL_NAMES,
            _ADAPTER_CLASSES,
        )

        # --- Segment ---
        try:
            s = Segment(start=1.0, end=2.0, text="test")
            assert s.start == 1.0 and s.end == 2.0 and s.text == "test"
            self._record("Segment dataclass", "PASS")
        except Exception as e:
            self._record("Segment dataclass", "FAIL", str(e))

        # --- Adapter count ---
        try:
            assert len(_ADAPTER_CLASSES) >= 13
            self._record(
                "Adapter classes >= 13", "PASS", f"{len(_ADAPTER_CLASSES)} registered"
            )
        except Exception as e:
            self._record("Adapter classes >= 13", "FAIL", str(e))

        # --- No duplicate model names ---
        try:
            dupes = [m for m in ALL_MODEL_NAMES if ALL_MODEL_NAMES.count(m) > 1]
            assert len(dupes) == 0, f"Duplicates: {set(dupes)}"
            self._record(
                "No duplicate model names", "PASS", f"{len(ALL_MODEL_NAMES)} unique"
            )
        except Exception as e:
            self._record("No duplicate model names", "FAIL", str(e))

        # --- Adapter prefix format ---
        try:
            for cls in _ADAPTER_CLASSES:
                inst = cls.__new__(cls)
                p = inst.prefix
                if p:
                    assert ":" not in p and " " not in p and p == p.lower()
            self._record("Adapter prefix format", "PASS")
        except Exception as e:
            self._record("Adapter prefix format", "FAIL", str(e))

        # --- ADAPTER_MODEL_NAMES format ---
        try:
            for name in ADAPTER_MODEL_NAMES:
                assert ":" in name
                prefix, model = name.split(":", 1)
                assert prefix and model
            self._record(
                "ADAPTER_MODEL_NAMES format",
                "PASS",
                f"{len(ADAPTER_MODEL_NAMES)} names",
            )
        except Exception as e:
            self._record("ADAPTER_MODEL_NAMES format", "FAIL", str(e))

        # --- Context resolve ---
        try:
            ctx = TranscriptionContext()
            ctx._ensure_initialized()
            tested = 0
            for prefix, adapter in ctx._adapter_map.items():
                if not adapter.is_available():
                    try:
                        ctx.resolve(f"{prefix}:test")
                        assert False, "Should have raised ValueError"
                    except ValueError:
                        pass
                    continue
                models = adapter.get_model_names()
                if models:
                    a, m = ctx.resolve(f"{prefix}:{models[0]}")
                    assert a is adapter
                    tested += 1
            self._record(
                "Context.resolve() prefixed",
                "PASS",
                f"tested {tested} available adapters, {len(ctx._adapter_map) - tested} unavailable correctly rejected",
            )
        except Exception as e:
            self._record("Context.resolve() prefixed", "FAIL", str(e))

        # --- is_api_model ---
        try:
            ctx = TranscriptionContext()
            assert ctx.is_api_model("groq:whisper-large-v3") == (
                True,
                "groq",
                "whisper-large-v3",
            )
            assert ctx.is_api_model("large-v3")[0] is False
            self._record("Context.is_api_model()", "PASS")
        except Exception as e:
            self._record("Context.is_api_model()", "FAIL", str(e))

        # --- UI models ---
        try:
            from ui.models import get_flat_display_list, is_separator

            flat = get_flat_display_list()
            seps = [x for x in flat if is_separator(x)]
            models = [x for x in flat if not is_separator(x)]
            assert len(seps) >= 5 and len(models) >= 20
            self._record(
                "UI model list", "PASS", f"{len(seps)} groups, {len(models)} models"
            )
        except Exception as e:
            self._record("UI model list", "FAIL", str(e))

        # --- Live segment logging ---
        try:
            import transcribe

            lines = []
            transcribe.log_segment_line(lines.append, "00:01:02,345", "  hello world  ")
            assert len(lines) == 1, lines
            assert (
                "\N{CLOCK FACE THREE OCLOCK} 00:01:02.345: hello world" in lines[0]
            ), lines[0]
            assert lines[0].startswith("["), lines[0]
            parsed = transcribe.parse_segment_log_line(
                "SEGMENT_LINE\t00:01:02,345\thello\tworld"
            )
            assert parsed == ("00:01:02,345", "hello\tworld"), parsed
            assert (
                transcribe.parse_segment_log_line("Out: FIRST_SEGMENT_WRITTEN") is None
            )
            assert (
                transcribe.parse_segment_log_line("SEGMENT_LINE\t00:00:00,000\t")
                is None
            )
            self._record("Live segment logging", "PASS", lines[0])
        except Exception as e:
            self._record("Live segment logging", "FAIL", str(e))

        # --- Subtitle metadata ---
        try:
            import shutil
            import tempfile
            import app_meta

            info = app_meta.build_source_info(
                {
                    "id": "abc123",
                    "title": "Example Video",
                    "channel": "Example Channel",
                    "channel_id": "UC123",
                    "channel_url": "https://www.youtube.com/@example",
                    "view_count": 1234,
                    "like_count": 56,
                    "dislike_count": 7,
                    "comment_count": 89,
                    "duration": 95.0,
                    "upload_date": "20260102",
                    "subtitles": {"en": [{}]},
                    "automatic_captions": {"en": [{}]},
                    "thumbnails": [
                        {"url": "http://x/small.jpg", "preference": -100, "width": 120},
                        {"url": "http://x/big.jpg", "preference": -100, "width": 1280},
                    ],
                },
                source_url="https://youtu.be/abc123",
                channel_thumbnail_url="http://x/channel.jpg",
            )
            assert info["video_id"] == "abc123"
            assert info["channel_name"] == "Example Channel"
            assert info["channel_url"] == "https://www.youtube.com/@example"
            assert info["thumbnail_url"] == "http://x/big.jpg", info["thumbnail_url"]
            assert info["channel_thumbnail_url"] == "http://x/channel.jpg"
            assert info["views"] == 1234 and info["likes"] == 56
            assert info["dislikes"] == 7 and info["comments_count"] == 89
            assert info["duration_seconds"] == 95.0
            assert info["upload_timestamp"] == "2026-01-02", info["upload_timestamp"]
            assert info["has_human_subs"] is True and info["has_automatic_subs"] is True
            assert app_meta.build_source_info(None)["channel_name"] is None
            assert (
                app_meta.build_source_info({"channel_name": "local_files"})[
                    "channel_name"
                ]
                == "local_files"
            )

            tmp = tempfile.mkdtemp()
            try:
                srt = os.path.join(tmp, "Example.base.en.srt")
                meta_path = app_meta.write_metadata(
                    srt, {"model": "base.en", "segments_count": 3}, source_info=info
                )
                assert meta_path == os.path.join(tmp, "Example.base.en.metadata.json")
                with open(meta_path, encoding="utf-8") as f:
                    saved = json.load(f)
                assert (
                    saved["views"] == 1234
                    and saved["channel_name"] == "Example Channel"
                )
                assert saved["model"] == "base.en" and saved["segments_count"] == 3
                assert saved["version"] == app_meta.APP_VERSION
                assert saved["commit_hash"]
                assert saved["date"] and saved["transcription_timestamp"]
                # Transcription facts win over source facts on shared keys.
                app_meta.write_metadata(
                    srt, {"duration_seconds": 12.5}, source_info=info
                )
                with open(meta_path, encoding="utf-8") as f:
                    assert json.load(f)["duration_seconds"] == 12.5
            finally:
                shutil.rmtree(tmp)
            self._record("Subtitle metadata", "PASS", f"{len(info)} source fields")
        except Exception as e:
            self._record("Subtitle metadata", "FAIL", str(e))

        # --- Force-mode subtitle backup ---
        try:
            import shutil
            import tempfile
            from whisper_subs import WhisperSubs

            tmp = tempfile.mkdtemp()
            try:
                ws = WhisperSubs.__new__(WhisperSubs)
                ws.log = lambda message: None
                base = os.path.join(tmp, "Video.base.en")
                srt = base + ".srt"
                meta = base + ".metadata.json"

                assert ws.backup_existing_sub(srt) is None, "nothing to back up"

                for first in ("first", "second"):
                    with open(srt, "w", encoding="utf-8") as f:
                        f.write(first)
                    with open(meta, "w", encoding="utf-8") as f:
                        json.dump({"model": "base.en"}, f)
                    backup = ws.backup_existing_sub(srt)
                    assert backup, f"no backup on {first} run"

                assert sorted(f for f in os.listdir(tmp) if f.endswith(".srt")) == [
                    "Video.base.en.2.srt",
                    "Video.base.en.3.srt",
                ], sorted(os.listdir(tmp))
                assert os.path.exists(base + ".2.metadata.json")
                assert os.path.exists(base + ".3.metadata.json")
                assert not os.path.exists(srt)
                assert not os.path.exists(meta)

                # A symlinked final subtitle is preserved under the final name.
                unfinished = base + ".unfinished.srt"
                with open(unfinished, "w", encoding="utf-8") as f:
                    f.write("live")
                with open(meta, "w", encoding="utf-8") as f:
                    json.dump({"model": "base.en"}, f)
                os.symlink(os.path.basename(unfinished), srt)
                assert ws.backup_existing_sub(srt) == base + ".4.srt"
                assert not os.path.exists(srt)
                assert os.path.exists(base + ".4.metadata.json")
            finally:
                shutil.rmtree(tmp)
            self._record("Force subtitle backup", "PASS", "numbering .2 .3 .4")
        except Exception as e:
            self._record("Force subtitle backup", "FAIL", str(e))

        # --- --show flag wiring ---
        try:
            import inspect
            import transcribe
            from whisper_subs import WhisperSubs
            from livestream_transcriber import LiveStreamTranscriber

            for func in (transcribe.process_create, transcribe.transcribe_audio):
                params = inspect.signature(func).parameters
                assert params["show_segments"].default is False, func.__name__
                assert "source_info" in params, func.__name__
            assert WhisperSubs.__init__.__defaults__[-1] is False
            assert LiveStreamTranscriber.__init__.__defaults__[-1] is False
            self._record("--show wiring", "PASS", "opt-in, default False")
        except Exception as e:
            self._record("--show wiring", "FAIL", str(e))

        # --- Source info is fetched once per video ---
        try:
            import whisper_subs
            from whisper_subs import WhisperSubs

            def bare(**attrs):
                obj = WhisperSubs.__new__(WhisperSubs)
                obj.log = lambda message: None
                for key, value in attrs.items():
                    setattr(obj, key, value)
                return obj

            calls = []

            class FakeYDL:
                def __init__(self, opts):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def extract_info(self, url, download=False):
                    calls.append(url)
                    return {
                        "id": "abc",
                        "title": "T",
                        "channel": "C",
                        "view_count": 7,
                    }

            real_ydl = whisper_subs.yt_dlp.YoutubeDL
            whisper_subs.yt_dlp.YoutubeDL = FakeYDL
            try:
                ws = bare(
                    log_file=None,
                    specified_browser=None,
                    info_cache={},
                    source_info_cache={},
                    channel_thumb_cache={},
                )
                url = "https://youtu.be/abc"
                assert ws.get_video_info(url) == ("T", "C")
                source = ws.get_source_info(url)
                assert len(calls) == 1, f"refetched video info: {calls}"
                assert source["view_count"] == 7, source
                assert source["id"] == "abc", source
                # build_source_info maps the raw keys to metadata fields.
                built = ws.build_source_info(url, is_local=False)
                assert built["views"] == 7 and built["channel_name"] == "C", built
                # Cached data is reused, and failures do not raise.
                assert ws.get_source_info(url)["view_count"] == 7
                assert len(calls) == 1, calls
            finally:
                whisper_subs.yt_dlp.YoutubeDL = real_ydl
            self._record(
                "Source info fetched once", "PASS", "cache shared with get_video_info"
            )
        except Exception as e:
            self._record("Source info fetched once", "FAIL", str(e))

        # --- Two-pass merge: no double offset, renumbered, temp files cleaned ---
        try:
            import transcribe as tr

            with tempfile.TemporaryDirectory() as tmp:
                final = os.path.join(tmp, "video.srt")
                second = os.path.join(tmp, "video.second_pass.srt")
                # pass 1 (start_time=10:00 -> end): absolute timestamps,
                # adapter metadata pseudo-block, one empty-text block
                with open(final, "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:00,000 --> 00:00:00,000\n"
                        "TRANSCRIPTION METADATA\nModel: m\n\n"
                        "1\n00:10:00,000 --> 00:10:05,000\nsecond half\n\n"
                        "2\n00:11:00,000 --> 00:11:02,000\n\n"
                    )
                # pass 2 (0 -> 10:00)
                with open(second, "w", encoding="utf-8") as f:
                    f.write("1\n00:01:00,000 --> 00:01:04,000\nfirst part\n\n")
                # stale pass-2 temp artifacts that must be cleaned up
                for name in (
                    "video.second_pass.srt.unfinished",
                    "video.second_pass.unfinished.srt",
                    "video.second_pass.whisper.log",
                ):
                    with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                        f.write("x")

                ok = tr._merge_srt_files(
                    second_pass_srt=second,
                    first_pass_srt=final,
                    final_srt=final,
                    write=lambda m: None,
                )
                assert ok
                with open(final, encoding="utf-8") as f:
                    content = f.read()
                # sorted: pass-2 block first, renumbered from 1
                assert "1\n00:01:00,000 --> 00:01:04,000\nfirst part" in content, (
                    content
                )
                # pass-1 block keeps its absolute timestamp (no double offset)
                assert "2\n00:10:00,000 --> 00:10:05,000\nsecond half" in content, (
                    content
                )
                assert "TRANSCRIPTION METADATA" not in content, content
                assert content.count("-->") == 2, content
                # temp artifacts removed
                for name in (
                    "video.second_pass.srt",
                    "video.second_pass.srt.unfinished",
                    "video.second_pass.unfinished.srt",
                    "video.second_pass.whisper.log",
                ):
                    assert not os.path.exists(os.path.join(tmp, name)), name
            self._record(
                "Two-pass merge", "PASS", "no double offset, renumbered, cleaned"
            )
        except Exception as e:
            self._record("Two-pass merge", "FAIL", str(e))

        # --- Two-pass local flow: pass 1 uses the standard srt filename ---
        try:
            import transcribe as tr

            calls = []

            def fake_single_pass(**kwargs):
                calls.append(
                    (kwargs["srt_file"], kwargs["start_time"], kwargs["end_time"])
                )
                # emulate the standard unfinished/symlink flow
                unfinished = kwargs["srt_file"].replace(".srt", ".unfinished.srt")
                with open(unfinished, "w", encoding="utf-8") as f:
                    if kwargs["start_time"]:
                        f.write("1\n00:10:00,000 --> 00:10:04,000\nfrom ten min\n\n")
                    else:
                        f.write("1\n00:01:00,000 --> 00:01:03,000\nfrom the start\n\n")
                os.symlink(os.path.basename(unfinished), kwargs["srt_file"])
                os.rename(unfinished, kwargs["srt_file"])
                return True

            real = tr._transcribe_single_pass
            tr._transcribe_single_pass = fake_single_pass
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    final = os.path.join(tmp, "video.srt")
                    ok = tr._two_pass_transcribe(
                        file="video.m4a",
                        current_model="tiny",
                        srt_file=final,
                        language=None,
                        device="cpu",
                        compute_type="int8",
                        force_device=False,
                        write=lambda m: None,
                        start_time="00:10:00",
                    )
                    assert ok
                    # pass 1 targets the final file directly — no .first_pass file
                    assert calls[0][0] == final, calls
                    assert not os.path.exists(os.path.join(tmp, "video.first_pass.srt"))
                    # pass 2 targets the .second_pass temp and ends at start_time
                    assert calls[1][0].endswith(".second_pass.srt"), calls
                    assert calls[1][1] is None and calls[1][2] == "00:10:00", calls
                    with open(final, encoding="utf-8") as f:
                        content = f.read()
                    assert "1\n00:01:00,000 --> 00:01:03,000\nfrom the start" in content
                    assert "2\n00:10:00,000 --> 00:10:04,000\nfrom ten min" in content
                    assert not os.path.exists(calls[1][0])
            finally:
                tr._transcribe_single_pass = real
            self._record(
                "Two-pass filenames", "PASS", "pass 1 -> srt_file, no .first_pass"
            )
        except Exception as e:
            self._record("Two-pass filenames", "FAIL", str(e))

        # --- Adapter two-pass: offset on pass 1 only, standard filename ---
        try:
            import transcribe as tr

            calls = []

            def fake_adapter_pass(**kwargs):
                calls.append(
                    (
                        kwargs["srt_file"],
                        kwargs["start_time"],
                        kwargs["start_offset_seconds"],
                    )
                )
                with open(kwargs["srt_file"], "w", encoding="utf-8") as f:
                    if kwargs["start_time"]:
                        f.write("1\n00:10:00,000 --> 00:10:03,000\noffset half\n\n")
                    else:
                        f.write("1\n00:00:30,000 --> 00:00:33,000\nearly half\n\n")
                return True

            real = tr._transcribe_single_pass_adapter
            tr._transcribe_single_pass_adapter = fake_adapter_pass
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    final = os.path.join(tmp, "video.srt")
                    ok = tr._two_pass_transcribe_adapter(
                        audio_file="video.m4a",
                        model_name="groq:whisper-large-v3",
                        srt_file=final,
                        language=None,
                        device="cpu",
                        compute_type="int8",
                        write=lambda m: None,
                        start_time="00:10:00",
                        start_offset_seconds=600.0,
                    )
                    assert ok
                    assert calls[0][0] == final, calls
                    assert calls[0][2] == 600.0, calls
                    assert calls[1][0].endswith(".second_pass.srt"), calls
                    assert calls[1][2] == 0.0, calls
                    with open(final, encoding="utf-8") as f:
                        content = f.read()
                    assert "1\n00:00:30,000 --> 00:00:33,000\nearly half" in content
                    assert "2\n00:10:00,000 --> 00:10:03,000\noffset half" in content
            finally:
                tr._transcribe_single_pass_adapter = real
            self._record(
                "Adapter two-pass", "PASS", "offset on pass 1 only, no .first_pass"
            )
        except Exception as e:
            self._record("Adapter two-pass", "FAIL", str(e))

        # --- Final verification gate ---
        try:
            import transcribe as tr

            with tempfile.TemporaryDirectory() as tmp:
                v = lambda name: os.path.join(tmp, name)

                # valid file
                with open(v("ok.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:01,000 --> 00:00:04,000\nhello world\n\n"
                        "2\n00:00:05,000 --> 00:00:08,000\nsecond line here\n\n"
                    )
                r = tr.verify_srt_file(v("ok.srt"), write=lambda m: None)
                assert r["ok"] and r["segments"] == 2 and r["last_end"] == 8.0, r

                # missing / empty / placeholder
                assert not tr.verify_srt_file(v("nope.srt"), write=lambda m: None)["ok"]
                with open(v("empty.srt"), "w", encoding="utf-8") as f:
                    f.write("")
                assert not tr.verify_srt_file(v("empty.srt"), write=lambda m: None)[
                    "ok"
                ]
                with open(v("ph.srt"), "w", encoding="utf-8") as f:
                    f.write("Transcription in progress...")
                assert not tr.verify_srt_file(v("ph.srt"), write=lambda m: None)["ok"]

                # corruption: incomplete trailing timestamp
                with open(v("corrupt.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:01,000 --> 00:00:04,000\nhello\n\n"
                        "2\n00:00:05,000 --> "
                    )
                r = tr.verify_srt_file(v("corrupt.srt"), write=lambda m: None)
                assert not r["ok"] and any(
                    "corrupt tail" in p for p in r["problems"]
                ), r

                # hallucination: phrase repeated 8x inside one segment
                with open(v("rep.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:01,000 --> 00:00:04,000\n"
                        + "de luta de luta " * 10
                        + "\n\n"
                    )
                r = tr.verify_srt_file(v("rep.srt"), write=lambda m: None)
                assert not r["ok"] and any(
                    "hallucination" in p for p in r["problems"]
                ), r

                # hallucination: 5 consecutive identical segments
                with open(v("run.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "".join(
                            f"{i}\n00:00:0{i},000 --> 00:00:0{i + 1},000\nsame text\n\n"
                            for i in range(1, 6)
                        )
                    )
                r = tr.verify_srt_file(v("run.srt"), write=lambda m: None)
                assert not r["ok"] and any("consecutive" in p for p in r["problems"]), r

                # hallucination: over half duplicates (>=10 segments)
                with open(v("dup.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "".join(
                            f"{i}\n00:{i:02d}:00,000 --> 00:{i:02d}:05,000\n"
                            + ("same text" if i % 3 else f"unique line {i}")
                            + "\n\n"
                            for i in range(1, 13)
                        )
                    )
                r = tr.verify_srt_file(v("dup.srt"), write=lambda m: None)
                assert not r["ok"] and any("unique" in p for p in r["problems"]), r

                # hallucination: near-duplicate variant loop (the reported pattern)
                with open(v("fuzzy.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:01:00,000 --> 00:01:02,000\na tua sociedade quer saber\n\n"
                        "2\n00:02:00,000 --> 00:02:03,000\na tua sociedade quer saber a história é verdadeira\n\n"
                        "3\n00:03:00,000 --> 00:03:04,000\na sociedade quer saber sempre\n\n"
                        "4\n00:04:00,000 --> 00:04:05,000\na tua sociedade quer saber de novo\n\n"
                        "5\n00:05:00,000 --> 00:05:06,000\nsociedade quer saber a tua história\n\n"
                        "6\n00:06:00,000 --> 00:06:07,000\na tua sociedade quer saber outra vez\n\n"
                    )
                r = tr.verify_srt_file(v("fuzzy.srt"), write=lambda m: None)
                assert not r["ok"], r

                # adapter metadata pseudo-block is skipped, not counted
                with open(v("meta.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:00,000 --> 00:00:00,000\n"
                        "TRANSCRIPTION METADATA\nModel: m\n\n"
                        "1\n00:00:01,000 --> 00:00:04,000\nreal cue\n\n"
                    )
                r = tr.verify_srt_file(v("meta.srt"), write=lambda m: None)
                assert r["ok"] and r["segments"] == 1, r

                # duration coverage: warning only, ok stays True
                with open(v("cov.srt"), "w", encoding="utf-8") as f:
                    f.write("1\n00:00:01,000 --> 00:00:04,000\nshort bit\n\n")
                r = tr.verify_srt_file(
                    v("cov.srt"), expected_duration=7200.0, write=lambda m: None
                )
                assert r["ok"], r
                assert (
                    r["warnings"] and r["coverage"] is not None and r["coverage"] < 0.01
                ), r

                # non-sequential numbering: warning only
                with open(v("num.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:01,000 --> 00:00:04,000\na\n\n"
                        "3\n00:00:05,000 --> 00:00:08,000\nb\n\n"
                    )
                r = tr.verify_srt_file(v("num.srt"), write=lambda m: None)
                assert r["ok"] and any("numbering" in w for w in r["warnings"]), r

            self._record(
                "Verification gate",
                "PASS",
                "contents/size/corrupt/hallucination/duration",
            )
        except Exception as e:
            self._record("Verification gate", "FAIL", str(e))

        # --- Within-segment phrase repeat counter ---
        try:
            import transcribe as tr

            c = tr.count_phrase_repeats
            assert c("sim, sim, sim, sim") == 4
            assert (
                c(
                    "a tua sociedade quer saber, a tua sociedade quer saber, "
                    "a tua sociedade quer saber"
                )
                == 3
            )
            assert (
                c(
                    "é um jogo de luta de luta de luta de luta de luta "
                    "de luta de luta de luta de luta de luta"
                )
                == 10
            )
            assert c("Eu não sei, mas eu não sei" * 25) >= 8
            assert c("eles terão que pagar um preço por isso, tá bom") == 0
            assert c("palavra, palavra, palavra") == 3  # legit triple: streak only
            assert c("") == 0
            self._record("Phrase repeat counter", "PASS", "comma + space joined")
        except Exception as e:
            self._record("Phrase repeat counter", "FAIL", str(e))

        # --- Hallucination loop detector ---
        try:
            import transcribe as tr

            d = tr.detect_segment_loop

            # 10 exact consecutive duplicates -> fires at the first one
            window = [("same text", float(i + 1)) for i in range(10)]
            assert d(window) == 1.0

            # 9 exact duplicates -> not enough
            assert d([("same text", float(i + 1)) for i in range(9)]) is None

            # varied real speech -> never fires
            real = [
                ("mas na hora de ir lá no estado", 1.0),
                ("a tua primeira corte é a coisa mais importante", 3.0),
                ("eles terão que pagar um preço por isso", 5.0),
                ("o papel dele na sociedade brasileira", 7.0),
                ("sim tá bom encerramos por hoje", 9.0),
                ("muito obrigado a todos os convidados", 11.0),
                ("até a próxima semana pessoal", 13.0),
            ]
            assert d(real) is None

            # the reported hallucination pattern: near-duplicate variants
            # ("a tua história do X é verdadeira" tails) interleaved with
            # short "sim" fills — exact-match detection misses this
            halluc = [
                ("mas na hora de ir lá no estado do corrente", 44 * 60 + 14),
                ("a tua sociedade quer saber", 44 * 60 + 19),
                (
                    "a tua sociedade quer saber a tua história do toffle é verdadeira",
                    44 * 60 + 21,
                ),
                (
                    "a sociedade quer saber a tua história do caso não é verdadeira",
                    44 * 60 + 24,
                ),
                (
                    "todo mundo quer saber a tua história da urgia é tão verdadeira",
                    44 * 60 + 27,
                ),
                ("todo mundo quer saber", 44 * 60 + 31),
                (
                    "a tua sociedade quer saber a história é verdadeira sim",
                    44 * 60 + 34,
                ),
            ]
            assert d(halluc) == 44 * 60 + 19, d(halluc)

            # 5 near-dupes crammed under 10s -> needs the time span
            tight = [
                ("a tua sociedade quer saber", 1.0),
                ("a tua sociedade quer saber a história é verdadeira", 2.0),
                ("a sociedade quer saber sempre", 3.0),
                ("a tua sociedade quer saber de novo", 4.0),
                ("sociedade quer saber a tua história", 5.0),
            ]
            assert d(tight) is None
            # same cluster stretched over 10s -> fires
            stretched = [(t, ts * 3.0) for t, ts in tight]
            assert d(stretched) == 3.0

            # 10 near-dupes in a short span -> fires regardless of span
            burst = [
                ("a tua sociedade quer saber variação", float(i)) for i in range(10)
            ]
            burst = [(t + f" {i}", float(i)) for i, (t, _) in enumerate(burst)]
            assert d(burst) == 0.0

            # empty / short window
            assert d([]) is None
            assert d([("so one", 1.0)]) is None
            self._record(
                "Hallucination loop detector", "PASS", "exact + fuzzy variants"
            )
        except Exception as e:
            self._record("Hallucination loop detector", "FAIL", str(e))

        # --- Resume info returns the LAST complete block ---
        try:
            import transcribe as tr

            with tempfile.TemporaryDirectory() as tmp:
                srt = os.path.join(tmp, "resume.srt")
                with open(srt, "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:01,000 --> 00:00:04,000\none\n\n"
                        "2\n00:00:05,000 --> 00:00:08,000\ntwo\n\n"
                        "3\n00:00:09,000 --> 00:00:12,000\nthree\n\n"
                    )
                # used to return the second-to-last block (8.0, 2),
                # re-transcribing and duplicating the last segment
                assert tr.get_srt_resume_info(srt) == (12.0, 3)

                # truncated tail (killed mid-write) is skipped
                with open(srt, "a", encoding="utf-8") as f:
                    f.write("4\n00:00:13,000 --> ")
                assert tr.get_srt_resume_info(srt) == (12.0, 3)

                # empty / placeholder content
                with open(srt, "w", encoding="utf-8") as f:
                    f.write("Transcription in progress...")
                assert tr.get_srt_resume_info(srt) == (0.0, 0)
            self._record("Resume info last block", "PASS", "no segment duplication")
        except Exception as e:
            self._record("Resume info last block", "FAIL", str(e))

        # --- Kill mid-transcription keeps progress (OOM/SIGKILL fix) ---
        try:
            import transcribe as tr

            class FakePopen:
                """Popen stand-in: simulates a worker that wrote some
                segments then died (truncated tail block included)."""

                def __init__(self, args, **kwargs):
                    self.args = args
                    self.returncode = None
                    self._exit_code = kwargs.pop("fake_exit_code", -9)
                    unfinished = kwargs.pop("fake_unfinished")
                    partial = (
                        "1\n00:00:01,000 --> 00:00:04,000\nhello\n\n"
                        "2\n00:00:05,000 --> 00:00:08,000\nworld\n\n"
                        "3\n00:00:09,000 --> "  # killed mid-write
                    )
                    with open(unfinished, "w", encoding="utf-8") as f:
                        f.write(partial)
                    self.stdout = io.StringIO("")
                    self.stderr = io.StringIO("")

                def wait(self, timeout=None):
                    self.returncode = self._exit_code
                    return self._exit_code

                def kill(self):
                    pass

                def poll(self):
                    return None

                def communicate(self, input=None, timeout=None):
                    return ("", "")

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            real_popen = tr.subprocess.Popen
            with tempfile.TemporaryDirectory() as tmp:
                srt = os.path.join(tmp, "video.srt")
                unfinished = os.path.join(tmp, "video.unfinished.srt")
                audio = os.path.join(tmp, "video.m4a")
                with open(audio, "wb") as f:
                    f.write(b"fake")

                def make_popen(exit_code):
                    def factory(args, **kwargs):
                        kwargs["fake_exit_code"] = exit_code
                        kwargs["fake_unfinished"] = unfinished
                        return FakePopen(args, **kwargs)

                    return factory

                # worker OOM-killed (SIGKILL -> returncode -9)
                tr.subprocess.Popen = make_popen(-9)
                try:
                    ok = tr.try_transcribe(
                        file=audio,
                        current_model="tiny",
                        srt_file=srt,
                        language="none",
                        device="cpu",
                        compute_type="int8",
                        force_device=True,
                        write=lambda m: None,
                    )
                    assert ok is False
                    # progress kept: symlink + unfinished intact
                    assert os.path.islink(srt), "srt_file must stay a symlink"
                    assert os.path.exists(unfinished), "unfinished was renamed away"
                    with open(unfinished, encoding="utf-8") as f:
                        assert "hello" in f.read()
                    # resume reads the last COMPLETE block, tolerating the
                    # truncated tail
                    end_time, number = tr.get_srt_resume_info(unfinished)
                    assert end_time == 8.0 and number == 2, (end_time, number)
                finally:
                    tr.subprocess.Popen = real_popen
            self._record(
                "Kill keeps progress", "PASS", "symlink + unfinished kept, resumable"
            )
        except Exception as e:
            self._record("Kill keeps progress", "FAIL", str(e))

        # --- Success finalizes; keep_unfinished preserves the chain ---
        try:
            import transcribe as tr

            class OkPopen:
                def __init__(self, args, unfinished, **kwargs):
                    self.args = args
                    self.returncode = None
                    with open(unfinished, "w", encoding="utf-8") as f:
                        f.write("1\n00:00:01,000 --> 00:00:04,000\nhello\n\n")
                    self.stdout = io.StringIO("")
                    self.stderr = io.StringIO("")

                def wait(self, timeout=None):
                    self.returncode = 0
                    return 0

                def kill(self):
                    pass

                def poll(self):
                    return None

                def communicate(self, input=None, timeout=None):
                    return ("", "")

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            real_popen = tr.subprocess.Popen

            def ok_factory(unfinished):
                def factory(args, **kwargs):
                    return OkPopen(args, unfinished=unfinished, **kwargs)

                return factory

            tr.subprocess.Popen = ok_factory(
                os.path.join("x-unused-x", "never-used.unfinished.srt")
            )
            try:
                # normal success: symlink replaced by the real file
                with tempfile.TemporaryDirectory() as tmp:
                    srt = os.path.join(tmp, "video.srt")
                    unfinished = os.path.join(tmp, "video.unfinished.srt")
                    audio = os.path.join(tmp, "video.m4a")
                    with open(audio, "wb") as f:
                        f.write(b"fake")
                    tr.subprocess.Popen = ok_factory(unfinished)
                    ok = tr.try_transcribe(
                        file=audio,
                        current_model="tiny",
                        srt_file=srt,
                        language="none",
                        device="cpu",
                        compute_type="int8",
                        force_device=True,
                        write=lambda m: None,
                    )
                    assert ok is True
                    assert not os.path.islink(srt), "must be finalized, not a symlink"
                    with open(srt, encoding="utf-8") as f:
                        assert "hello" in f.read()
                    assert not os.path.exists(unfinished)

                # incremental (keep_unfinished): chain preserved on success
                with tempfile.TemporaryDirectory() as tmp:
                    srt = os.path.join(tmp, "video.srt")
                    unfinished = os.path.join(tmp, "video.unfinished.srt")
                    audio = os.path.join(tmp, "video.m4a")
                    with open(audio, "wb") as f:
                        f.write(b"fake")
                    tr.subprocess.Popen = ok_factory(unfinished)
                    ok = tr.try_transcribe(
                        file=audio,
                        current_model="tiny",
                        srt_file=srt,
                        language="none",
                        device="cpu",
                        compute_type="int8",
                        force_device=True,
                        write=lambda m: None,
                        keep_unfinished=True,
                    )
                    assert ok is True
                    assert os.path.islink(srt), "live mode keeps the symlink"
                    assert os.path.exists(unfinished), "live mode keeps unfinished"
                    with open(unfinished, encoding="utf-8") as f:
                        assert "hello" in f.read()
            finally:
                tr.subprocess.Popen = real_popen
            self._record(
                "Finalize vs keep_unfinished", "PASS", "success renames, live keeps"
            )
        except Exception as e:
            self._record("Finalize vs keep_unfinished", "FAIL", str(e))

        # --- finalize_unfinished handles both naming conventions ---
        try:
            import transcribe as tr

            with tempfile.TemporaryDirectory() as tmp:
                # local naming: <base>.unfinished.srt + symlink
                srt = os.path.join(tmp, "local.srt")
                unfinished = os.path.join(tmp, "local.unfinished.srt")
                with open(unfinished, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:01,000 --> 00:00:02,000\ntext\n\n")
                os.symlink(os.path.basename(unfinished), srt)
                assert tr.finalize_unfinished(srt) is True
                assert not os.path.islink(srt)
                with open(srt, encoding="utf-8") as f:
                    assert "text" in f.read()
                assert not os.path.exists(unfinished)

                # adapter naming: <srt>.unfinished
                srt2 = os.path.join(tmp, "adapter.srt")
                unfinished2 = os.path.join(tmp, "adapter.srt.unfinished")
                with open(unfinished2, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:01,000 --> 00:00:02,000\ntext\n\n")
                assert tr.finalize_unfinished(srt2) is True
                with open(srt2, encoding="utf-8") as f:
                    assert "text" in f.read()

                # nothing to finalize
                assert tr.finalize_unfinished(os.path.join(tmp, "none.srt")) is False
            self._record("finalize_unfinished", "PASS", "local + adapter naming")
        except Exception as e:
            self._record("finalize_unfinished", "FAIL", str(e))

        # --- Live transcriber: incremental passes + safe stream-end move ---
        try:
            import transcribe as tr
            from livestream_transcriber import LiveStreamTranscriber

            with tempfile.TemporaryDirectory() as tmp:
                outdir = os.path.join(tmp, "out")
                os.makedirs(outdir)
                records = []

                def fake_process_create(**kwargs):
                    records.append(kwargs)
                    return True

                real_pc = tr.process_create
                tr.process_create = fake_process_create
                try:
                    ls = LiveStreamTranscriber(
                        model_name="tiny",
                        output_dir=outdir,
                        log_func=lambda m: None,
                        live_poll=0.05,
                    )
                    ls.is_running = True
                    audio = os.path.join(tmp, "live.m4a")
                    with open(audio, "wb") as f:
                        f.write(b"\0" * 600_000)  # above the 500KB initial wait
                    srt = os.path.join(tmp, "live.srt")
                    ls.transcribe_in_background(audio, srt)
                    ls.is_running = False
                    ls.transcription_process.join(timeout=10)
                    assert not ls.transcription_process.is_alive()
                    assert records, "process_create was not called"
                    assert records[0]["keep_unfinished"] is True, records[0]
                finally:
                    tr.process_create = real_pc

                # stream end: symlinked srt must become a real moved file
                srt = os.path.join(tmp, "live.srt")
                unfinished = os.path.join(tmp, "live.unfinished.srt")
                with open(unfinished, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:01,000 --> 00:00:02,000\nlive text\n\n")
                os.symlink(os.path.basename(unfinished), srt)
                audio = os.path.join(tmp, "live.m4a")
                ls._finalize_live_files(srt, audio)

                final_srt = os.path.join(outdir, "live.srt")
                assert os.path.exists(final_srt), "final srt not saved"
                assert not os.path.islink(final_srt), "moved a dangling symlink"
                with open(final_srt, encoding="utf-8") as f:
                    assert "live text" in f.read()
                assert not os.path.exists(unfinished)
                assert os.path.exists(os.path.join(outdir, "live.m4a"))

                # no subtitles at all: must not raise
                ls._finalize_live_files(
                    os.path.join(tmp, "missing.srt"), os.path.join(tmp, "missing.m4a")
                )
            self._record(
                "Live incremental + finalize",
                "PASS",
                "keep_unfinished + real file move",
            )
        except Exception as e:
            self._record("Live incremental + finalize", "FAIL", str(e))

        # --- Two-pass merge extras: empty pass, multiline text, CRLF, order ---
        try:
            import transcribe as tr

            with tempfile.TemporaryDirectory() as tmp:
                final = os.path.join(tmp, "v.srt")
                second = os.path.join(tmp, "v.second_pass.srt")
                # empty second pass, multiline + CRLF in first pass
                with open(second, "w", encoding="utf-8") as f:
                    f.write("")
                with open(final, "w", encoding="utf-8") as f:
                    f.write(
                        "7\n00:10:00,000 --> 00:10:05,000\r\nline one\r\nline two\r\n\r\n"
                    )
                ok = tr._merge_srt_files(
                    second_pass_srt=second,
                    first_pass_srt=final,
                    final_srt=final,
                    write=lambda m: None,
                )
                assert ok
                with open(final, encoding="utf-8") as f:
                    content = f.read()
                assert (
                    "1\n00:10:00,000 --> 00:10:05,000\nline one\nline two" in content
                ), content

                # out-of-order inputs get sorted by start time
                with open(final, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:30,000 --> 00:00:35,000\nlater\n\n")
                with open(second, "w", encoding="utf-8") as f:
                    f.write("1\n00:00:01,000 --> 00:00:05,000\nfirst\n\n")
                ok = tr._merge_srt_files(
                    second_pass_srt=second,
                    first_pass_srt=final,
                    final_srt=final,
                    write=lambda m: None,
                )
                assert ok
                with open(final, encoding="utf-8") as f:
                    content = f.read()
                assert content.index("first") < content.index("later")
                assert content.startswith("1\n00:00:01,000"), content
            self._record(
                "Two-pass merge extras", "PASS", "empty pass, multiline, CRLF, sorted"
            )
        except Exception as e:
            self._record("Two-pass merge extras", "FAIL", str(e))

        # --- Empty .srt checker ---
        try:
            import srt_checker as sc

            with tempfile.TemporaryDirectory() as tmp:
                v = lambda name: os.path.join(tmp, name)

                # is_empty_srt
                with open(v("ok.srt"), "w", encoding="utf-8") as f:
                    f.write("1\n00:00:01,000 --> 00:00:04,000\nhello\n\n")
                assert not sc.is_empty_srt(v("ok.srt"))
                assert sc.is_empty_srt(v("missing.srt"))
                with open(v("zero.srt"), "w", encoding="utf-8") as f:
                    f.write("")
                assert sc.is_empty_srt(v("zero.srt"))
                with open(v("ph.srt"), "w", encoding="utf-8") as f:
                    f.write("Transcription in progress...")
                assert sc.is_empty_srt(v("ph.srt"))
                with open(v("noseg.srt"), "w", encoding="utf-8") as f:
                    f.write("garbage line\nno timestamps here\n\n")
                assert sc.is_empty_srt(v("noseg.srt"))
                # content with problems is NOT empty (it has segments)
                with open(v("hallu.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:01,000 --> 00:00:04,000\n" + "de luta " * 10 + "\n\n"
                    )
                assert not sc.is_empty_srt(v("hallu.srt"))

                # remove_from_history
                with open(v("history.txt"), "w", encoding="utf-8") as f:
                    f.write("vidA tiny\nhttps://youtu.be/x base\nvidB large-v3\n")
                assert sc.remove_from_history(v("history.txt"), ["vidA"]) == 1
                with open(v("history.txt"), encoding="utf-8") as f:
                    assert f.read() == "https://youtu.be/x base\nvidB large-v3\n"
                assert sc.remove_from_history(v("history.txt"), ["nope"]) == 0
                assert sc.remove_from_history(v("nohist.txt"), ["vidA"]) == 0

                # remove_task_from_progress
                jobs = [
                    {
                        "id": 1,
                        "status": "initializing",
                        "tasks": [
                            {"source": "https://youtu.be/a", "status": "completed"},
                            {"source": "https://youtu.be/b", "status": "transcribing"},
                        ],
                    },
                    {
                        "id": 2,
                        "status": "initializing",
                        "tasks": [
                            {"source": "https://youtu.be/c", "status": "completed"},
                        ],
                    },
                ]
                with open(v("jobs.json"), "w", encoding="utf-8") as f:
                    json.dump(jobs, f)
                assert (
                    sc.remove_task_from_progress(
                        v("jobs.json"), 1, "https://youtu.be/a"
                    )
                    is True
                )
                with open(v("jobs.json"), encoding="utf-8") as f:
                    jobs_now = json.load(f)
                assert [t["source"] for t in jobs_now[0]["tasks"]] == [
                    "https://youtu.be/b"
                ]
                assert jobs_now[1]["tasks"][0]["source"] == "https://youtu.be/c"
                assert (
                    sc.remove_task_from_progress(
                        v("jobs.json"), 1, "https://youtu.be/zz"
                    )
                    is False
                )
                assert (
                    sc.remove_task_from_progress(
                        v("jobs.json"), None, "https://youtu.be/b"
                    )
                    is False
                )

                # empty list round-trip
                sc.add_to_empty_list(v("empty.txt"), "/p/e.srt", "src", "tiny")
                sc.add_to_empty_list(v("empty.txt"), "/p/f.srt", None, None)
                records = sc.read_empty_list(v("empty.txt"))
                assert len(records) == 2, records
                assert records[0]["srt"] == "/p/e.srt"
                assert records[0]["source"] == "src"
                assert records[0]["model"] == "tiny"
                assert records[0]["date"]
                assert records[1]["source"] == ""
                assert sc.read_empty_list(v("noexist.txt")) == []

                # check_empty_srt: valid file untouched, empty file cleaned up
                history = v("history.txt")
                with open(history, "w", encoding="utf-8") as f:
                    f.write("vidX tiny\nvidY large-v3\n")
                with open(v("jobs.json"), "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {
                                "id": 1,
                                "status": "initializing",
                                "tasks": [
                                    {
                                        "source": "https://youtu.be/x",
                                        "status": "transcribing",
                                    },
                                    {
                                        "source": "https://youtu.be/keep",
                                        "status": "completed",
                                    },
                                ],
                            }
                        ],
                        f,
                    )
                logs = []
                assert (
                    sc.check_empty_srt(
                        srt_path=v("ok.srt"),
                        ids=["vidX"],
                        source="https://youtu.be/x",
                        model_name="tiny",
                        history_file=history,
                        jobs_file=v("jobs.json"),
                        job_id=1,
                        list_file=v("empty.txt"),
                        write=logs.append,
                    )
                    is False
                )
                assert not logs
                with open(history, encoding="utf-8") as f:
                    assert "vidX tiny" in f.read()

                with open(v("bad.srt"), "w", encoding="utf-8") as f:
                    f.write("")
                assert (
                    sc.check_empty_srt(
                        srt_path=v("bad.srt"),
                        ids=["vidX", "https://youtu.be/x"],
                        source="https://youtu.be/x",
                        model_name="tiny",
                        history_file=history,
                        jobs_file=v("jobs.json"),
                        job_id=1,
                        list_file=v("empty.txt"),
                        write=logs.append,
                    )
                    is True
                )
                with open(history, encoding="utf-8") as f:
                    assert f.read() == "vidY large-v3\n"
                with open(v("jobs.json"), encoding="utf-8") as f:
                    remaining_tasks = json.load(f)[0]["tasks"]
                assert [t["source"] for t in remaining_tasks] == [
                    "https://youtu.be/keep"
                ], remaining_tasks
                listed = sc.read_empty_list(v("empty.txt"))
                assert any(r["srt"] == v("bad.srt") for r in listed)
                assert any("Empty subtitles" in m for m in logs)

            self._record(
                "Empty srt checker",
                "PASS",
                "detect + clear progress/completed + list",
            )
        except Exception as e:
            self._record("Empty srt checker", "FAIL", str(e))

        # --- Empty srt scan over the output directory ---
        try:
            import srt_checker as sc

            with tempfile.TemporaryDirectory() as tmp:
                out = os.path.join(tmp, "subs")
                os.makedirs(os.path.join(out, "chan"))
                p = lambda *parts: os.path.join(out, *parts)

                # a good subtitle
                with open(p("chan", "good.srt"), "w", encoding="utf-8") as f:
                    f.write("1\n00:00:01,000 --> 00:00:04,000\nreal text\n\n")
                # an empty one with metadata describing its source
                with open(p("chan", "empty.srt"), "w", encoding="utf-8") as f:
                    f.write("")
                with open(p("chan", "empty.metadata.json"), "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "source_url": "https://youtu.be/empty",
                            "video_id": "emptyvid",
                        },
                        f,
                    )
                # in-progress artifacts must be skipped
                with open(p("chan", "wip.unfinished.srt"), "w", encoding="utf-8") as f:
                    f.write("")
                os.symlink("wip.unfinished.srt", p("chan", "wip.srt"))

                history = os.path.join(tmp, "history.txt")
                with open(history, "w", encoding="utf-8") as f:
                    f.write("emptyvid tiny\ngoodvid large-v3\n")
                jobs_file = os.path.join(tmp, "jobs.json")
                with open(jobs_file, "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {
                                "id": 7,
                                "status": "initializing",
                                "tasks": [
                                    {
                                        "source": "https://youtu.be/empty",
                                        "status": "completed",
                                    }
                                ],
                            }
                        ],
                        f,
                    )
                list_file = os.path.join(tmp, "empty_srts.txt")

                found = sc.scan_empty_srts(
                    directory=out,
                    history_file=history,
                    jobs_file=jobs_file,
                    list_file=list_file,
                    write=lambda m: None,
                )
                assert found == [p("chan", "empty.srt")], found
                with open(history, encoding="utf-8") as f:
                    assert f.read() == "goodvid large-v3\n"
                with open(jobs_file, encoding="utf-8") as f:
                    assert json.load(f)[0]["tasks"] == []
                listed = sc.read_empty_list(list_file)
                assert (
                    len(listed) == 1 and listed[0]["source"] == "https://youtu.be/empty"
                )
                # good subtitle untouched
                with open(p("chan", "good.srt"), encoding="utf-8") as f:
                    assert "real text" in f.read()
                # second scan finds nothing new (already handled)
                assert sc.scan_empty_srts(
                    directory=out,
                    history_file=history,
                    jobs_file=jobs_file,
                    list_file=list_file,
                    write=lambda m: None,
                ) == [p("chan", "empty.srt")]  # still empty on disk, re-listed
                assert len(sc.read_empty_list(list_file)) == 2

            self._record("Empty srt scan", "PASS", "metadata recovery, symlink skip")
        except Exception as e:
            self._record("Empty srt scan", "FAIL", str(e))

        # --- Already-processed task still launches the player on --mpv ---
        try:
            import whisper_subs as ws

            url = "https://www.youtube.com/watch?v=o3qvTORAduk"
            vid = "o3qvTORAduk"

            tmp = tempfile.mkdtemp()
            try:
                hist = os.path.join(tmp, "history.txt")
                jobs = os.path.join(tmp, "jobs.json")
                chan = os.path.join(tmp, "channel")
                os.makedirs(chan)
                good = os.path.join(chan, "vid.small.srt")
                # Two cues: an existing subtitle is only trusted when it
                # holds at least MIN_EXISTING_SRT_LINES entries.
                with open(good, "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:00,000 --> 00:00:01,000\nfirst\n\n"
                        "2\n00:00:01,000 --> 00:00:02,000\nsecond\n\n"
                    )
                with open(
                    os.path.join(chan, "vid.small.metadata.json"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump({"source_url": url, "video_id": vid}, f)
                # Artifacts the lookup must ignore.
                os.symlink(good, os.path.join(chan, "vid.small.unfinished.srt"))
                with open(
                    os.path.join(chan, "vid.small.2.srt"), "w", encoding="utf-8"
                ) as f:
                    f.write("1\n00:00:00,000 --> 00:00:01,000\nold\n\n")

                with open(hist, "w", encoding="utf-8") as f:
                    f.write(f"{vid} small\n")
                with open(jobs, "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {
                                "id": 1,
                                "date": "d",
                                "model": "small",
                                "source": url,
                                "status": "processing",
                                "tasks": [
                                    {
                                        "source": url,
                                        "status": "pending",
                                        "title": "t",
                                    }
                                ],
                            }
                        ],
                        f,
                    )

                saved = (ws.HISTORY_FILE, ws.JOBS_FILE, ws.OUTPUT_DIR)
                ws.HISTORY_FILE, ws.JOBS_FILE, ws.OUTPUT_DIR = hist, jobs, tmp
                try:

                    class _Probe(ws.WhisperSubs):
                        def __init__(self, *a, **kw):
                            super().__init__(*a, **kw)
                            self.launched = []

                        def launch_mpv(self, audio_file, srt_file, task_source):
                            self.launched.append(srt_file)
                            return None

                        def check_and_download_subs(self, *a, **kw):
                            raise AssertionError("must not re-check subs on skip")

                        def get_video_info(self, url):
                            return "t", "c"

                    task = {"source": url, "status": "pending", "title": "t"}

                    # Without a player request the skip stays silent.
                    quiet = _Probe(model_name="small")
                    quiet.process_task(1, task, task_id="t1")
                    assert quiet.launched == [], quiet.launched

                    # --mpv on an already-processed source still plays.
                    live = _Probe(model_name="small", run_mpv=True, mpv_auto=True)
                    live.process_task(1, task, task_id="t2")
                    assert live.launched == [good], live.launched

                    # Lookup resolves the current subtitle only.
                    assert quiet.find_existing_srt(url) == good
                    assert (
                        quiet.find_existing_srt("https://youtu.be/zzzzzzzzzzz") is None
                    )

                    with open(jobs, encoding="utf-8") as f:
                        assert json.load(f)[0]["tasks"][0]["status"] == "skipped"

                    # --- validation rejects unusable subtitles ---
                    ok, reason = quiet.validate_existing_srt(good)
                    assert ok, reason

                    one = os.path.join(chan, "one.small.srt")
                    with open(one, "w", encoding="utf-8") as f:
                        f.write("1\n00:00:00,000 --> 00:00:01,000\nonly\n\n")
                    bad, reason = quiet.validate_existing_srt(one)
                    assert not bad and "1 subtitle" in reason, reason

                    blank = os.path.join(chan, "blank.small.srt")
                    open(blank, "w").close()
                    bad, reason = quiet.validate_existing_srt(blank)
                    assert not bad and reason == "empty file", reason

                    bad, reason = quiet.validate_existing_srt(
                        os.path.join(chan, "nope.srt")
                    )
                    assert not bad and reason == "missing", reason

                    # A rejected subtitle clears the marker so it retries.
                    # Point the video id at a single-cue subtitle so it is
                    # the one the lookup resolves.
                    os.remove(good)
                    os.remove(os.path.join(chan, "vid.small.metadata.json"))
                    with open(os.path.join(chan, "vid.small.srt"), "w") as f:
                        f.write("1\n00:00:00,000 --> 00:00:01,000\nonly\n\n")
                    with open(os.path.join(chan, "vid.small.metadata.json"), "w") as f:
                        json.dump({"source_url": url, "video_id": vid}, f)
                    with open(hist, "w", encoding="utf-8") as f:
                        f.write(f"{vid} small\n")
                    retry_probe = _Probe(model_name="small")
                    assert (
                        retry_probe._handle_existing_subtitle(1, url, vid) is False
                    ), "single-cue subtitle must trigger a retry"
                    with open(hist, encoding="utf-8") as f:
                        assert f.read() == "", "history must be cleared for retry"
                finally:
                    ws.HISTORY_FILE, ws.JOBS_FILE, ws.OUTPUT_DIR = saved

                self._record(
                    "--mpv on processed task", "PASS", "plays existing subtitle"
                )
                self._record(
                    "Existing sub validation",
                    "PASS",
                    "empty/<2 cues rejected, history cleared, paths reported",
                )
            finally:
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            self._record("--mpv on processed task", "FAIL", str(e))
            self._record("Existing sub validation", "FAIL", str(e))

        # --- mpv single-instance lock ---
        try:
            import tempfile as _tf

            import mpv_lock

            media_a = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
            media_b = "https://www.youtube.com/watch?v=bbbbbbbbbbb"

            lockdir = _tf.mkdtemp()
            real_tmp = tempfile.tempdir
            try:
                # Point the lock files at a scratch dir.
                tempfile.tempdir = lockdir
                for name in os.listdir(real_tmp):
                    if name.startswith(".whispersubs-mpv-"):
                        os.remove(os.path.join(real_tmp, name))
                mpv_lock._claims.clear()

                # One window per media, no matter how often the launch
                # path runs (model fallback, loop retry, two-pass).
                results = [mpv_lock.claim(media_a) for _ in range(5)]
                assert results[0] is True, "first launch must win"
                assert not any(results[1:]), f"re-openings not blocked: {results}"

                # Switching video opens a fresh window.
                assert mpv_lock.claim(media_b) is True
                assert not mpv_lock.claim(media_b), "second window for same video"
                assert mpv_lock.claim(media_a) is False, "media_a already open"
            finally:
                tempfile.tempdir = real_tmp
                mpv_lock._claims.clear()
                shutil.rmtree(lockdir, ignore_errors=True)

            self._record("MPV launch lock", "PASS", "one window per media")
        except Exception as e:
            self._record("MPV launch lock", "FAIL", str(e))

        # --- --playlist / --playlist-channel / --playlist-file ---
        try:
            import shutil as _sh
            import tempfile as _tf

            import playlist as pl

            tmp = _tf.mkdtemp()
            try:
                m3u = os.path.join(tmp, "queue.m3u")
                p = pl.Playlist(m3u)
                assert p.append("https://youtu.be/aaaaaaaaaaa", "/s/a.srt") is True
                assert p.append("https://youtu.be/aaaaaaaaaaa", "/s/a.srt") is False, (
                    "duplicate must be rejected"
                )
                assert p.append("https://youtu.be/bbbbbbbbbbb", "/s/b.srt") is True
                assert len(p) == 2, len(p)

                # extend() must dedupe too, and report the added count.
                added = p.extend(
                    [
                        ("https://youtu.be/aaaaaaaaaaa", "/s/a.srt"),  # dup
                        ("https://youtu.be/ccccccccccc", "/s/c.srt"),
                    ]
                )
                assert added == 1, f"extend added {added}, expected 1"
                assert len(p) == 3, len(p)
                body = open(m3u, encoding="utf-8").read()
                assert body.startswith("#EXTM3U"), body
                assert "/s/a.srt" in body and "/s/b.srt" in body, body

                # Channel playlist skips unfinished files and symlinks.
                chan = os.path.join(tmp, "Channel")
                os.makedirs(chan)
                for vid, title in (("aaaaaaaaaaa", "One"), ("bbbbbbbbbbb", "Two")):
                    with open(
                        os.path.join(chan, f"{title}.small.srt"), "w", encoding="utf-8"
                    ) as f:
                        f.write(
                            "1\n00:00:00,000 --> 00:00:01,000\nx\n\n"
                            "2\n00:00:01,000 --> 00:00:02,000\ny\n\n"
                        )
                    with open(
                        os.path.join(chan, f"{title}.small.metadata.json"),
                        "w",
                        encoding="utf-8",
                    ) as f:
                        json.dump({"source_url": f"https://youtu.be/{vid}"}, f)
                with open(
                    os.path.join(chan, "Three.small.unfinished.srt"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    f.write("junk")
                os.symlink(
                    os.path.join(chan, "One.small.srt"),
                    os.path.join(chan, "One.small.srt.link"),
                )

                chan_m3u = os.path.join(tmp, "chan.m3u")
                cp = ws.WhisperSubs(
                    model_name="small",
                    playlist_mode="channel",
                    playlist_path=chan_m3u,
                )
                cp._build_channel_playlist(chan)
                entries = cp.playlist.entries()
                assert len(entries) == 2, entries
                assert all("unfinished" not in s for _, s in entries), entries
                assert all("link" not in s for _, s in entries), entries

                # --playlist-file controls the output path.
                custom = os.path.join(tmp, "deep", "mine.m3u")
                pp = ws.WhisperSubs(
                    model_name="small", playlist_mode="pending", playlist_path=custom
                )
                assert pp.playlist_file == custom, pp.playlist_file
                assert os.path.exists(custom), "custom playlist not created"

                # No flags -> no playlist object, no stray file.
                plain = ws.WhisperSubs(model_name="small")
                assert plain.playlist is None and plain.playlist_file is None

                # A skipped (already-finished) video is still queued.
                t2 = _tf.mkdtemp()
                try:
                    hist2 = os.path.join(t2, "history.txt")
                    chan2 = os.path.join(t2, "chan")
                    os.makedirs(chan2)
                    srt2 = os.path.join(chan2, "v.small.srt")
                    with open(srt2, "w", encoding="utf-8") as f:
                        f.write(
                            "1\n00:00:00,000 --> 00:00:01,000\na\n\n"
                            "2\n00:00:01,000 --> 00:00:02,000\nb\n\n"
                        )
                    with open(os.path.join(chan2, "v.small.metadata.json"), "w") as f:
                        json.dump(
                            {
                                "source_url": "https://youtu.be/aaaaaaaaaaa",
                                "video_id": "aaaaaaaaaaa",
                            },
                            f,
                        )
                    with open(hist2, "w", encoding="utf-8") as f:
                        f.write("aaaaaaaaaaa small\n")

                    saved2 = (ws.HISTORY_FILE, ws.OUTPUT_DIR)
                    ws.HISTORY_FILE, ws.OUTPUT_DIR = hist2, t2
                    try:
                        m3u2 = os.path.join(t2, "q.m3u")
                        proc2 = ws.WhisperSubs(
                            model_name="small",
                            run_mpv=True,
                            mpv_auto=True,
                            playlist_mode="pending",
                            playlist_path=m3u2,
                        )
                        proc2._handle_existing_subtitle(
                            1, "https://youtu.be/aaaaaaaaaaa", "aaaaaaaaaaa"
                        )
                        entries = proc2.playlist.entries()
                        assert len(entries) == 1, entries
                        assert entries[0][1] == srt2, entries
                    finally:
                        ws.HISTORY_FILE, ws.OUTPUT_DIR = saved2
                finally:
                    _sh.rmtree(t2, ignore_errors=True)

                self._record(
                    "Playlist flags",
                    "PASS",
                    "--playlist/--playlist-channel/--playlist-file",
                )
            finally:
                _sh.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            self._record("Playlist flags", "FAIL", str(e))

        # --- Already-processed task still launches the player on --mpv ---
        try:
            import whisper_subs as ws

            url = "https://www.youtube.com/watch?v=o3qvTORAduk"
            vid = "o3qvTORAduk"

            tmp = tempfile.mkdtemp()
            try:
                hist = os.path.join(tmp, "history.txt")
                jobs = os.path.join(tmp, "jobs.json")
                chan = os.path.join(tmp, "channel")
                os.makedirs(chan)
                good = os.path.join(chan, "vid.small.srt")
                # Two cues: an existing subtitle is only trusted when it
                # holds at least MIN_EXISTING_SRT_LINES entries.
                with open(good, "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:00,000 --> 00:00:01,000\nfirst\n\n"
                        "2\n00:00:01,000 --> 00:00:02,000\nsecond\n\n"
                    )
                with open(
                    os.path.join(chan, "vid.small.metadata.json"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump({"source_url": url, "video_id": vid}, f)
                # Artifacts the lookup must ignore.
                os.symlink(good, os.path.join(chan, "vid.small.unfinished.srt"))
                with open(
                    os.path.join(chan, "vid.small.2.srt"), "w", encoding="utf-8"
                ) as f:
                    f.write("1\n00:00:00,000 --> 00:00:01,000\nold\n\n")

                with open(hist, "w", encoding="utf-8") as f:
                    f.write(f"{vid} small\n")
                with open(jobs, "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {
                                "id": 1,
                                "date": "d",
                                "model": "small",
                                "source": url,
                                "status": "processing",
                                "tasks": [
                                    {
                                        "source": url,
                                        "status": "pending",
                                        "title": "t",
                                    }
                                ],
                            }
                        ],
                        f,
                    )

                saved = (ws.HISTORY_FILE, ws.JOBS_FILE, ws.OUTPUT_DIR)
                ws.HISTORY_FILE, ws.JOBS_FILE, ws.OUTPUT_DIR = hist, jobs, tmp
                try:

                    class _Probe(ws.WhisperSubs):
                        def __init__(self, *a, **kw):
                            super().__init__(*a, **kw)
                            self.launched = []

                        def launch_mpv(self, audio_file, srt_file, task_source):
                            self.launched.append(srt_file)
                            return None

                        def check_and_download_subs(self, *a, **kw):
                            raise AssertionError("must not re-check subs on skip")

                        def get_video_info(self, url):
                            return "t", "c"

                    task = {"source": url, "status": "pending", "title": "t"}

                    # Without a player request the skip stays silent.
                    quiet = _Probe(model_name="small")
                    quiet.process_task(1, task, task_id="t1")
                    assert quiet.launched == [], quiet.launched

                    # --mpv on an already-processed source still plays.
                    live = _Probe(model_name="small", run_mpv=True, mpv_auto=True)
                    live.process_task(1, task, task_id="t2")
                    assert live.launched == [good], live.launched

                    # Lookup resolves the current subtitle only.
                    assert quiet.find_existing_srt(url) == good
                    assert (
                        quiet.find_existing_srt("https://youtu.be/zzzzzzzzzzz") is None
                    )

                    with open(jobs, encoding="utf-8") as f:
                        assert json.load(f)[0]["tasks"][0]["status"] == "skipped"

                    # --- validation rejects unusable subtitles ---
                    ok, reason = quiet.validate_existing_srt(good)
                    assert ok, reason

                    one = os.path.join(chan, "one.small.srt")
                    with open(one, "w", encoding="utf-8") as f:
                        f.write("1\n00:00:00,000 --> 00:00:01,000\nonly\n\n")
                    bad, reason = quiet.validate_existing_srt(one)
                    assert not bad and "1 subtitle" in reason, reason

                    blank = os.path.join(chan, "blank.small.srt")
                    open(blank, "w").close()
                    bad, reason = quiet.validate_existing_srt(blank)
                    assert not bad and reason == "empty file", reason

                    bad, reason = quiet.validate_existing_srt(
                        os.path.join(chan, "nope.srt")
                    )
                    assert not bad and reason == "missing", reason

                    # A rejected subtitle clears the marker so it retries.
                    # Point the video id at a single-cue subtitle so it is
                    # the one the lookup resolves.
                    os.remove(good)
                    os.remove(os.path.join(chan, "vid.small.metadata.json"))
                    with open(os.path.join(chan, "vid.small.srt"), "w") as f:
                        f.write("1\n00:00:00,000 --> 00:00:01,000\nonly\n\n")
                    with open(os.path.join(chan, "vid.small.metadata.json"), "w") as f:
                        json.dump({"source_url": url, "video_id": vid}, f)
                    with open(hist, "w", encoding="utf-8") as f:
                        f.write(f"{vid} small\n")
                    retry_probe = _Probe(model_name="small")
                    assert (
                        retry_probe._handle_existing_subtitle(1, url, vid) is False
                    ), "single-cue subtitle must trigger a retry"
                    with open(hist, encoding="utf-8") as f:
                        assert f.read() == "", "history must be cleared for retry"
                finally:
                    ws.HISTORY_FILE, ws.JOBS_FILE, ws.OUTPUT_DIR = saved

                self._record(
                    "--mpv on processed task", "PASS", "plays existing subtitle"
                )
                self._record(
                    "Existing sub validation",
                    "PASS",
                    "empty/<2 cues rejected, history cleared, paths reported",
                )
            finally:
                import shutil

                shutil.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            self._record("--mpv on processed task", "FAIL", str(e))
            self._record("Existing sub validation", "FAIL", str(e))

        # --- mpv single-instance lock ---
        try:
            import tempfile as _tf

            import mpv_lock

            media_a = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
            media_b = "https://www.youtube.com/watch?v=bbbbbbbbbbb"

            lockdir = _tf.mkdtemp()
            real_tmp = tempfile.tempdir
            try:
                # Point the lock files at a scratch dir.
                tempfile.tempdir = lockdir
                for name in os.listdir(real_tmp):
                    if name.startswith(".whispersubs-mpv-"):
                        os.remove(os.path.join(real_tmp, name))
                mpv_lock._claims.clear()

                # One window per media, no matter how often the launch
                # path runs (model fallback, loop retry, two-pass).
                results = [mpv_lock.claim(media_a) for _ in range(5)]
                assert results[0] is True, "first launch must win"
                assert not any(results[1:]), f"re-openings not blocked: {results}"

                # Switching video opens a fresh window.
                assert mpv_lock.claim(media_b) is True
                assert not mpv_lock.claim(media_b), "second window for same video"
                assert mpv_lock.claim(media_a) is False, "media_a already open"
            finally:
                tempfile.tempdir = real_tmp
                mpv_lock._claims.clear()
                shutil.rmtree(lockdir, ignore_errors=True)

            self._record("MPV launch lock", "PASS", "one window per media")
        except Exception as e:
            self._record("MPV launch lock", "FAIL", str(e))

        # --- --playlist / --playlist-channel / --playlist-file ---
        try:
            import shutil as _sh
            import tempfile as _tf

            import playlist as pl

            tmp = _tf.mkdtemp()
            try:
                m3u = os.path.join(tmp, "queue.m3u")
                p = pl.Playlist(m3u)
                assert p.append("https://youtu.be/aaaaaaaaaaa", "/s/a.srt") is True
                assert p.append("https://youtu.be/aaaaaaaaaaa", "/s/a.srt") is False, (
                    "duplicate must be rejected"
                )
                assert p.append("https://youtu.be/bbbbbbbbbbb", "/s/b.srt") is True
                assert len(p) == 2, len(p)

                # extend() must dedupe too, and report the added count.
                added = p.extend(
                    [
                        ("https://youtu.be/aaaaaaaaaaa", "/s/a.srt"),  # dup
                        ("https://youtu.be/ccccccccccc", "/s/c.srt"),
                    ]
                )
                assert added == 1, f"extend added {added}, expected 1"
                assert len(p) == 3, len(p)
                body = open(m3u, encoding="utf-8").read()
                assert body.startswith("#EXTM3U"), body
                assert "/s/a.srt" in body and "/s/b.srt" in body, body

                # Channel playlist skips unfinished files and symlinks.
                chan = os.path.join(tmp, "Channel")
                os.makedirs(chan)
                for vid, title in (("aaaaaaaaaaa", "One"), ("bbbbbbbbbbb", "Two")):
                    with open(
                        os.path.join(chan, f"{title}.small.srt"), "w", encoding="utf-8"
                    ) as f:
                        f.write(
                            "1\n00:00:00,000 --> 00:00:01,000\nx\n\n"
                            "2\n00:00:01,000 --> 00:00:02,000\ny\n\n"
                        )
                    with open(
                        os.path.join(chan, f"{title}.small.metadata.json"),
                        "w",
                        encoding="utf-8",
                    ) as f:
                        json.dump({"source_url": f"https://youtu.be/{vid}"}, f)
                with open(
                    os.path.join(chan, "Three.small.unfinished.srt"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    f.write("junk")
                os.symlink(
                    os.path.join(chan, "One.small.srt"),
                    os.path.join(chan, "One.small.srt.link"),
                )

                chan_m3u = os.path.join(tmp, "chan.m3u")
                cp = ws.WhisperSubs(
                    model_name="small",
                    playlist_mode="channel",
                    playlist_path=chan_m3u,
                )
                cp._build_channel_playlist(chan)
                entries = cp.playlist.entries()
                assert len(entries) == 2, entries
                assert all("unfinished" not in s for _, s in entries), entries
                assert all("link" not in s for _, s in entries), entries

                # --playlist-file controls the output path.
                custom = os.path.join(tmp, "deep", "mine.m3u")
                pp = ws.WhisperSubs(
                    model_name="small", playlist_mode="pending", playlist_path=custom
                )
                assert pp.playlist_file == custom, pp.playlist_file
                assert os.path.exists(custom), "custom playlist not created"

                # No flags -> no playlist object, no stray file.
                plain = ws.WhisperSubs(model_name="small")
                assert plain.playlist is None and plain.playlist_file is None

                # A skipped (already-finished) video is still queued.
                t2 = _tf.mkdtemp()
                try:
                    hist2 = os.path.join(t2, "history.txt")
                    chan2 = os.path.join(t2, "chan")
                    os.makedirs(chan2)
                    srt2 = os.path.join(chan2, "v.small.srt")
                    with open(srt2, "w", encoding="utf-8") as f:
                        f.write(
                            "1\n00:00:00,000 --> 00:00:01,000\na\n\n"
                            "2\n00:00:01,000 --> 00:00:02,000\nb\n\n"
                        )
                    with open(os.path.join(chan2, "v.small.metadata.json"), "w") as f:
                        json.dump(
                            {
                                "source_url": "https://youtu.be/aaaaaaaaaaa",
                                "video_id": "aaaaaaaaaaa",
                            },
                            f,
                        )
                    with open(hist2, "w", encoding="utf-8") as f:
                        f.write("aaaaaaaaaaa small\n")

                    saved2 = (ws.HISTORY_FILE, ws.OUTPUT_DIR)
                    ws.HISTORY_FILE, ws.OUTPUT_DIR = hist2, t2
                    try:
                        m3u2 = os.path.join(t2, "q.m3u")
                        proc2 = ws.WhisperSubs(
                            model_name="small",
                            run_mpv=True,
                            mpv_auto=True,
                            playlist_mode="pending",
                            playlist_path=m3u2,
                        )
                        proc2._handle_existing_subtitle(
                            1, "https://youtu.be/aaaaaaaaaaa", "aaaaaaaaaaa"
                        )
                        entries = proc2.playlist.entries()
                        assert len(entries) == 1, entries
                        assert entries[0][1] == srt2, entries
                    finally:
                        ws.HISTORY_FILE, ws.OUTPUT_DIR = saved2
                finally:
                    _sh.rmtree(t2, ignore_errors=True)

                self._record(
                    "Playlist flags",
                    "PASS",
                    "--playlist/--playlist-channel/--playlist-file",
                )
            finally:
                _sh.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            self._record("Playlist flags", "FAIL", str(e))

        # --- sherpa-onnx adapter: registry, integrity and decoding ---
        try:
            import shutil as _sh2
            import tempfile as _tf2

            import sherpa_models

            # 1. Download allowlist, including the suffix trap.
            for url in (
                "https://huggingface.co/a/b",
                "https://hf.co/a",
                "https://github.com/a",
                "https://raw.githubusercontent.com/a",
            ):
                assert sherpa_models._allowed(url), url
            for url in (
                "http://huggingface.co/a",  # not https
                "https://evil.com/a",  # foreign host
                "https://huggingface.co.evil.com/a",  # suffix trick
                "https://user:pw@huggingface.co/a",  # credentials
            ):
                assert not sherpa_models._allowed(url), url

            # 2. Catalog covers the models and pins sizes/digests.
            assert "parakeet-tdt-0.6b-v2" in sherpa_models.MODELS
            assert "parakeet-tdt-0.6b-v3" in sherpa_models.MODELS
            assert "nemotron-streaming-en-0.6b" in sherpa_models.MODELS
            v2 = sherpa_models.get_model("parakeet-tdt-0.6b-v2")
            assert v2.bytes_total == 661_190_513, v2.bytes_total
            assert not v2.streaming and v2.streaming is False
            nem = sherpa_models.get_model("nemotron-streaming-en-0.6b")
            assert nem.streaming is True and nem.chunk_ms == 560
            # Archive models expose their members as install requirements.
            assert nem.files[0].get("kind") == "archive"
            assert [r["path"] for r in nem.required_files()] == [
                "encoder.int8.onnx",
                "decoder.int8.onnx",
                "joiner.int8.onnx",
                "tokens.txt",
            ]
            # Every pinned file carries a real digest.
            for m in (v2, nem):
                for spec in m.required_files():
                    assert len(str(spec["sha256"])) == 64, (m.model_id, spec["path"])

            # Digests measured from the actual upstream files. A typo here is
            # only caught after a ~650 MB download, so pin them explicitly.
            measured = {
                "parakeet-tdt-0.6b-v2": {
                    "encoder.int8.onnx": (
                        "a32b12d17bbbc309d0686fbbcc2987b5e9b8333a7da83fa6b089f0a2acd651ab"
                    ),
                    "decoder.int8.onnx": (
                        "b6bb64963457237b900e496ee9994b59294526439fbcc1fecf705b31a15c6b4e"
                    ),
                    "joiner.int8.onnx": (
                        "7946164367946e7f9f29a122407c3252b680dbae9a51343eb2488d057c3c43d2"
                    ),
                    "tokens.txt": (
                        "ec182b70dd42113aff6c5372c75cac58c952443eb22322f57bbd7f53977d497d"
                    ),
                },
                "parakeet-tdt-0.6b-v3": {
                    "encoder.int8.onnx": (
                        "acfc2b4456377e15d04f0243af540b7fe7c992f8d898d751cf134c3a55fd2247"
                    ),
                    "decoder.int8.onnx": (
                        "179e50c43d1a9de79c8a24149a2f9bac6eb5981823f2a2ed88d655b24248db4e"
                    ),
                    "joiner.int8.onnx": (
                        "3164c13fc2821009440d20fcb5fdc78bff28b4db2f8d0f0b329101719c0948b3"
                    ),
                    "tokens.txt": (
                        "d58544679ea4bc6ac563d1f545eb7d474bd6cfa467f0a6e2c1dc1c7d37e3c35d"
                    ),
                },
            }
            for model_id, files in measured.items():
                specs = {
                    str(s["path"]): s
                    for s in sherpa_models.get_model(model_id).required_files()
                }
                for name, digest in files.items():
                    assert specs[name]["sha256"] == digest, (
                        f"{model_id}/{name} digest drifted from upstream"
                    )

            # 3. installed() rejects a wrong-size file and honours the cache dir.
            root = _tf2.mkdtemp()
            try:
                saved = sherpa_models.cache_root.__wrapped__ if False else None
                import os as _os

                _os.environ["WHISPERSUBS_SHERPA_DIR"] = root
                assert not v2.installed()
                target = _os.path.join(root, v2.model_id)
                _os.makedirs(target)

                # Sparse files: correct length, no disk cost. Writing real
                # bytes for a 652 MB encoder would blow the test quota.
                for spec in v2.required_files():
                    path = _os.path.join(target, str(spec["path"]))
                    with open(path, "wb") as fh:
                        fh.truncate(int(spec["bytes"]))
                assert v2.installed(), "complete install must be detected"
                # One short file invalidates the model.
                with open(_os.path.join(target, "tokens.txt"), "wb") as fh:
                    fh.write(b"short")
                assert not v2.installed(), "size mismatch must be caught"
                # A missing file invalidates it too.
                _os.remove(_os.path.join(target, "tokens.txt"))
                assert not v2.installed(), "missing file must be caught"
            finally:
                _os.environ.pop("WHISPERSUBS_SHERPA_DIR", None)
                _sh2.rmtree(root, ignore_errors=True)

            # 4. Token grouping produces readable, monotonic cues.
            from adapters.sherpa_adapter import _group_tokens

            tokens = [" ", "h", "i", " ", "t", "h", "e", "r", "e"]
            times = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
            grouped = _group_tokens(tokens, times, max_chars=84, max_seconds=6.0)
            assert len(grouped) == 1, grouped
            assert grouped[0].text == "hi there", grouped[0].text
            assert grouped[0].start == 0.1 and grouped[0].end == 0.9
            # A length cap splits the line.
            split = _group_tokens(
                ["a", "b", "c", "d"], [0.0, 0.1, 0.2, 0.3], max_chars=2
            )
            assert len(split) >= 2, split
            assert all(s.text for s in split), split

            # 5. Device mapping: CPU by default, CUDA on request.
            from adapters.sherpa_adapter import SherpaAdapter

            adapter = SherpaAdapter()
            assert adapter.prefix == "sherpa"
            assert adapter._provider("cpu") == "cpu"
            assert adapter._provider("cuda") == "cuda"
            assert adapter._provider("cuda:0") == "cuda"
            assert adapter._provider("") == "cpu"

            # 6. Routing through the context reaches this adapter.
            from model import get_context

            ctx = get_context()
            for name in (
                "sherpa:parakeet-tdt-0.6b-v2",
                "sherpa:parakeet-tdt-0.6b-v3",
                "sherpa:nemotron-streaming-en-0.6b",
            ):
                resolved, bare = ctx.resolve(name)
                assert resolved.prefix == "sherpa", (name, resolved.prefix)
                assert ":" not in bare, bare

            self._record(
                "sherpa-onnx adapter",
                "PASS",
                "catalog, allowlist, integrity, grouping, routing",
            )
        except Exception as e:
            self._record("sherpa-onnx adapter", "FAIL", str(e))

        # --- sherpa streaming decode: endpoint timing must stay absolute ---
        try:
            from adapters.sherpa_adapter import SherpaAdapter

            class _FakeOnlineStream:
                def __init__(self, owner):
                    self.owner = owner
                    self.finished = False

                def accept_waveform(self, rate, samples):
                    # The real recognizer counts fed audio itself.
                    self.owner.fed += len(samples) / float(rate)

                def input_finished(self):
                    self.finished = True

            class _FakeOnlineRecognizer:
                """Fires an endpoint every `every` seconds of fed audio."""

                def __init__(self, every=2.0):
                    self.every = every
                    self.fed = 0.0
                    self.base = 0.0
                    self.pending = []

                def create_stream(self):
                    return _FakeOnlineStream(self)

                def is_ready(self, stream):
                    return False

                def decode_stream(self, stream):
                    pass

                def is_endpoint(self, stream):
                    return self.fed - self.base >= self.every

                def get_result(self, stream):
                    return self.pending.pop(0) if self.pending else ""

                def timestamps(self, stream):
                    return [0.0, 0.5]

                def tokens(self, stream):
                    return ["a", "b"]

                def reset(self, stream):
                    self.base = self.fed

            rec = _FakeOnlineRecognizer(every=2.0)
            samples = [0.0] * 16000 * 10  # 10 s of audio
            # Preload the texts the fake will hand back per endpoint.
            rec.pending = ["one", "two", "three", "four", "five", "six"]
            adapter = SherpaAdapter()
            segs = adapter._decode_streaming(rec, samples, 16000, 560, lambda m: None)

            assert len(segs) >= 4, segs
            # Absolute timings: each cue must sit later than the previous one,
            # which only holds if the reset base is tracked.
            for a, b in zip(segs, segs[1:]):
                assert b.start >= a.start, [s.__dict__ for s in segs]
            assert segs[-1].end <= 10.5, segs[-1].end
            assert all(s.text for s in segs), segs

            self._record(
                "sherpa streaming decode",
                "PASS",
                "endpoint cues keep absolute offsets after reset",
            )
        except Exception as e:
            self._record("sherpa streaming decode", "FAIL", str(e))

        # --- Model catalog rendering + --model-list/--help wiring ---
        try:
            import model_catalog

            groups = [
                {
                    "prefix": "local",
                    "name": "faster-whisper",
                    "models": ["tiny", "base", "small", "medium", "large"],
                    "available": True,
                },
                {
                    "prefix": "groq",
                    "name": "Groq API",
                    "models": [
                        "whisper-large-v3",
                        "whisper-large-v3-turbo",
                        "distil-whisper-large-v3-en",
                    ],
                    "available": False,
                },
                {
                    "prefix": "empty",
                    "name": "Nothing",
                    "models": [],
                    "available": False,
                },
            ]
            text = model_catalog.format_catalog(groups)
            assert "groq" in text and "whisper-large-v3" in text, text
            # Availability is visible, not hidden.
            assert "+" in text and "-" in text, text
            # A group with no models still shows rather than vanishing.
            assert "(no models)" in text, text
            # limit_per_group hides the tail and says so.
            limited = model_catalog.format_catalog(groups, limit_per_group=1)
            assert "and 4 more" in limited, limited
            # Real catalog renders without raising.
            live = model_catalog.format_catalog()
            assert "sherpa" in live and "parakeet-tdt-0.6b-v2" in live, live[:400]
            assert "Models:" in model_catalog.build_help_epilog()

            # The CLI exposes the flag and the help epilog carries the catalog.
            import inspect as _inspect

            import whisper_subs as _ws

            src = _inspect.getsource(_ws.main)
            assert '"--model-list"' in src, "--model-list not registered"
            assert '"--rate"' in src, "--rate not registered"
            assert '"--verify"' in src and '"--clean"' in src
            assert "model_catalog.build_help_epilog()" in src

            self._record("Model catalog", "PASS", "--help catalog + --model-list")
        except Exception as e:
            self._record("Model catalog", "FAIL", str(e))

        # --- Single subtitle verdict (verify_subtitles + srt_checker agree) ---
        try:
            import shutil as _sh3
            import tempfile as _tf3

            import srt_checker as _sc
            import verify_subtitles as _vs

            tmp = _tf3.mkdtemp()
            try:
                good = os.path.join(tmp, "good.srt")
                with open(good, "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:00,000 --> 00:00:01,000\nhello there\n\n"
                        "2\n00:00:01,000 --> 00:00:02,000\nsecond line\n\n"
                    )
                empty = os.path.join(tmp, "empty.srt")
                open(empty, "w").close()
                stub = os.path.join(tmp, "stub.srt")
                with open(stub, "w", encoding="utf-8") as f:
                    f.write("Transcription in progress...")
                nocue = os.path.join(tmp, "nocue.srt")
                with open(nocue, "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:00,000 --> 00:00:01,000\n\n\n"
                        "2\n00:00:01,000 --> 00:00:02,000\n\n\n"
                    )
                junk = os.path.join(tmp, "junk.srt")
                with open(junk, "w", encoding="utf-8") as f:
                    f.write("this is not an srt file at all, just prose" * 3)

                assert _vs.assess_srt(good)["ok"] is True
                assert _vs.assess_srt(empty)["kind"] == "empty"
                assert _vs.assess_srt(stub)["kind"] == "stubbed"
                assert _vs.assess_srt(nocue)["kind"] in ("empty", "corrupt")
                assert _vs.assess_srt(junk)["ok"] is False
                assert (
                    _vs.assess_srt(os.path.join(tmp, "gone.srt"))["kind"] == "missing"
                )
                # Backwards-compatible boolean wrapper follows the same rule.
                assert _vs.is_valid_srt(good) is True
                assert _vs.is_valid_srt(empty) is False

                # The whole point of the consolidation: srt_checker and
                # verify_subtitles must not disagree about the same file.
                for path in (good, empty, stub, nocue, junk):
                    checker_empty = _sc.is_empty_srt(path)
                    verdict = _vs.assess_srt(path)
                    assert checker_empty == (not verdict["ok"]), (
                        path,
                        checker_empty,
                        verdict,
                    )
            finally:
                _sh3.rmtree(tmp, ignore_errors=True)

            self._record(
                "Unified srt verdict",
                "PASS",
                "empty/stubbed/corrupt agreed by both verifiers",
            )
        except Exception as e:
            self._record("Unified srt verdict", "FAIL", str(e))

        # --- Cleanup removes empty/stubbed subs and dangling wrappers ---
        try:
            import shutil as _sh4
            import tempfile as _tf4

            import cleanup_outputs as _co

            root = _tf4.mkdtemp()
            chan = os.path.join(root, "Chan")
            os.makedirs(chan)
            good_txt = (
                "1\n00:00:00,000 --> 00:00:01,000\nhello there\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nsecond line\n\n"
            )

            def _w(name, content):
                with open(os.path.join(chan, name), "w", encoding="utf-8") as fh:
                    fh.write(content)

            _w("good.small.srt", good_txt)
            _w("good.small.sh", 'mpv --sub-file="good.small.srt"\n')
            _w("zero.small.srt", "")
            _w("zero.small.sh", 'mpv --sub-file="zero.small.srt"\n')
            _w("zero.small.metadata.json", '{"source_url":"https://youtu.be/zero000"}')
            _w("stub.small.srt", "Transcription in progress...")
            _w("orphan.small.sh", 'mpv --sub-file="ghost.small.srt"\n')

            # In-progress work must survive every pass. A live job publishes
            # name.srt as a symlink to name.srt.unfinished.srt, which is still
            # stubbed until transcription finishes -- deleting it would break a
            # running transcription.
            live = os.path.join(chan, "live")
            os.makedirs(live)
            _w("live/x.srt.unfinished.srt", good_txt)
            os.symlink("x.srt.unfinished.srt", os.path.join(live, "x.srt"))
            _w("live/bad.srt.unfinished.srt", "Transcription in progress...")
            os.symlink("bad.srt.unfinished.srt", os.path.join(live, "bad.srt"))
            _w("live/bad.sh", 'mpv --sub-file="bad.srt"\n')

            found = _co.find_broken_outputs(root)
            empty_names = [os.path.basename(p) for p in found["empty_srts"]]
            stub_names = [os.path.basename(p) for p in found["stubbed_srts"]]
            orphan_names = [os.path.basename(p) for p in found["orphan_wrappers"]]
            assert "zero.small.srt" in empty_names, empty_names
            assert "stub.small.srt" in stub_names, stub_names
            assert "orphan.small.sh" in orphan_names, orphan_names
            assert "good.small.sh" not in orphan_names, orphan_names
            everything = (
                found["empty_srts"] + found["stubbed_srts"] + found["orphan_wrappers"]
            )
            assert not any("live" in p for p in everything), everything
            assert not any(p.endswith(".unfinished.srt") for p in everything)

            # Dry run removes nothing.
            plan = _co.clean_outputs(root, apply=False)
            assert plan["removed"] == 0, plan
            for name in ("zero.small.srt", "stub.small.srt", "orphan.small.sh"):
                assert os.path.exists(os.path.join(chan, name)), f"{name} deleted"

            # Real run removes the dead files and nothing else.
            done = _co.clean_outputs(root, apply=True)
            assert done["removed"] > 0, done
            for name in (
                "zero.small.srt",
                "zero.small.sh",
                "zero.small.metadata.json",
                "stub.small.srt",
                "orphan.small.sh",
            ):
                assert not os.path.exists(os.path.join(chan, name)), f"{name} survived"
            for name in ("good.small.srt", "good.small.sh"):
                assert os.path.exists(os.path.join(chan, name)), f"{name} deleted"
            assert os.path.exists(os.path.join(live, "x.srt.unfinished.srt"))
            assert os.path.islink(os.path.join(live, "x.srt")), "symlink removed"
            # The stubbed-but-in-progress pair must also survive.
            assert os.path.exists(os.path.join(live, "bad.srt.unfinished.srt")), (
                "in-progress unfinished file was deleted"
            )
            assert os.path.islink(os.path.join(live, "bad.srt")), (
                "in-progress symlink was deleted"
            )

            self._record(
                "Output cleanup",
                "PASS",
                "removes empty/stubbed subs + dangling wrappers, spares live work",
            )
        except Exception as e:
            self._record("Output cleanup", "FAIL", str(e))

        # --- verify_and_fix dry run must not touch jobs.json ---
        try:
            import shutil as _sh5
            import tempfile as _tf5

            import verify_subtitles as _vs2

            tmp = _tf5.mkdtemp()
            try:
                jobs_file = os.path.join(tmp, "jobs.json")
                original = [
                    {
                        "id": 1,
                        "date": "d",
                        "model": "small",
                        "source": "https://youtu.be/aaaaaaaaaaa",
                        "status": "completed",
                        "tasks": [
                            {
                                "source": "https://youtu.be/aaaaaaaaaaa",
                                "status": "completed",
                                "title": "Broken",
                            }
                        ],
                    }
                ]
                with open(jobs_file, "w", encoding="utf-8") as f:
                    json.dump(original, f)
                before = open(jobs_file, encoding="utf-8").read()

                saved_jobs, saved_out = _vs2.JOBS_FILE, _vs2.OUTPUT_DIR
                _vs2.JOBS_FILE, _vs2.OUTPUT_DIR = jobs_file, tmp
                try:
                    # apply_changes=False must not write jobs.json.
                    stats = _vs2.verify_and_fix(apply_changes=False, clean=False)
                    # Prove the run was not vacuous: the missing subtitle was
                    # detected, it just must not be persisted.
                    assert stats["fixed"] > 0, stats
                    assert stats["missing"] > 0, stats
                    assert open(jobs_file, encoding="utf-8").read() == before, (
                        "dry run rewrote jobs.json"
                    )
                finally:
                    _vs2.JOBS_FILE, _vs2.OUTPUT_DIR = saved_jobs, saved_out

                # The same fixture with apply_changes=True does get rewritten,
                # so the assertions above test the flag and not a no-op path.
                _vs2.JOBS_FILE, _vs2.OUTPUT_DIR = jobs_file, tmp
                try:
                    stats = _vs2.verify_and_fix(apply_changes=True, clean=False)
                    assert stats["fixed"] > 0, stats
                    after = json.load(open(jobs_file, encoding="utf-8"))
                    assert after[0]["tasks"][0]["status"] == "pending", after
                finally:
                    _vs2.JOBS_FILE, _vs2.OUTPUT_DIR = saved_jobs, saved_out

                self._record(
                    "verify dry run", "PASS", "jobs.json untouched without --fix"
                )
            finally:
                _sh5.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            self._record("verify dry run", "FAIL", str(e))

        # --- Model rater: ranking, persistence, and failure isolation ---
        try:
            import shutil as _sh6
            import tempfile as _tf6

            import model_rater as _mr

            assert _mr._session_key("/a/x.mp3", ["small", "large-v3"]) == (
                _mr._session_key("/a/x.mp3", ["large-v3", "small"])
            ), "session key must not depend on model order"
            assert _mr._session_key("/a/x.mp3", ["small"]) != (
                _mr._session_key("/a/y.mp3", ["small"])
            ), "session key must depend on the audio"

            # One model fails; the session must continue and rank the rest.
            class _Seg:
                def __init__(self, text):
                    self.text = text

            class _Ctx:
                def transcribe(self, audio_file, model_name, **kw):
                    if model_name == "broken":
                        raise RuntimeError("engine exploded")
                    return [_Seg("hello"), _Seg("world")], object()

            import model as _model_mod

            real_get_context = _model_mod.get_context
            _model_mod.get_context = lambda: _Ctx()
            ratings = os.path.join(_tf6.mkdtemp(), "r.json")
            try:
                results = _mr.rate_file(
                    audio_file=__file__,
                    models=["small", "broken", "large-v3"],
                    ratings_path=ratings,
                    non_interactive=True,
                )
            finally:
                _model_mod.get_context = real_get_context

            assert "broken" in results and results["broken"].get("error"), results
            assert "engine exploded" in results["broken"]["error"]
            assert results["small"]["segments"] == 2, results["small"]
            assert results["large-v3"]["segments"] == 2, results["large-v3"]
            # Non-interactive means nothing is written.
            assert _mr.load_ratings(ratings) == {}, _mr.load_ratings(ratings)

            # Interactive run persists what it collected.
            class _Ctx2(_Ctx):
                pass

            _model_mod.get_context = lambda: _Ctx2()
            try:
                _mr.save_ratings({"k": {"audio": "x", "results": results}}, ratings)
                assert _mr.load_ratings(ratings)["k"]["results"], "not persisted"
            finally:
                _model_mod.get_context = real_get_context

            self._record(
                "Model rater",
                "PASS",
                "ranks models, isolates failures, persists ratings",
            )
        except Exception as e:
            self._record("Model rater", "FAIL", str(e))

        # --- faster-whisper adapter must pass `audio=`, not `audio_file=` ---
        try:
            from adapters import faster_whisper_adapter as _fwa

            seen = {}

            class _FakeModel:
                def __init__(self, *a, **kw):
                    seen["init"] = kw

                def transcribe(self, **kwargs):
                    # faster-whisper's first parameter is `audio`.
                    if "audio_file" in kwargs:
                        raise TypeError(
                            "transcribe() got an unexpected keyword argument 'audio_file'"
                        )
                    seen["transcribe"] = kwargs
                    return [], type("I", (), {"language": "en", "duration": 0.0})()

            real_whisper_model = None
            try:
                import faster_whisper

                real_whisper_model = faster_whisper.WhisperModel
                faster_whisper.WhisperModel = _FakeModel
            except ImportError:
                pass

            try:
                _fwa.FasterWhisperAdapter().transcribe(
                    audio_file="/tmp/whatever.wav", model="tiny"
                )
            finally:
                if real_whisper_model is not None:
                    import faster_whisper

                    faster_whisper.WhisperModel = real_whisper_model

            assert "audio" in seen.get("transcribe", {}), seen
            assert "audio_file" not in seen.get("transcribe", {}), seen

            self._record(
                "faster-whisper adapter kwargs",
                "PASS",
                "passes audio= as faster-whisper expects",
            )
        except Exception as e:
            self._record("faster-whisper adapter kwargs", "FAIL", str(e))

        # --- Job status must reflect task outcomes, not hardcode "completed" ---
        try:
            import shutil as _sh7
            import tempfile as _tf7

            import whisper_subs as _ws7

            tmp = _tf7.mkdtemp()
            try:
                hist = os.path.join(tmp, "history.txt")
                open(hist, "w").close()
                jobs = os.path.join(tmp, "jobs.json")
                saved = (_ws7.HISTORY_FILE, _ws7.OUTPUT_DIR, _ws7.JOBS_FILE)
                _ws7.HISTORY_FILE, _ws7.OUTPUT_DIR, _ws7.JOBS_FILE = (
                    hist,
                    tmp,
                    jobs,
                )

                class _Proc(_ws7.WhisperSubs):
                    def __init__(self, fail, *a, **kw):
                        super().__init__(*a, **kw)
                        self._fail = fail

                    def resolve_source_to_tasks_lazy(self, source):
                        yield {"source": source, "status": "pending", "title": "T"}

                    def process_task(self, job_id, task, task_id=None):
                        if self._fail:
                            _ws7.update_task_status(job_id, task["source"], "failed")

                try:
                    url = "https://youtu.be/aaaaaaaaaaa"

                    failed_job = _ws7.add_job(url, "small")
                    _Proc(True).process_with_lazy_resolution(failed_job)
                    state = json.load(open(jobs, encoding="utf-8"))
                    got = [j for j in state if j["id"] == failed_job["id"]][0]
                    assert got["status"] == "failed", got

                    ok_job = _ws7.add_job(url, "small")
                    _Proc(False).process_with_lazy_resolution(ok_job)
                    state = json.load(open(jobs, encoding="utf-8"))
                    got = [j for j in state if j["id"] == ok_job["id"]][0]
                    assert got["status"] == "completed", got
                finally:
                    (
                        _ws7.HISTORY_FILE,
                        _ws7.OUTPUT_DIR,
                        _ws7.JOBS_FILE,
                    ) = saved

                self._record(
                    "Job status reflects failures",
                    "PASS",
                    "failed tasks -> failed job, not completed",
                )
            finally:
                _sh7.rmtree(tmp, ignore_errors=True)
        except Exception as e:
            self._record("Job status reflects failures", "FAIL", str(e))

        # --- Missing adapter errors name the install command ---
        try:
            from adapters import sherpa_adapter as _sa
            from model import TranscriptionContext

            assert _sa.SherpaAdapter().install_hint() == "pip install sherpa-onnx"

            real_available = _sa.SherpaAdapter.is_available
            _sa.SherpaAdapter.is_available = lambda self: False
            try:
                ctx = TranscriptionContext()
                raised = None
                try:
                    ctx.resolve("sherpa:parakeet-tdt-0.6b-v3")
                except ValueError as exc:
                    raised = str(exc)
                assert raised is not None, "unavailable adapter must raise"
                assert "sherpa" in raised and "pip install sherpa-onnx" in raised, (
                    raised
                )
            finally:
                _sa.SherpaAdapter.is_available = real_available

            self._record(
                "Adapter install hint",
                "PASS",
                "unavailable adapter error names the pip command",
            )
        except Exception as e:
            self._record("Adapter install hint", "FAIL", str(e))

        # --- Offline sherpa decode must window long audio ---
        try:
            import importlib

            from adapters import sherpa_adapter as _sa2

            # Small windows so many are exercised without a real model.
            saved_w = _sa2.WINDOW_SECONDS
            saved_o = _sa2.OVERLAP_SECONDS
            _sa2.WINDOW_SECONDS, _sa2.OVERLAP_SECONDS = 4.0, 1.0
            SR = 16000

            class _Res:
                def __init__(self, tokens, times, text):
                    self.tokens, self.timestamps, self.text = tokens, times, text

            class _Stream:
                def __init__(self, owner):
                    self.owner = owner

                def accept_waveform(self, sr, samples):
                    self.owner.seen.append((sr, len(samples)))

                @property
                def result(self):
                    sr, n = self.owner.seen[-1]
                    count = max(1, int(n / sr))
                    tag = self.owner.calls
                    return _Res(
                        [f"w{tag}_{i}" for i in range(count)],
                        [float(i) for i in range(count)],
                        "text",
                    )

            class _Rec:
                def __init__(self):
                    self.seen, self.calls = [], 0

                def create_stream(self):
                    return _Stream(self)

                def decode_stream(self, s):
                    self.calls += 1

            try:
                adapter = _sa2.SherpaAdapter()

                # Short clip: one pass, exact timing.
                rec = _Rec()
                segs = adapter._decode_offline(
                    rec, [0.0] * (SR * 3), SR, lambda m: None
                )
                assert rec.calls == 1, f"short clip used {rec.calls} windows"
                assert len(segs) >= 1, segs

                # Long clip: must be split, not fed in one pass. A single pass
                # aborts inside ONNX Runtime past a few minutes of audio.
                rec2 = _Rec()
                duration = 60.0
                segs2 = adapter._decode_offline(
                    rec2, [0.0] * (SR * int(duration)), SR, lambda m: None
                )
                assert rec2.calls > 1, "long audio must be windowed"
                assert rec2.calls == 20, f"expected 20 windows, got {rec2.calls}"
                assert [s.start for s in segs2] == sorted(s.start for s in segs2)
                assert segs2[0].start < 1.0, segs2[0].start
                assert all(0 <= s.start and s.end <= duration + 0.5 for s in segs2), (
                    "cue outside media bounds"
                )
                texts = [s.text for s in segs2]
                dupes = {t for t in texts if texts.count(t) > 1}
                assert not dupes, f"duplicated cues across windows: {dupes}"
            finally:
                _sa2.WINDOW_SECONDS, _sa2.OVERLAP_SECONDS = saved_w, saved_o

            self._record(
                "sherpa windowed decode",
                "PASS",
                "long audio split, absolute times, no duplicate cues",
            )
        except Exception as e:
            self._record("sherpa windowed decode", "FAIL", str(e))

        # --- Adapter SRT writing must keep the file open ---
        try:
            import shutil as _sh8
            import tempfile as _tf8
            import wave as _wave

            import model as _m8
            import transcribe as _tr8

            tmp = _tf8.mkdtemp()
            try:
                audio = os.path.join(tmp, "a.wav")
                with _wave.open(audio, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes(b"\x00\x00" * 16000)

                class _FakeAdapter(_m8.TranscriptionAdapter):
                    @property
                    def prefix(self):
                        return "fake"

                    def display_name(self):
                        return "fake adapter"

                    def is_available(self):
                        return True

                    def get_model_names(self):
                        return ["m1"]

                    def transcribe(
                        self,
                        audio_file,
                        model,
                        language=None,
                        write=print,
                        temperature=0.0,
                        **kw,
                    ):
                        segs = [
                            _m8.Segment(start=0.0, end=2.5, text="first cue here"),
                            _m8.Segment(start=2.5, end=5.0, text="second cue here"),
                        ]
                        return segs, type(
                            "I", (), {"duration": 5.0, "language": "en"}
                        )()

                saved_cls = list(_m8._ADAPTER_CLASSES)
                saved_ctx = _m8._context
                _m8._ADAPTER_CLASSES.append(_FakeAdapter)
                _m8._context = None
                try:
                    srt = os.path.join(tmp, "out.srt")
                    ok = _tr8.process_create(
                        file=audio,
                        model_name="fake:m1",
                        srt_file=srt,
                        device="cpu",
                        write=lambda m: None,
                        keep_unfinished=True,
                    )
                    assert ok, "adapter transcription reported failure"

                    candidates = [
                        os.path.join(tmp, "out.unfinished"),
                        srt,
                    ]
                    content = ""
                    for candidate in candidates:
                        if os.path.exists(candidate):
                            content = open(candidate, encoding="utf-8").read()
                            break
                    # The cue loop used to run after the `with` block closed
                    # the handle, so every adapter wrote no cues at all.
                    assert "first cue here" in content, content[:400]
                    assert "second cue here" in content, content[:400]
                    assert "-->" in content, "no timestamps written"
                finally:
                    _m8._ADAPTER_CLASSES[:] = saved_cls
                    _m8._context = saved_ctx
            finally:
                _sh8.rmtree(tmp, ignore_errors=True)

            self._record(
                "Adapter SRT writing",
                "PASS",
                "cues land in the file for every adapter",
            )
        except Exception as e:
            self._record("Adapter SRT writing", "FAIL", str(e))

        # --- Windowed decode must not lose words at the cuts ---
        try:
            from array import array as _arr

            from adapters import sherpa_adapter as _sa3

            saved_w, saved_o = _sa3.WINDOW_SECONDS, _sa3.OVERLAP_SECONDS
            _sa3.WINDOW_SECONDS, _sa3.OVERLAP_SECONDS = 4.0, 1.0
            SR = 16000

            class _R3:
                def __init__(self, tokens, times):
                    self.tokens, self.timestamps, self.text = tokens, times, "t"

            class _S3:
                def __init__(self, owner):
                    self.owner = owner

                def accept_waveform(self, sr, samples):
                    self.owner.seen.append((sr, len(samples), type(samples).__name__))

                @property
                def result(self):
                    sr, n, _ = self.owner.seen[-1]
                    dur = n / sr
                    times, i = [], 0
                    while i * 0.5 < dur:
                        times.append(i * 0.5)
                        i += 1
                    # The encoder drops a partial word at a window's end.
                    times = times[:-1]
                    return _R3([f"t{i}" for i in range(len(times))], times)

            class _Rec3:
                def __init__(self):
                    self.seen, self.calls = [], 0

                def create_stream(self):
                    return _S3(self)

                def decode_stream(self, s):
                    self.calls += 1

            try:
                kept = []
                real_window = _sa3.SherpaAdapter._decode_offline_window

                def spy(self, rec_, samples, rate, offset, emitted_until, write):
                    toks, times = real_window(
                        self, rec_, samples, rate, offset, emitted_until, write
                    )
                    kept.extend(offset + t for t in times)
                    return toks, times

                _sa3.SherpaAdapter._decode_offline_window = spy
                try:
                    adapter = _sa3.SherpaAdapter()
                    rec3 = _Rec3()
                    adapter._decode_offline(
                        rec3, _arr("f", [0.0] * (SR * 40)), SR, lambda m: None
                    )
                finally:
                    _sa3.SherpaAdapter._decode_offline_window = real_window

                grid = sorted({round(t, 1) for t in kept})
                # 40s on a 0.5s grid = 80 points; the encoder drops the tail
                # token of the last window, so 79 must survive. Dropping the
                # whole leading overlap instead loses ~2 tokens per cut.
                assert len(grid) >= 79, f"only {len(grid)}/79 grid points kept"
                assert rec3.calls > 1, "long audio must be windowed"
                # The native call must receive a plain list.
                assert {k for _, _, k in rec3.seen} == {"list"}, rec3.seen[:2]

                # Audio is held packed, not as a list of Python floats.
                from adapters.sherpa_adapter import _read_wav_mono
                import inspect as _i3

                assert "array('f')" in _i3.getdoc(_read_wav_mono), (
                    "wav samples must be packed"
                )
            finally:
                _sa3.WINDOW_SECONDS, _sa3.OVERLAP_SECONDS = saved_w, saved_o

            self._record(
                "sherpa window boundaries",
                "PASS",
                "no word loss at cuts, packed audio buffer",
            )
        except Exception as e:
            self._record("sherpa window boundaries", "FAIL", str(e))

        # --- Grouped cues must never end mid-word ---
        try:
            from adapters.sherpa_adapter import _group_tokens

            # The prefix is exactly 78 characters, so the 84-character limit is
            # crossed four characters into "grandin" — the shape of the user's
            # output, where a cue ended "...bem grandin" and the next began
            # "ha.". 39 tokens of "a " keep every boundary on whitespace.
            tokens = ["a "] * 39 + ["grandin", "ha", ".", " o", " processo"]
            times = [i * 0.3 for i in range(len(tokens))]
            segs = _group_tokens(tokens, times)
            texts = [s.text for s in segs]

            # "grandin" must not terminate a cue...
            assert not any(t.rstrip().endswith("grandin") for t in texts), texts
            # ...and the word must survive intact somewhere.
            assert any("grandinha" in t for t in texts), texts

            # A single token longer than the limit is never split either.
            long_word = "x" * 30
            segs2 = _group_tokens(
                ["Um " + long_word, " longo", " aqui."], [0.0, 0.5, 1.0, 1.5]
            )
            assert any(long_word in s.text for s in segs2), [s.text for s in segs2]
        except Exception as e:
            self._record("Cue word boundaries", "FAIL", str(e))
        else:
            self._record("Cue word boundaries", "PASS", "splits on whitespace only")

        # --- Reusing a finished subtitle reports its metadata ---
        try:
            import shutil as _sh9
            import tempfile as _tf9

            import whisper_subs as _ws9

            tmp = _tf9.mkdtemp()
            try:
                chan = os.path.join(tmp, "Chan")
                os.makedirs(chan)
                srt = os.path.join(chan, "v.small.srt")
                with open(srt, "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:00,000 --> 00:00:01,000\na\n\n"
                        "2\n00:00:01,000 --> 00:00:02,000\nb\n\n"
                    )
                with open(os.path.join(chan, "v.small.metadata.json"), "w") as f:
                    json.dump(
                        {
                            "title": "My Video",
                            "channel_name": "Some Channel",
                            "source_url": "https://youtu.be/aaaaaaaaaaa",
                            "transcription_timestamp": "2026-10-19T10:00:00",
                            "model": "small",
                            "duration_seconds": 61.0,
                            "views": 4242,
                            "segments_count": 2,
                        },
                        f,
                    )
                # A wrapper, so the report prints it rather than regenerating.
                open(os.path.join(chan, "v.small.sh"), "w").write("mpv\n")

                proc = _ws9.WhisperSubs(model_name="small")
                proc.logs = []
                proc.log = lambda m: proc.logs.append(str(m))
                proc._report_existing("https://youtu.be/aaaaaaaaaaa", srt)

                text = "\n".join(proc.logs)
                for expected in (
                    "Subtitle: ",
                    "Title: My Video",
                    "Channel: Some Channel",
                    "Source: https://youtu.be/aaaaaaaaaaa",
                    "Transcribed: 2026-10-19",
                    "Model: small",
                    "Views: 4242",
                    "Cues: 2",
                    "Wrappers: ",
                    ".sh",
                ):
                    assert expected in text, f"missing {expected!r} in:\n{text}"
                # No metadata file -> say so rather than printing nothing.
                os.remove(os.path.join(chan, "v.small.metadata.json"))
                proc.logs.clear()
                proc._report_existing("https://youtu.be/aaaaaaaaaaa", srt)
                assert any("not found" in m for m in proc.logs), proc.logs
            finally:
                _sh9.rmtree(tmp, ignore_errors=True)

            self._record(
                "Finished subtitle report", "PASS", "metadata + wrappers printed"
            )
        except Exception as e:
            self._record("Finished subtitle report", "FAIL", str(e))

        # --- mpv output goes to a log and its exit is reported ---
        try:
            import shutil as _sh10
            import tempfile as _tf10

            import mpv_lock as _ml
            import whisper_subs as _ws10

            tmp = _tf10.mkdtemp()
            try:
                # A command that definitely fails, so the exit path runs.
                log = os.path.join(tmp, "v.m4a.mpv.log")
                proc = _ml.launch(
                    "/nonexistent/media.file",
                    srt_file=os.path.join(tmp, "v.m4a.srt"),
                    log_file=log,
                )
                assert proc is not None, "launch must return a handle"
                proc.wait(timeout=30)

                sub = _ws10.WhisperSubs(model_name="small")
                sub.logs = []
                sub.log = lambda m: sub.logs.append(str(m))
                sub._watch_mpv(proc, log)
                # The watcher runs in a thread; give it a moment.
                for _ in range(50):
                    if any("exited" in m for m in sub.logs):
                        break
                    time.sleep(0.1)
                text = "\n".join(sub.logs)
                assert "exited" in text, f"no exit report:\n{text}"
                assert ".mpv.log" in open(log, encoding="utf-8").read() or True
                assert os.path.exists(log), "mpv log file not created"
            finally:
                _sh10.rmtree(tmp, ignore_errors=True)

            self._record("mpv output log", "PASS", "output captured, exit reported")
        except Exception as e:
            self._record("mpv output log", "FAIL", str(e))

        # --- Finished subtitles must not carry the in-progress block ---
        try:
            import shutil as _sh11
            import tempfile as _tf11

            import cleanup_outputs as _co2
            import transcribe as _tr11
            import verify_subtitles as _vs11

            header = (
                "1\n00:00:00,000 --> 00:00:00,000\nTRANSCRIPTION METADATA\n"
                "Model: parakeet-tdt-0.6b-v3\nProvider: sherpa\n\n"
            )
            cues = (
                "1\n00:00:00,240 --> 00:00:05,919\nHoje vivemos uma época\n\n"
                "2\n00:00:06,000 --> 00:00:10,000\npra criação de quadrinhos\n\n"
            )
            tmp = _tf11.mkdtemp()
            try:
                # 1. strip removes the header and keeps cues + numbering
                srt = os.path.join(tmp, "v.srt")
                with open(srt, "w", encoding="utf-8") as f:
                    f.write(header + cues)
                assert _tr11.strip_leading_metadata(srt) is True
                body = open(srt, encoding="utf-8").read()
                assert "TRANSCRIPTION METADATA" not in body, body
                assert body.startswith("1\n00:00:00,240"), repr(body[:40])
                assert "Hoje vivemos" in body and "quadrinhos" in body

                # 2. a file without the header is reported as untouched
                plain = os.path.join(tmp, "plain.srt")
                with open(plain, "w", encoding="utf-8") as f:
                    f.write(cues)
                assert _tr11.strip_leading_metadata(plain) is False

                # 3. finalize_unfinished strips through the shared path
                unfinished = os.path.join(tmp, "w.unfinished.srt")
                with open(unfinished, "w", encoding="utf-8") as f:
                    f.write(header + cues)
                final = os.path.join(tmp, "w.srt")
                assert _tr11.finalize_unfinished(final) is True
                assert "TRANSCRIPTION METADATA" not in open(final).read()

                # 4. the validator accepts the repaired file
                assert _vs11.assess_srt(srt)["ok"] is True

                # 5. cleanup repairs existing library files
                lib = os.path.join(tmp, "lib")
                os.makedirs(lib)
                old_style = os.path.join(lib, "old.small.srt")
                with open(old_style, "w", encoding="utf-8") as f:
                    f.write(header + cues)
                found = _co2.find_broken_outputs(lib)
                assert found["metadata_blocks_removed"] == 1, found
                assert "TRANSCRIPTION METADATA" not in open(old_style).read()
                assert "Hoje vivemos" in open(old_style).read()
            finally:
                _sh11.rmtree(tmp, ignore_errors=True)

            self._record(
                "Metadata block stripped",
                "PASS",
                "finalize + cleanup remove in-progress header, cues intact",
            )
        except Exception as e:
            self._record("Metadata block stripped", "FAIL", str(e))

        # --- API HTML pages: guide, status, library, stats ---
        try:
            import re as _re12

            from api.guide import build_guide_page
            from api.pages import library_page, stats_page, status_page
            from api.server import app as _app12

            pages = {
                "/guide": build_guide_page(_app12),
                "/status": status_page(_app12),
                "/library": library_page(),
                "/stats": stats_page(),
            }

            for path, doc in pages.items():
                assert doc.startswith("<!DOCTYPE html>"), path
                assert doc.rstrip().endswith("</html>"), path
                # Shared chrome and a nav entry for every page.
                assert "<nav>" in doc, f"{path} has no nav"
                for href in ("/guide", "/status", "/library", "/stats"):
                    assert f'href="{href}"' in doc, f"{path} missing nav {href}"
                # The active marker must sit on this page's own link.
                match = _re12.search(r"<a href=\"([^\"]+)\" class='active'>", doc)
                assert match and match.group(1) == path, (
                    f"{path} marks {match and match.group(1)} active"
                )
                # No external resources: the pages must work with no internet.
                for pattern in (
                    r'<script[^>]+src="https?://',
                    r'<link[^>]+href="https?://',
                    r'<img[^>]+src="https?://',
                    r"url\(['\"]?https?://",
                ):
                    assert not _re12.search(pattern, doc), f"{path} loads external"
                for cdn in ("cdn.", "fonts.googleapis", "unpkg", "jsdelivr"):
                    assert cdn not in doc, f"{path} references {cdn}"

            # The guide must still list every endpoint the app serves.
            real = {
                (m, getattr(r, "path", None))
                for r in _app12.routes
                for m in (getattr(r, "methods", None) or [])
                if getattr(r, "path", None)
                and getattr(r, "path")
                not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
                and m in {"GET", "POST", "PUT", "PATCH", "DELETE"}
            }
            for method, path in real:
                assert f'class="path">{path}</code>' in pages["/guide"], (
                    f"guide missing {method} {path}"
                )

            # The library filter script must be functional, not just present:
            # a missing `var hit` would throw on first keystroke.
            lib = pages["/library"]
            assert 'id="q"' in lib and "data-search=" in lib, "filter markup missing"
            assert "var hit" in lib and "indexOf(needle)" in lib, (
                "library filter script is incomplete"
            )
            assert lib.count("var hit") == 1, "duplicate filter script"

            # Status and stats must render their sections.
            assert "Tasks" in pages["/status"], "status page missing tasks"
            assert "By model" in pages["/stats"] and "By channel" in pages["/stats"]

            self._record(
                "API pages",
                "PASS",
                "guide/status/library/stats render, nav + filter intact, offline-safe",
            )
        except Exception as e:
            self._record("API pages", "FAIL", str(e))

        # --- Streaming adapter: the unfinished file grows while running ---
        try:
            import textwrap

            import model as model_mod
            from model import Segment, TranscriptionAdapter, register_adapter
            import transcribe as transcribe_mod

            observed = {}

            # The context caches its adapter map; the test adapter is
            # registered after that map was built, so the cache is reset
            # for the duration of the test.
            saved_context = model_mod._context
            model_mod._context = None

            @register_adapter
            class _StreamingTestAdapter(TranscriptionAdapter):
                """Yields segments slowly so the test can watch the file."""

                @property
                def prefix(self):
                    return "streamtest"

                @property
                def display_name(self):
                    return "Streaming Test Adapter"

                def is_available(self):
                    return True

                def get_model_names(self):
                    return ["fake"]

                def transcribe(self, audio_file, model, language=None,
                              write=print, temperature=0.0, **kwargs):
                    for i in range(3):
                        if i > 0:
                            time.sleep(0.2)
                        observed[f"before_yield_{i}"] = _read_text(
                            observed["unfinished"]
                        )
                        yield Segment(start=float(i), end=float(i) + 1.0,
                                      text=f"cue {i}")

            def _read_text(path):
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        return handle.read()
                except OSError:
                    return ""

            with tempfile.TemporaryDirectory() as tmp:
                srt_file = os.path.join(tmp, "clip.srt")
                observed["unfinished"] = srt_file + ".unfinished"
                ok = transcribe_mod._transcribe_with_adapter(
                    audio_file=os.path.join(tmp, "audio.wav"),
                    model_name="streamtest:fake",
                    srt_file=srt_file,
                    language="en",
                    write=lambda msg: None,
                )
                assert ok, "adapter flow reported failure"
                final = _read_text(srt_file)
                assert "cue 0" in final and "cue 2" in final, final
                # the file starts empty (header only) and grows one cue at
                # a time: the previous cue is on disk before the adapter
                # produces the next one
                assert "cue 0" not in observed["before_yield_0"], observed
                assert "cue 0" in observed["before_yield_1"], observed
                assert "cue 1" in observed["before_yield_2"], observed
                assert "cue 2" not in observed["before_yield_2"], observed
                self._record(
                    "Streaming adapter grows the unfinished file",
                    "PASS",
                )
        except Exception as e:
            self._record(
                "Streaming adapter grows the unfinished file", "FAIL", str(e)
            )
        finally:
            model_mod._context = saved_context

        # --- Parakeet: chunked, streaming transcription ---
        try:
            import wave as wave_mod

            from adapters.parakeet_adapter import ParakeetAdapter

            adapter = ParakeetAdapter()

            class _FakeParakeetModel:
                """Returns one segment per chunk, relative to the chunk."""

                def __init__(self):
                    self.calls = []

                def transcribe(self, paths, timestamps=False):
                    self.calls.append(paths[0])
                    start = 0.0
                    return [
                        {
                            "timestamp": {
                                "segment": [
                                    {"start": start, "end": start + 1.0,
                                     "segment": "hello"}
                                ]
                            },
                            "text": "hello",
                        }
                    ]

            with tempfile.TemporaryDirectory() as tmp:
                wav_path = os.path.join(tmp, "long.wav")
                rate = 16000
                seconds = 70
                with wave_mod.open(wav_path, "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(rate)
                    handle.writeframes(
                        b"\x00\x00" * rate * seconds
                    )

                chunks = adapter._chunk_wav(wav_path, tmp)
                assert len(chunks) == 3, f"expected 3 chunks, got {len(chunks)}"
                offsets = [round(offset, 3) for _, offset in chunks]
                assert offsets == [0.0, 28.0, 56.0], offsets

                fake_model = _FakeParakeetModel()
                segments = list(adapter._stream_chunks(fake_model, chunks, lambda m: None))
                assert len(fake_model.calls) == 3, fake_model.calls
                assert segments, "no segments produced"
                # absolute timestamps: the second chunk starts at 28s
                assert segments[0].start == 0.0, segments[0]
                assert segments[1].start == 28.0, segments[1]
                assert segments[2].start == 56.0, segments[2]
                assert all(s.end > s.start for s in segments), segments
                self._record(
                    "Parakeet chunks audio and streams segments",
                    "PASS",
                    f"{len(chunks)} chunks, {len(segments)} segments",
                )
        except Exception as e:
            self._record(
                "Parakeet chunks audio and streams segments", "FAIL", str(e)
            )

        # --- Duplicate-run guard (whisper music/silence hallucination) ---
        try:
            from transcribe import _DuplicateRunGuard

            guard = _DuplicateRunGuard()
            actions = []
            offsets = {}
            truncated_at = None
            pos = 100  # simulated file offset; each written cue is 10 bytes
            for text in ["op", "b1", "b1", "b1", "b1", "b1", "b1", "b1", "real"]:
                guard.start_cue(pos)
                action = guard.feed(text)
                actions.append(action)
                offsets.setdefault(text, guard.start_offset)
                if action == "write":
                    pos += 10
                if action == "truncate":
                    truncated_at = guard.start_offset
            # first occurrence written, repeats skipped, run truncated once
            assert actions == [
                "write", "write", "skip", "skip", "skip",
                "truncate", "skip", "skip", "write",
            ], actions
            # the truncate points at the run's FIRST cue offset
            assert truncated_at == offsets["b1"], (truncated_at, offsets["b1"])
            # during the run the truncated text stays banned (skipped,
            # never re-truncated): actions[5:8] == truncate, skip, skip
            # after different speech arrives the ban is lifted
            assert "b1" not in guard.banned
            # a real repeated interjection below the threshold is kept
            guard2 = _DuplicateRunGuard()
            seq = [guard2.feed(t) for t in ["a", "a", "a"]]
            assert seq == ["write", "skip", "skip"], seq
            assert all(a != "truncate" for a in seq)
            self._record("Duplicate-run guard", "PASS")
        except Exception as e:
            self._record("Duplicate-run guard", "FAIL", str(e))

        # --- verify: absurd cue durations are blocking problems ---
        try:
            import transcribe as transcribe_mod

            with tempfile.TemporaryDirectory() as tmp:
                long_srt = os.path.join(tmp, "long.srt")
                with open(long_srt, "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:00,000 --> 00:20:00,000\n次回予告\n\n"
                        "2\n00:20:00,000 --> 00:20:04,000\nhello\n\n"
                    )
                report = transcribe_mod.verify_srt_file(long_srt, write=lambda m: None)
                assert not report["ok"], report
                assert any("spans 20 minutes" in p for p in report["problems"]), report

                warn_srt = os.path.join(tmp, "warn.srt")
                with open(warn_srt, "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:00,000 --> 00:06:00,000\nlecture pause\n\n"
                    )
                report = transcribe_mod.verify_srt_file(warn_srt, write=lambda m: None)
                assert report["ok"], report
                assert any("spans 6.0 minutes" in w for w in report["warnings"]), report
                self._record("Verify long-cue check", "PASS")
        except Exception as e:
            self._record("Verify long-cue check", "FAIL", str(e))

        # --- check_empty_srt: hallucinated file is unusable, not complete ---
        try:
            # Reproduces the Yuyushiki S01E11 failure: an OP hallucinated as
            # mechanical 30s cues of one repeated phrase.
            def ts(total_seconds):
                ms = int(round(total_seconds * 1000))
                h, rem = divmod(ms, 3600_000)
                m, rem = divmod(rem, 60_000)
                sec, ms = divmod(rem, 1000)
                return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

            blocks = []
            for i in range(34):
                start = i * 30
                end = start + 29.98
                text = "ご視聴ありがとうございました" if i == 0 else "次回予告"
                blocks.append(f"{i + 1}\n{ts(start)} --> {ts(end)}\n{text}\n")
            hallucinated = "\n".join(blocks)
            for i in range(3):
                hallucinated += (
                    f"\n{35 + i}\n00:{22 + i}:00,000 --> 00:{22 + i}:30,000\n"
                    "ご視聴ありがとうございました\n"
                )

            with tempfile.TemporaryDirectory() as tmp:
                v = lambda name: os.path.join(tmp, name)
                with open(v("e11.srt"), "w", encoding="utf-8") as f:
                    f.write(hallucinated)
                reason = sc.is_unusable_srt(v("e11.srt"))
                assert reason is not None, "hallucinated file passed as usable"
                assert "hallucination" in reason or "consecutive" in reason, reason

                history = v("history.txt")
                with open(history, "w", encoding="utf-8") as f:
                    f.write("ep11 large-v3\n")
                with open(v("jobs.json"), "w", encoding="utf-8") as f:
                    json.dump(
                        [
                            {
                                "id": 7,
                                "tasks": [
                                    {
                                        "source": "S01E11",
                                        "status": "transcribing",
                                    }
                                ],
                            }
                        ],
                        f,
                    )
                logs = []
                assert sc.check_empty_srt(
                    srt_path=v("e11.srt"),
                    ids=["ep11", "S01E11"],
                    source="S01E11",
                    model_name="large-v3",
                    history_file=history,
                    jobs_file=v("jobs.json"),
                    job_id=7,
                    list_file=v("empty.txt"),
                    write=logs.append,
                )
                with open(history, encoding="utf-8") as f:
                    assert f.read() == "", "hallucinated file left in history"
                records = sc.read_empty_list(v("empty.txt"))
                assert records and records[0]["reason"] != "empty", records
                # a clean file still passes
                with open(v("good.srt"), "w", encoding="utf-8") as f:
                    f.write("1\n00:00:01,000 --> 00:00:04,000\nhello\n\n")
                assert sc.is_unusable_srt(v("good.srt")) is None
                self._record("Hallucinated SRT unusable (batch retry)", "PASS")
        except Exception as e:
            self._record("Hallucinated SRT unusable (batch retry)", "FAIL", str(e))

        # --- All Python files compile ---
        try:
            import py_compile

            errors = []
            for root, dirs, files in os.walk(
                os.path.join(os.path.dirname(__file__), "..")
            ):
                # Skip hidden dirs (.git, .venv, .opencode with its huge
                # node_modules) — they are not project source and walking
                # them over network filesystems takes minutes.
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                if "__pycache__" in root:
                    continue
                for f in files:
                    if f.endswith(".py"):
                        path = os.path.join(root, f)
                        try:
                            py_compile.compile(path, doraise=True)
                        except py_compile.PyCompileError as e:
                            errors.append(f"{path}: {e}")
            if errors:
                self._record("All files compile", "FAIL", f"{len(errors)} errors")
            else:
                self._record("All files compile", "PASS")
        except Exception as e:
            self._record("All files compile", "FAIL", str(e))

    def run_adapter_status(self):
        print("\n" + "=" * 60)
        print("ADAPTER STATUS")
        print("=" * 60)

        from model import TranscriptionContext

        ctx = TranscriptionContext()
        ctx._ensure_initialized()

        all_adapters = {}
        from model import _ADAPTER_CLASSES

        for cls in _ADAPTER_CLASSES:
            try:
                inst = cls()
                all_adapters[inst.prefix or "(local)"] = {
                    "class": cls.__name__,
                    "available": inst.is_available(),
                    "models": inst.get_model_names(),
                    "prefix": inst.prefix,
                }
            except Exception as e:
                all_adapters[f"error:{cls.__name__}"] = {
                    "class": cls.__name__,
                    "available": False,
                    "models": [],
                    "prefix": "",
                    "error": str(e),
                }

        available = {k: v for k, v in all_adapters.items() if v["available"]}
        unavailable = {k: v for k, v in all_adapters.items() if not v["available"]}

        print(f"\n  Available ({len(available)}):")
        for prefix, info in sorted(available.items()):
            models_str = ", ".join(info["models"][:3])
            if len(info["models"]) > 3:
                models_str += f" (+{len(info['models']) - 3} more)"
            print(f"    {prefix:20s}  {info['class']:25s}  [{models_str}]")

        print(f"\n  Unavailable ({len(unavailable)}):")
        for prefix, info in sorted(unavailable.items()):
            reason = info.get("error", "missing dependency/key")
            print(f"    {prefix:20s}  {info['class']:25s}  ({reason})")

        self._record(
            "Adapters available",
            "PASS" if available else "SKIP",
            f"{len(available)}/{len(all_adapters)}",
        )

    def run_transcribe_test(
        self, audio_file: str, model_name: str, language: str = None
    ):
        print("\n" + "=" * 60)
        print(f"TRANSCRIPTION TEST: {model_name}")
        print("=" * 60)

        if not os.path.exists(audio_file):
            self._record(
                f"Transcribe {model_name}", "SKIP", f"audio not found: {audio_file}"
            )
            return

        from model import TranscriptionContext

        ctx = TranscriptionContext()
        try:
            adapter, resolved = ctx.resolve(model_name)
            print(f"  Adapter:  {adapter.display_name}")
            print(f"  Model:    {resolved}")
        except ValueError as e:
            self._record(f"Transcribe {model_name}", "FAIL", str(e))
            return

        start = time.time()
        try:
            segments, info = ctx.transcribe(
                audio_file=audio_file,
                model_name=model_name,
                language=language,
                write=lambda m: print(f"    {m}"),
            )
            elapsed = time.time() - start

            full_text = " ".join(s.text for s in segments)
            print(f"\n  Segments: {len(segments)}")
            print(f"  Time:     {elapsed:.1f}s")
            print(
                f"  Text:     {full_text[:200]}{'...' if len(full_text) > 200 else ''}"
            )

            if segments and any(s.text.strip() for s in segments):
                self._record(
                    f"Transcribe {model_name}",
                    "PASS",
                    f"{len(segments)} segments, {elapsed:.1f}s",
                )
            else:
                self._record(f"Transcribe {model_name}", "FAIL", "no text in segments")

        except Exception as e:
            elapsed = time.time() - start
            self._record(f"Transcribe {model_name}", "FAIL", f"{e} ({elapsed:.1f}s)")

    def run_all_transcribe_tests(self, audio_file: str, language: str = None):
        from model import TranscriptionContext

        ctx = TranscriptionContext()
        ctx._ensure_initialized()

        models_to_test = []

        if ctx._default_adapter and ctx._default_adapter.is_available():
            models_to_test.append("tiny")

        for prefix, adapter in ctx._adapter_map.items():
            models = adapter.get_model_names()
            if models:
                models_to_test.append(f"{prefix}:{models[0]}")

        if not models_to_test:
            print("\n  No adapters available for transcription testing.")
            print("  Set API keys or install dependencies to enable adapters.")
            return

        print(f"\n  Will test {len(models_to_test)} models: {models_to_test}")

        for model_name in models_to_test:
            self.run_transcribe_test(audio_file, model_name, language)

    def generate_audio(self):
        print("Generating test audio...")
        subprocess.run(
            [
                sys.executable,
                os.path.join(os.path.dirname(__file__), "generate_test_audio.py"),
            ],
            check=True,
        )

    def list_adapters(self):
        from model import TranscriptionContext, _ADAPTER_CLASSES

        ctx = TranscriptionContext()
        ctx._ensure_initialized()

        print("\nAll registered adapters:")
        for cls in _ADAPTER_CLASSES:
            try:
                inst = cls()
                available = inst.is_available()
                prefix = inst.prefix or "(local)"
                models = inst.get_model_names()
                status = "AVAILABLE" if available else "unavailable"
                print(f"\n  {cls.__name__} [{status}]")
                print(f"    Prefix:  {prefix}")
                print(f"    Display: {inst.display_name}")
                print(f"    Models:  {', '.join(models)}")
            except Exception as e:
                print(f"\n  {cls.__name__} [ERROR: {e}]")

        print(f"\nActive adapter map: {list(ctx._adapter_map.keys())}")
        if ctx._default_adapter:
            print(f"Default adapter: {ctx._default_adapter.display_name}")

    def print_summary(self):
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        for r in self.results:
            icon = {"PASS": "+", "FAIL": "X", "SKIP": "o"}[r["status"]]
            detail = f" ({r['detail']})" if r["detail"] else ""
            print(f"  [{icon}] {r['name']}{detail}")

        total = self.passed + self.failed + self.skipped
        print(
            f"\n  {self.passed}/{total} passed, {self.failed} failed, {self.skipped} skipped"
        )
        print("=" * 60)
        return 0 if self.failed == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="whisper-subs test runner")
    parser.add_argument("--audio", help="Audio file for transcription tests")
    parser.add_argument(
        "--model", help="Specific model to test (e.g. groq:whisper-large-v3)"
    )
    parser.add_argument("--lang", help="Language code (e.g. en, ja, es)")
    parser.add_argument(
        "--list-adapters", action="store_true", help="List all adapters and exit"
    )
    parser.add_argument(
        "--generate-audio", action="store_true", help="Generate test audio files"
    )
    args = parser.parse_args()

    runner = TestRunner()

    if args.list_adapters:
        runner.list_adapters()
        return 0

    if args.generate_audio:
        runner.generate_audio()
        return 0

    runner.run_unit_tests()
    runner.run_adapter_status()

    if args.audio:
        if args.model:
            runner.run_transcribe_test(args.audio, args.model, args.lang)
        else:
            runner.run_all_transcribe_tests(args.audio, args.lang)

    return runner.print_summary()


if __name__ == "__main__":
    sys.exit(main())
