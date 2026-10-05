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
                assert "1\n00:01:00,000 --> 00:01:04,000\nfirst part" in content, content
                # pass-1 block keeps its absolute timestamp (no double offset)
                assert "2\n00:10:00,000 --> 00:10:05,000\nsecond half" in content, content
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
                assert not tr.verify_srt_file(v("empty.srt"), write=lambda m: None)["ok"]
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
                assert not r["ok"] and any("corrupt tail" in p for p in r["problems"]), r

                # hallucination: phrase repeated 8x inside one segment
                with open(v("rep.srt"), "w", encoding="utf-8") as f:
                    f.write("1\n00:00:01,000 --> 00:00:04,000\n"
                            + "de luta de luta " * 10 + "\n\n")
                r = tr.verify_srt_file(v("rep.srt"), write=lambda m: None)
                assert not r["ok"] and any("hallucination" in p for p in r["problems"]), r

                # hallucination: 5 consecutive identical segments
                with open(v("run.srt"), "w", encoding="utf-8") as f:
                    f.write("".join(
                        f"{i}\n00:00:0{i},000 --> 00:00:0{i+1},000\nsame text\n\n"
                        for i in range(1, 6)
                    ))
                r = tr.verify_srt_file(v("run.srt"), write=lambda m: None)
                assert not r["ok"] and any("consecutive" in p for p in r["problems"]), r

                # hallucination: over half duplicates (>=10 segments)
                with open(v("dup.srt"), "w", encoding="utf-8") as f:
                    f.write("".join(
                        f"{i}\n00:{i:02d}:00,000 --> 00:{i:02d}:05,000\n"
                        + ("same text" if i % 3 else f"unique line {i}") + "\n\n"
                        for i in range(1, 13)
                    ))
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
                assert r["warnings"] and r["coverage"] is not None and r["coverage"] < 0.01, r

                # non-sequential numbering: warning only
                with open(v("num.srt"), "w", encoding="utf-8") as f:
                    f.write(
                        "1\n00:00:01,000 --> 00:00:04,000\na\n\n"
                        "3\n00:00:05,000 --> 00:00:08,000\nb\n\n"
                    )
                r = tr.verify_srt_file(v("num.srt"), write=lambda m: None)
                assert r["ok"] and any("numbering" in w for w in r["warnings"]), r

            self._record(
                "Verification gate", "PASS", "contents/size/corrupt/hallucination/duration"
            )
        except Exception as e:
            self._record("Verification gate", "FAIL", str(e))

        # --- Within-segment phrase repeat counter ---
        try:
            import transcribe as tr

            c = tr.count_phrase_repeats
            assert c("sim, sim, sim, sim") == 4
            assert c("a tua sociedade quer saber, a tua sociedade quer saber, "
                     "a tua sociedade quer saber") == 3
            assert c("é um jogo de luta de luta de luta de luta de luta "
                     "de luta de luta de luta de luta de luta") == 10
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
                ("a tua sociedade quer saber a tua história do toffle é verdadeira", 44 * 60 + 21),
                ("a sociedade quer saber a tua história do caso não é verdadeira", 44 * 60 + 24),
                ("todo mundo quer saber a tua história da urgia é tão verdadeira", 44 * 60 + 27),
                ("todo mundo quer saber", 44 * 60 + 31),
                ("a tua sociedade quer saber a história é verdadeira sim", 44 * 60 + 34),
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
            burst = [("a tua sociedade quer saber variação", float(i)) for i in range(10)]
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
                "Live incremental + finalize", "PASS", "keep_unfinished + real file move"
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
                    f.write("7\n00:10:00,000 --> 00:10:05,000\r\nline one\r\nline two\r\n\r\n")
                ok = tr._merge_srt_files(
                    second_pass_srt=second,
                    first_pass_srt=final,
                    final_srt=final,
                    write=lambda m: None,
                )
                assert ok
                with open(final, encoding="utf-8") as f:
                    content = f.read()
                assert "1\n00:10:00,000 --> 00:10:05,000\nline one\nline two" in content, content

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
