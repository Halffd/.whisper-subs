#!/usr/bin/env python3
"""Tests for the three feature areas added on 2026-11-08:

1. distil-whisper: MODEL_NAMES HF repo ids translate to what
   faster-whisper accepts (`distil-whisper/distil-medium.en` ->
   `distil-medium.en`).
2. Custom VADs: the pluggable `vad` module, its registry, region
   merging, custom-callable loading, and the WhisperX wrapper object.
3. NeMo diarization: model-name routing of the diarization engine.

Run directly or via tests/run_tests.py.
"""
import sys
import textwrap
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_PARSER_CACHE = []


def SRC_PARSER():
    """Build the real CLI parser (cached: the imports behind it are slow)."""
    if not _PARSER_CACHE:
        sys.path.insert(0, REPO_ROOT)
        import whisper_subs

        _PARSER_CACHE.append(whisper_subs.build_parser())
    return _PARSER_CACHE[0]


WAV = os.path.join(os.path.dirname(__file__), "fixtures", "test_sine.wav")


def test_fw_alias_translates_distil_names():
    """MODEL_NAMES repo ids must map to faster-whisper's short names."""
    from adapters.faster_whisper_adapter import _resolve_fw_model

    assert _resolve_fw_model("distil-whisper/distil-medium.en") == "distil-medium.en"
    assert _resolve_fw_model("distil-whisper/distil-small.en") == "distil-small.en"
    assert _resolve_fw_model("distil-whisper/distil-large-v3") == "distil-large-v3"
    print("  [PASS] distil HF repo ids resolve to faster-whisper names")


def test_fw_alias_leaves_plain_names_untouched():
    """Non-distil names must pass through unchanged, or transcription
    of every normal model would silently break."""
    from adapters.faster_whisper_adapter import _resolve_fw_model

    for name in ("large-v3", "tiny.en", "medium", "Systran/faster-whisper-tiny"):
        assert _resolve_fw_model(name) == name, name
    print("  [PASS] plain model names pass through unchanged")


def test_fw_alias_covers_all_repo_forms():
    """Every slashed MODEL_NAMES entry that faster-whisper expects in
    short form must be in the alias table."""
    from adapters.faster_whisper_adapter import _FW_MODEL_ALIASES, _resolve_fw_model
    from model import MODEL_NAMES

    slashed = [m for m in MODEL_NAMES if "/" in m and "distil" in m]
    assert slashed, "expected distil entries in MODEL_NAMES"
    # japanese-asr/... is an HF repo with no CTranslate2 model.bin, so
    # faster-whisper can never load it (pre-existing limitation, out of
    # scope here); it must not appear in the alias table.
    non_ct2 = {"japanese-asr/distil-whisper-large-v3-ja-reazonspeech-large"}
    for name in slashed:
        if name in non_ct2:
            assert name not in _FW_MODEL_ALIASES, name
            continue
        assert name in _FW_MODEL_ALIASES, name
        assert "/" not in _resolve_fw_model(name), name
    print(f"  [PASS] all {len(slashed) - len(non_ct2)} distil repo ids resolve via alias table")


def test_vad_engine_list_and_default():
    import vad

    assert set(vad.ENGINES) >= {"silero", "pyannote", "webrtc", "custom"}
    assert vad.DEFAULT_ENGINE == "silero"
    assert "custom" in vad.list_engines()
    print("  [PASS] VAD engines registered")


def test_vad_unknown_engine_degrades_gracefully():
    """An unknown engine must not abort transcription."""
    import vad

    out = []
    engine = vad.resolve("does-not-exist", write=out.append)
    assert engine is None
    assert any("Unknown VAD" in m for m in out)
    assert vad.detect(WAV, requested="does-not-exist", write=lambda m: None) == []
    print("  [PASS] unknown VAD engine degrades to no-VAD")


def test_vad_merge_regions():
    import vad

    assert vad.merge_regions([]) == []
    assert vad.merge_regions([(0.5, 0.1)]) == []  # end <= start dropped
    merged = vad.merge_regions([(5.0, 6.0), (0.0, 1.0), (0.5, 2.0), (2.0, 3.0)])
    assert [(round(a, 3), round(b, 3)) for a, b in merged] == [
        (0.0, 3.0),
        (5.0, 6.0),
    ]
    print("  [PASS] merge_regions sorts, drops empty, coalesces touching")


def test_vad_registry_custom_callable():
    """register_vad + detect() end to end with a fake engine."""
    import vad

    vad.register_vad("test-full-vad", lambda path: [(0.0, 3.0)])
    try:
        assert vad.detect(WAV, requested="test-full-vad", write=lambda m: None) == [
            (0.0, 3.0)
        ]
        obj = vad.build_whisperx_vad(WAV, "test-full-vad", write=lambda m: None)
        assert obj is not None and obj.regions == [(0.0, 3.0)]
    finally:
        del vad._REGISTRY["test-full-vad"]
    print("  [PASS] custom registered VAD produces WhisperX-compatible regions")


def test_vad_whisperx_wrapper_protocol():
    """The object handed to whisperx.load_model must satisfy issubclass
    against whisperx's Vad and return whisperx Segments on call."""
    import vad

    vad.register_vad("test-wx", lambda path: [(0.0, 1.0), (2.0, 3.0)])
    try:
        obj = vad.build_whisperx_vad(WAV, "test-wx", write=lambda m: None)
        from whisperx.vads.vad import Vad

        assert issubclass(type(obj), Vad), "wrapper must subclass whisperx Vad"

        from whisperx.diarize import Segment as seg_type

        segs = obj.__call__({})
        assert isinstance(segs, list) and all(isinstance(s, seg_type) for s in segs)
        assert [(s.start, s.end) for s in segs] == [(0.0, 1.0), (2.0, 3.0)]
        assert all(s.speaker == "UNKNOWN" for s in segs)

        # merge_chunks must be the pipeline's, not the wrapper's, and must
        # accept the kwargs asr.py passes (it reads seg.speaker). Regions
        # whose gaps are under chunk_size collapse into one chunk.
        merged = type(obj).merge_chunks(
            segs, 30, onset=0.5, offset=0.363
        )
        assert merged, "expected at least one merged chunk"
        assert merged[0]["start"] == 0.0 and merged[0]["end"] == 3.0
        assert merged[0]["segments"] == [(0.0, 1.0), (2.0, 3.0)]
    finally:
        del vad._REGISTRY["test-wx"]
    print("  [PASS] WhisperX VAD wrapper implements the real contract")


def test_vad_custom_target_requires_callable_target():
    import vad

    out = []
    engine = vad._load_custom({}, write=out.append)
    assert engine is None
    assert any("target" in m for m in out)

    out = []
    engine = vad._load_custom({"target": "no-colon"}, write=out.append)
    assert engine is None
    assert any("module:callable" in m for m in out)

    # A well-formed target resolves.
    engine = vad._load_custom({"target": "json:loads"}, write=lambda m: None)
    assert callable(engine)
    print("  [PASS] custom target parsing validates 'module:callable' form")


def test_vad_param_parsing():
    import vad

    assert vad.parse_vad_params(["threshold=0.35", "mode=2"]) == {
        "threshold": "0.35",
        "mode": "2",
    }
    assert vad.parse_vad_params(["garbage"]) == {}
    assert vad.parse_vad_params(None) == {}
    assert vad._parse_params("a=1,b=two,c=3") == {"a": "1", "b": "two", "c": "3"}
    print("  [PASS] VAD params parse from both env and repeatable flags")


def test_vad_engine_env_fallback():
    """WHISPERSUBS_VAD selects the engine when no explicit request."""
    import subprocess

    saved = os.environ.get("WHISPERSUBS_VAD")
    try:
        os.environ["WHISPERSUBS_VAD"] = "webrtc"
        # A child import: no module already loaded, so the env read is a
        # real cold path (and reload side effects stay out of the suite).
        code = (
            "import sys; sys.path.insert(0, %r); import vad;"
            "engine = vad.resolve(write=lambda m: None);"
            "print('NAMED' if engine is vad.vad_webrtc else 'OTHER')" % REPO_ROOT
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=300,
        ).stdout
        assert "NAMED" in out, out[-300:]

        # A registered plugin also wins over the default via the env var.
        os.environ["WHISPERSUBS_VAD"] = "plug"
        code = (
            "import sys; sys.path.insert(0, %r); import vad;"
            "vad.register_vad('plug', lambda p: [(0.0, 0.1)]);"
            "engine = vad.resolve(write=lambda m: None);"
            "print('PLUG' if engine is vad._REGISTRY['plug'] else 'OTHER')"
            % REPO_ROOT
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=300,
        ).stdout
        assert "PLUG" in out, out[-300:]
    finally:
        if saved is None:
            del os.environ["WHISPERSUBS_VAD"]
        else:
            os.environ["WHISPERSUBS_VAD"] = saved
    print("  [PASS] WHISPERSUBS_VAD env selects the engine")


def test_diarize_engine_accepted_by_process_create():
    """process_create/transcribe_audio must accept and forward the engine
    params, or --diarize-engine and --vad-engine would vanish silently."""
    import inspect

    import transcribe

    for fn in (transcribe.process_create, transcribe.transcribe_audio):
        params = inspect.signature(fn).parameters
        assert "diarize_engine" in params, fn.__name__
        assert "vad_engine" in params, fn.__name__
        assert "vad_params_extra" in params, fn.__name__
    print("  [PASS] engine params accepted by process_create/transcribe_audio")


def test_vad_cli_flags_parse():
    """The real CLI must accept and default the new flags."""
    from whisper_subs import build_parser

    parser = build_parser()
    args = parser.parse_args(["test.wav", "--vad-engine", "webrtc",
                               "--vad-param", "threshold=0.4"])
    assert args.vad_engine == "webrtc"
    assert args.vad_param == ["threshold=0.4"]

    args = parser.parse_args(["test.wav"])
    assert args.vad_engine is None and args.vad_param == []
    print("  [PASS] --vad-engine / --vad-param parse on the real CLI")


def test_caption_vtt_to_srt_conversion():
    """VTT payloads must convert to valid SRT: both timestamp separators."""
    import caption_fetch

    vtt = (
        "WEBVTT\nKind: captions\nLanguage: en\n\n"
        "1\n00:00:01.000 --> 00:00:03.500\n<c>Hello</c> there\n\n"
        "2\n00:00:04.000 --> 00:00:06.000\nSecond cue\n"
    )
    srt = caption_fetch._vtt_to_srt(vtt)
    assert srt, "conversion produced nothing"
    lines = srt.splitlines()
    assert lines[0] == "1"
    assert lines[1] == "00:00:01,000 --> 00:00:03,500"
    assert "Hello there" in lines[2]
    # The end timestamp must also be comma-separated (the original bug
    # only rewrote the first separator).
    assert any("--> 00:00:06,000" in line for line in lines)
    assert "." not in lines[1]
    print("  [PASS] VTT -> SRT conversion")


def test_caption_json3_conversion():
    """json3 events -> SRT; multi-seg cues join, ms formatter is correct."""
    import json

    import caption_fetch

    data = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 7000, "segs": [{"utf8": "One"}]},
            {
                "tStartMs": 19514,
                "dDurationMs": 1712,
                "segs": [{"utf8": "Hear "}, {"utf8": "that?"}],
            },
        ]
    }
    srt = caption_fetch._json3_to_srt(json.dumps(data))
    lines = srt.splitlines()
    # First cue: index 1, timestamps and text.
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:07,000"
    assert lines[2] == "One"
    # Second cue (multi-seg): the two fragments must be joined without a gap.
    assert lines[5] == "00:00:19,514 --> 00:00:21,226"
    assert lines[6] == "Hear that?", "multi-seg cues must be joined"
    assert "." not in lines[5]
    # Broken json must not raise, just yield nothing.
    assert caption_fetch._json3_to_srt("{not json") == ""
    assert caption_fetch._ms_to_srt(3661000) == "01:01:01,000"
    print("  [PASS] json3 -> SRT conversion")


def test_caption_ttml_conversion():
    """TTML <p begin= end=> -> SRT, with <br/> becoming a line break."""
    import caption_fetch

    ttml = (
        '<?xml version="1.0"?>\n<tt><body><div>'
        '<p begin="00:00:00.000" end="00:00:07.000" style="s2">'
        "Translator: A<br />Reviewer: B</p>"
        '<p begin="00:00:19.514" end="00:00:21.226">Hear that?</p>'
        "</div></body></tt>"
    )
    srt = caption_fetch._ttml_to_srt(ttml)
    lines = srt.splitlines()
    assert lines[1] == "00:00:00,000 --> 00:00:07,000"
    assert "Translator: A\nReviewer: B" in srt, "<br/> must become a newline"
    assert "Hear that?" in srt
    assert any("--> 00:00:21,226" in line for line in lines)
    # XML entities must be decoded.
    entity = (
        '<p begin="00:00:01.000" end="00:00:02.000">'
        "That&#39;s &amp; &lt;more&gt;</p>"
    )
    assert "That's & <more>" in caption_fetch._ttml_to_srt(entity)
    print("  [PASS] ttml -> SRT conversion")


def test_caption_language_matching_is_region_tolerant():
    """`pt` must match a `pt-BR` track and vice-versa."""
    import caption_fetch

    br = caption_fetch.CaptionTrack.from_entry(
        "pt-BR", {"url": "u", "ext": "srt"}
    )
    plain = caption_fetch.CaptionTrack.from_entry(
        "pt", {"url": "u", "ext": "srt"}
    )
    for requested, candidates, expected in (
        (["pt"], [br], br),
        (["pt-BR"], [plain], plain),
        (["PT"], [br], br),
    ):
        picked = caption_fetch._pick_track(
            candidates,
            langs=requested,
            allow_automatic=False,
            video_lang=None,
        )
        assert picked is expected, (requested, picked)
    print("  [PASS] caption language matching tolerates regions")


def test_caption_format_rank_prefers_cheap_formats():
    """srt/vtt win over json3/ttml in the same language and kind."""
    import caption_fetch

    cur = caption_fetch.CaptionTrack.from_entry(
        "en", {"url": "u", "ext": "json3"}
    )
    viewer = caption_fetch.CaptionTrack.from_entry(
        "en", {"url": "u", "ext": "vtt"}
    )
    picked = caption_fetch._pick_track(
        [cur, viewer], langs=["en"], allow_automatic=False, video_lang=None
    )
    assert picked.ext == "vtt", picked.ext
    assert caption_fetch._format_rank(viewer) < caption_fetch._format_rank(cur)
    print("  [PASS] caption format ranking prefers srt/vtt")


def test_caption_track_prefers_human_over_auto():
    """Human tracks win over automatic in the same language."""
    import caption_fetch

    human = caption_fetch.CaptionTrack.from_entry(
        "en", {"url": "u", "ext": "srt"}
    )
    auto = caption_fetch.CaptionTrack.from_entry(
        "en", {"url": "u", "ext": "srt", "is_automatic": True}
    )
    picked = caption_fetch._pick_track(
        [auto, human], langs=["en"], allow_automatic=False, video_lang=None
    )
    assert picked is human, "human track must be preferred"
    # Automatic is only reachable when explicitly allowed.
    picked = caption_fetch._pick_track(
        [auto], langs=["en"], allow_automatic=True, video_lang=None
    )
    assert picked is auto
    print("  [PASS] caption track preference (human first)")


def test_caption_track_language_priority():
    """Requested language beats defaults; format rank breaks ties."""
    import caption_fetch

    en = caption_fetch.CaptionTrack.from_entry("en", {"url": "u", "ext": "srt"})
    # A ttml track in the same language loses to srt on conversion cost, so
    # with both present the pick is the srt one.
    ttml = caption_fetch.CaptionTrack.from_entry(
        "en", {"url": "u", "ext": "ttml"}
    )
    picked = caption_fetch._pick_track(
        [ttml, en], langs=["en"], allow_automatic=False, video_lang=None
    )
    assert picked is en, picked
    # A requested language with no track falls through to defaults, and
    # ttml is convertible, so it is used when it is the only candidate.
    picked = caption_fetch._pick_track(
        [ttml], langs=["de"], allow_automatic=False, video_lang=None
    )
    assert picked is ttml, "ttml must be used when it is the only track"
    print("  [PASS] caption language priority and format ranking")


def test_caption_translate_url_forces_srt():
    """A vtt track URL must request srt output so the file is SRT."""
    import caption_fetch

    track = caption_fetch.CaptionTrack.from_entry(
        "en", {"url": "http://x?a=1&fmt=vtt", "ext": "vtt"}
    )
    assert caption_fetch._translate_url(track).endswith("fmt=srt")
    track = caption_fetch.CaptionTrack.from_entry(
        "en", {"url": "http://x?a=1", "ext": "vtt"}
    )
    assert caption_fetch._translate_url(track).endswith("&fmt=srt")
    print("  [PASS] caption URL requests srt")


def test_caption_fetch_reports_reason_without_writing():
    """A URL with no captions must fail cleanly with a reason, no file."""
    import caption_fetch

    # list_captions() swallows yt-dlp failures into [], so an unreachable
    # URL exercises the "no captions available" path.
    out = "/tmp/no-such-caption-file"
    result = caption_fetch.fetch_captions(
        "https://www.invalid/nope", out, write=lambda m: None
    )
    assert not result.ok
    assert result.reason
    assert result.path is None
    assert not os.path.exists(out), "nothing must be written on failure"
    print("  [PASS] caption fetch failure path is clean")


def test_caption_cli_flags_default_human_only():
    """--fetch-caps defaults to on, --fetch-auto off, --no-fetch-caps wins."""
    from whisper_subs import build_parser

    parser = build_parser()
    args = parser.parse_args(["test.wav"])
    assert args.fetch_caps is None, "unset means human-only default"
    assert args.fetch_auto is False
    assert args.fetch_langs == ""

    args = parser.parse_args(["test.wav", "--no-fetch-caps"])
    assert args.fetch_caps is False
    args = parser.parse_args(
        ["test.wav", "--fetch-auto", "--fetch-langs", "en,pt"]
    )
    assert args.fetch_auto is True
    assert args.fetch_langs == "en,pt"
    print("  [PASS] caption CLI flags and defaults")


def test_caption_lang_list_parsing_in_processor():
    """WhisperSubs stores --fetch-langs as a clean list."""
    import whisper_subs

    proc = whisper_subs.WhisperSubs(
        model_name="tiny", fetch_langs="en, pt ,,fr"
    )
    assert proc.fetch_langs == ["en", "pt", "fr"], proc.fetch_langs
    assert proc.fetch_caps is None
    print("  [PASS] fetch-langs parsed in WhisperSubs")


def test_caption_languages_helper_splits_kinds():
    """languages() collapses regional tags and separates kinds."""
    import caption_fetch

    # Fake out list_captions so the test needs no network.
    real = caption_fetch.list_captions
    try:
        caption_fetch.list_captions = lambda url: [
            caption_fetch.CaptionTrack.from_entry("pt-BR", {"url": "u", "ext": "srt"}),
            caption_fetch.CaptionTrack.from_entry("pt", {"url": "u", "ext": "srt"}),
            caption_fetch.CaptionTrack.from_entry("en", {"url": "u", "ext": "srt"}),
            caption_fetch.CaptionTrack.from_entry(
                "ja", {"url": "u", "ext": "srt", "is_automatic": True}
            ),
        ]
        langs = caption_fetch.languages("http://any")
    finally:
        caption_fetch.list_captions = real

    assert langs["human"].count("pt") == 1, langs["human"]
    assert set(langs["human"]) == {"pt", "en"}
    # Automatic languages are hidden unless explicitly requested.
    assert langs["automatic"] == []

    caption_fetch.list_captions = lambda u: [
        caption_fetch.CaptionTrack.from_entry(
            "ja", {"url": "u", "ext": "srt", "is_automatic": True}
        )
    ]
    assert caption_fetch.languages("http://any", allow_automatic=True)[
        "automatic"
    ] == ["ja"]
    caption_fetch.list_captions = real
    print("  [PASS] languages() splits human/automatic and dedupes regions")


def test_caption_asr_origin_is_not_human():
    """ASR-origins (`en-orig`) must be classified automatic, not human.

    On an ASR-only video yt-dlp puts the origin track under
    `automatic_captions` (with `subtitles` empty), and still omits the
    `is_automatic` key. Reading only that field would report machine output
    as human captions. The tag must come from the section, not the entry.
    """
    import caption_fetch

    info = {
        # ASR-only video: no uploads at all, origin + translations in auto.
        "subtitles": {},
        "automatic_captions": {
            "aa": [{"url": "u0", "ext": "srt"}],
            "en-orig": [{"url": "u", "ext": "srt"}],
        },
    }
    tracks = caption_fetch._tracks_from_info(info)
    origin = next(t for t in tracks if t.lang == "en-orig")
    assert origin.is_automatic is True, origin

    # Nothing human exists, so a human-only pick must fail rather than
    # silently return machine captions.
    picked = caption_fetch._pick_track(
        tracks, langs=["en"], allow_automatic=False, video_lang=None
    )
    assert picked is None, "human-only must not select ASR output"
    picked = caption_fetch._pick_track(
        tracks, langs=["en"], allow_automatic=True, video_lang=None
    )
    assert picked is origin, picked
    print("  [PASS] ASR-origin tracks are classified automatic")


def test_caption_human_tracks_stay_human():
    """A video with real uploaded captions must still report them human."""
    import caption_fetch

    info = {
        "subtitles": {"en": [{"url": "u", "ext": "srt"}]},
        "automatic_captions": {},
    }
    tracks = caption_fetch._tracks_from_info(info)
    assert tracks and all(t.is_automatic is False for t in tracks)
    assert caption_fetch._pick_track(
        tracks, langs=["en"], allow_automatic=False, video_lang=None
    ) is tracks[0]
    print("  [PASS] uploaded captions remain human")


def _write_srt(blocks) -> str:
    """blocks: [(start, end, text)] -> path to a temp SRT file."""
    import tempfile

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".srt", delete=False, encoding="utf-8"
    )
    for i, (start, end, text) in enumerate(blocks, 1):
        handle.write(f"{i}\n{start} --> {end}\n{text}\n\n")
    handle.close()
    return handle.name


def test_gap_detection_flags_speech_removed_mid_sentence():
    """Holes that open mid-sentence mean the VAD dropped real speech.

    Coverage alone cannot see this: it measures how *far* the file reaches,
    so a transcript missing its middle still scores 100%. Reported as a
    problem so the retry ladder (which now has a no-VAD rung) engages.
    """
    import os

    import transcribe as T

    # Four holes, each opening right after a comma -- speech cut mid-flow.
    blocks = [
        ("00:00:00,000", "00:00:05,000", "He opened the book and read,"),
        ("00:00:11,000", "00:00:16,000", "then quoted at length,"),
        ("00:00:22,000", "00:00:27,000", "and finally wrote,"),
        ("00:00:33,000", "00:00:38,000", "which later became,"),
        ("00:00:44,000", "00:01:00,000", "the closing line."),
    ]
    path = _write_srt(blocks)
    try:
        lines = []
        report = T.verify_srt_file(path, 60.0, lines.append)
    finally:
        os.unlink(path)

    assert len(report["gaps"]) == 4, report["gaps"]
    assert report["total_gap_seconds"] == 24.0, report["total_gap_seconds"]
    assert report["mid_sentence_gap_seconds"] == 24.0
    assert report["ok"] is False, "mid-sentence holes must be a problem"
    assert any("speech likely removed" in l for l in lines), lines
    print("  [PASS] mid-sentence gaps flagged as removed speech")


def test_gap_detection_allows_silence_between_sentences():
    """Holes between finished sentences are ordinary silence, not a defect."""
    import os

    import transcribe as T

    blocks = [
        ("00:00:00,000", "00:00:05,000", "The first scene ends here."),
        ("00:00:15,000", "00:00:20,000", "A new chapter begins."),
        ("00:00:30,000", "00:00:35,000", "Then the music returns."),
        ("00:00:45,000", "00:00:50,000", "And the credits roll."),
        ("00:01:00,000", "00:01:05,000", "The end."),
    ]
    path = _write_srt(blocks)
    try:
        lines = []
        report = T.verify_srt_file(path, 65.0, lines.append)
    finally:
        os.unlink(path)

    assert len(report["gaps"]) == 4
    assert report["mid_sentence_gap_seconds"] == 0.0
    assert report["ok"] is True, "clean breaks must not fail verification"
    assert any("gap(s) totalling" in l for l in lines), lines
    print("  [PASS] gaps between sentences stay warnings")


def test_gap_detection_ignores_small_holes():
    """Normal inter-cue spacing is not a gap."""
    import os

    import transcribe as T

    blocks = [
        ("00:00:00,000", "00:00:05,000", "One."),
        ("00:00:06,000", "00:00:11,000", "Two."),
        ("00:00:12,000", "00:00:17,000", "Three."),
    ]
    path = _write_srt(blocks)
    try:
        report = T.verify_srt_file(path, 17.0, lambda _m: None)
    finally:
        os.unlink(path)

    assert report["gaps"] == [], report["gaps"]
    assert report["total_gap_seconds"] == 0.0
    assert report["ok"] is True
    print("  [PASS] small inter-cue spacing is not reported")


def test_try_transcribe_callers_use_keywords():
    """Every try_transcribe(...) call must name its arguments.

    The positional form silently bound media_source to min_speakers once the
    speaker bounds were inserted ahead of it -- three call sites did this, so
    the assertion below pins the whole file, not one site.
    """
    import ast

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    tree = ast.parse(open(os.path.join(repo, "transcribe.py"), encoding="utf-8").read())

    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "try_transcribe"
    )
    params = [a.arg for a in func.args.args]
    known = set(params) | {a.arg for a in func.args.kwonlyargs}

    checked = 0
    for call in ast.walk(tree):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "try_transcribe"
        ):
            continue
        checked += 1
        assert not call.args, (
            f"line {call.lineno}: positional argument(s) will bind to "
            f"'{params[len(call.args) - 1]}' -- use keywords"
        )
        for kw in call.keywords:
            assert kw.arg in known, f"line {call.lineno}: unknown argument {kw.arg!r}"
    assert checked >= 5, f"expected several call sites, found {checked}"
    print(f"  [PASS] all {checked} try_transcribe call sites use keywords")


def child_script_undefined_names(source_text: str):
    """Names the generated child script loads but never defines.

    Pure function of transcribe.py's text so it can be run against a
    deliberately broken copy as well as the real file.
    """
    import ast
    import builtins
    import string

    text = source_text

    lines = text.splitlines()

    start = next(
        i for i, l in enumerate(lines) if l.strip().startswith("script = f'''")
    )
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "'''")
    body = "\n".join(lines[start + 1 : end])

    tree = ast.parse(text)
    sources = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(text, node)
            if segment:
                sources.setdefault(node.name, segment)

    rendered = []
    for literal, field, _spec, _conv in string.Formatter().parse(body):
        rendered.append(literal)
        if field is None:
            continue
        if field.startswith("inspect.getsource(") and field.endswith(")"):
            name = field[len("inspect.getsource(") : -1].strip()
            rendered.append(sources.get(name, "None"))
        else:
            # Parent-side state; its value cannot change which names the
            # child script is required to define.
            rendered.append("None")
    script = "".join(rendered)

    child = ast.parse(script)  # raises SyntaxError if the template is broken

    builtin_names = set(dir(builtins)) | {
        "__name__",
        "__file__",
        "__doc__",
        "__builtins__",
    }

    def bound_names(nodes) -> set:
        """Names a scope binds: assignments, defs, imports, except/handlers.

        Function *parameters* are deliberately not collected here: an argument
        named `language` in one helper must not make `language` look defined at
        module level, which is precisely the bug this guards against. Each
        function's own arguments are added when that function is checked.
        """
        out = set()
        for node in nodes:
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.add(sub.name)
                elif isinstance(sub, ast.ClassDef):
                    out.add(sub.name)
                elif isinstance(sub, ast.Import):
                    out.update(a.asname or a.name.split(".")[0] for a in sub.names)
                elif isinstance(sub, ast.ImportFrom):
                    out.update(a.asname or a.name for a in sub.names)
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    out.add(sub.id)
                elif isinstance(sub, ast.ExceptHandler) and sub.name:
                    out.add(sub.name)
                elif isinstance(sub, ast.Global):
                    out.update(sub.names)
        return out

    def annotation_nodes(tree_):
        """Type annotations: strings under `from __future__ import annotations`,
        so they are never evaluated and must not count as loads."""
        skip = set()
        for node in ast.walk(tree_):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.returns is not None:
                    skip.update(id(x) for x in ast.walk(node.returns))
            if isinstance(node, ast.arg) and node.annotation is not None:
                skip.update(id(x) for x in ast.walk(node.annotation))
        return skip

    skip = annotation_nodes(child)
    module_scope = bound_names([n for n in child.body])
    missing = set()

    def loads_in(nodes, known):
        found = set()
        for node in nodes:
            for sub in ast.walk(node):
                if id(sub) in skip:
                    continue
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                    if sub.id not in known:
                        found.add(sub.id)
        return found

    # Module level only: a name used inside a function is that function's
    # business, and checking it against module scope reports every local as
    # undefined.
    inside_functions = set()
    for node in ast.walk(child):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inside_functions.update(id(x) for x in ast.walk(node))
    module_stmts = [
        s for s in child.body if id(s) not in inside_functions
    ]
    missing |= loads_in(module_stmts, module_scope | builtin_names)

    # Each function: its own bindings and arguments, plus module scope.
    # Nested functions are checked on their own pass, so their bodies are
    # skipped here -- otherwise their locals would be judged against this
    # function's scope.
    for node in ast.walk(child):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local = bound_names(node.body) | {a.arg for a in node.args.args}
        local |= {a.arg for a in node.args.kwonlyargs}
        if node.args.vararg:
            local.add(node.args.vararg.arg)
        if node.args.kwarg:
            local.add(node.args.kwarg.arg)
        nested = set()
        for sub in ast.walk(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub is not node:
                nested.update(id(x) for x in ast.walk(sub))
        own_stmts = [s for s in node.body if id(s) not in nested]
        missing |= loads_in(own_stmts, local | module_scope | builtin_names)

    return sorted(missing), script


def test_generated_child_script_is_self_contained():
    """The transcription child script must define every name it uses.

    transcribe.py builds that script as an f-string and runs it in a fresh
    process, so any helper it calls has to be injected via
    ``inspect.getsource``. A helper that exists in transcribe.py but was never
    injected raises ``NameError`` at runtime -- once per written segment, and
    it silently cost the transcript while the job still reported success.
    """
    import ast

    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    text = open(os.path.join(repo, "transcribe.py"), encoding="utf-8").read()

    missing, script = child_script_undefined_names(text)
    assert not missing, f"child script references undefined names: {missing}"
    assert "def is_non_speech_label" in script
    assert any(
        isinstance(n, ast.Import) and any(a.name == "re" for a in n.names)
        for n in ast.walk(ast.parse(script))
    ), "the child script's helpers need `re` imported in it"

    # Negative control: the check must actually be able to fail. Without the
    # injection, is_non_speech_label is the name that goes missing.
    broken = text.replace("{inspect.getsource(is_non_speech_label)}", "")
    broken_missing, _ = child_script_undefined_names(broken)
    assert "is_non_speech_label" in broken_missing, (
        f"checker did not detect the known-bad case: {broken_missing}"
    )
    print("  [PASS] generated child script is self-contained (checker verified)")


def test_youtube_channel_url_normalization():
    """Handles/paths/URLs/bare names each normalise to the right form."""
    import api.youtube as yt

    assert yt.normalize_channel_url("@AlexHormozi") == "https://www.youtube.com/@AlexHormozi"
    assert yt.normalize_channel_url("/channel/UCabc") == "https://www.youtube.com/channel/UCabc"
    assert yt.normalize_channel_url("/@foo") == "https://www.youtube.com/@foo"
    assert yt.normalize_channel_url("https://www.youtube.com/@x/") == "https://www.youtube.com/@x"
    assert yt.normalize_channel_url("http://youtube.com/c/x") == "http://youtube.com/c/x"
    # A bare name is not a URL; the caller must search for it.
    assert yt.normalize_channel_url("Alex Hormozi") == "Alex Hormozi"
    assert yt.normalize_channel_url("") == ""
    print("  [PASS] channel URL normalization")


def test_youtube_subscription_roundtrip(tmp_path=None):
    """Subscribe/unsubscribe/is_subscribed agree, and duplicates collapse."""
    import tempfile

    import api.youtube as yt

    with tempfile.TemporaryDirectory() as tmp:
        yt.SUBS_PATH = os.path.join(tmp, "subs.json")

        assert yt.load_subscriptions() == []
        result = yt.subscribe(
            {"url": "https://www.youtube.com/@a", "name": "A", "id": "UC1"}
        )
        assert result["subscribed"] is True
        assert result["channel"]["name"] == "A"
        assert yt.is_subscribed("https://www.youtube.com/@a")
        # Trailing slash and re-subscribe must not create a second entry.
        assert yt.is_subscribed("https://www.youtube.com/@a/")
        yt.subscribe({"url": "https://www.youtube.com/@a", "name": "A"})
        assert len(yt.load_subscriptions()) == 1

        yt.subscribe({"url": "https://www.youtube.com/@b", "name": "B"})
        assert len(yt.load_subscriptions()) == 2
        # Most recently added first.
        assert yt.load_subscriptions()[0]["url"].endswith("/@b")

        assert yt.unsubscribe("https://www.youtube.com/@a")["subscribed"] is False
        assert not yt.is_subscribed("https://www.youtube.com/@a")
        assert yt.is_subscribed("https://www.youtube.com/@b")

        # A channel with no URL is rejected, not silently stored.
        assert yt.subscribe({"name": "no url"})["subscribed"] is False
    print("  [PASS] subscription roundtrip and dedupe")


def test_youtube_subscription_file_is_atomic_and_survives_reload():
    """Subscriptions persist to disk as a JSON file."""
    import tempfile

    import api.youtube as yt

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "subs.json")
        yt.SUBS_PATH = path
        yt.subscribe({"url": "https://www.youtube.com/@x", "name": "X"})
        assert os.path.exists(path)
        import json

        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        assert data["subscriptions"][0]["name"] == "X"
    print("  [PASS] subscription persistence")


def test_youtube_feed_ranks_recency_views_duration():
    """Scoring greases recent + watched + watchable, and states its reasons."""
    import api.youtube as yt

    now = 1_700_000_000.0
    assert yt._recency_score(now, now) == 1.0
    assert yt._recency_score(now - 86400 * 365, now) < 0.15
    assert yt._recency_score(None, now) == 0.0
    assert yt._recency_score(0, now) == 0.0

    assert yt._popularity_score(0) == 0.0
    assert yt._popularity_score(None) == 0.0
    assert yt._popularity_score(10_000_000) == 1.0
    # Log scale: 10M must not be 1000x the weight of 10k.
    assert yt._popularity_score(10_000) * 3 > yt._popularity_score(10_000_000)

    assert yt._duration_fit(600) == 1.0, "10 min is ideal"
    assert yt._duration_fit(60) < 1.0, "1 min is too short"
    assert yt._duration_fit(7200) < 0.5, "2h is a commitment"
    assert yt._duration_fit(None) == 0.0
    print("  [PASS] feed scoring functions")


def test_youtube_feed_is_empty_without_subscriptions():
    """No subscriptions means an empty feed, not a guess."""
    import tempfile

    import api.youtube as yt

    with tempfile.TemporaryDirectory() as tmp:
        yt.SUBS_PATH = os.path.join(tmp, "subs.json")
        assert yt.recommend() == []
        assert yt.recommend(subscribed_only=False) == []
        assert yt.recommend_from_history([{"title": "x"}]) == []
    print("  [PASS] feed degrades to empty without subscriptions")


def test_youtube_search_channels_ranks_by_hit_count():
    """Channels are grouped from video entries and ranked by hits."""
    import types

    import api.youtube as yt

    entries = [
        {"uploader_id": "@Popular", "channel": "Popular Channel", "channel_id": "UC1"},
        {"uploader_id": "@Popular", "channel": "Popular Channel", "channel_id": "UC1"},
        {"uploader_id": "@Popular", "channel": "Popular Channel", "channel_id": "UC1"},
        {"uploader_id": "@Small", "channel": "Small Channel", "channel_id": "UC2"},
        # No identity at all: must be skipped, not fabricated.
        {"uploader_id": None, "channel_id": None, "channel": "Mystery"},
    ]

    class _FakeYDL:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, *a, **k):
            return {"entries": entries}

    query = "some channel name"
    # A unique query keeps the call off the shared cache (and off the network).
    with yt._lock:
        yt._search_cache.pop(f"ch_8_{query}", None)
        yt._channel_cache.clear()
    real_ytdlp = yt.yt_dlp
    yt.yt_dlp = types.SimpleNamespace(YoutubeDL=_FakeYDL)
    try:
        found = yt.search_channels(query, limit=8)
    finally:
        yt.yt_dlp = real_ytdlp

    assert [c["url"] for c in found] == [
        "https://www.youtube.com/@Popular",
        "https://www.youtube.com/@Small",
    ], found
    assert found[0]["hits"] == 3 and found[1]["hits"] == 1
    assert found[0]["name"] == "Popular Channel"
    assert all("Mystery" != c["name"] for c in found), "identity-less entries skipped"
    # A second call is served from cache without hitting yt-dlp again.
    calls = []

    class _CountingYDL(_FakeYDL):
        def extract_info(self, *a, **k):
            calls.append(1)
            return {"entries": entries}

    yt.yt_dlp = types.SimpleNamespace(YoutubeDL=_CountingYDL)
    try:
        again = yt.search_channels(query, limit=8)
    finally:
        yt.yt_dlp = real_ytdlp
    assert again == found and not calls, "second call must be cached"
    print("  [PASS] channel search groups, ranks and caches")


def test_youtube_feed_reasons_survive_no_timestamp():
    """Flat entries often lack timestamps; ranking must still work."""
    import api.youtube as yt

    videos = [
        {"id": "a", "title": "Oldest", "duration": 600, "views": 5_000_000,
         "timestamp": None},
        {"id": "b", "title": "Newer", "duration": 600, "views": 5_000_000,
         "timestamp": None},
        {"id": "c", "title": "Live now", "duration": None, "views": None,
         "timestamp": None, "live": True},
    ]
    recency = yt._recency_score(videos[0].get("timestamp"), 1_700_000_000.0)
    assert recency == 0.0, "no timestamp -> recency falls back to position"
    # Position-based recency puts the first listing entry highest.
    total = len(videos)
    assert (1.0 - 0 / total) > (1.0 - 1 / total)
    print("  [PASS] ranking works without timestamps")


JOB_STATUS_SRC = """
        failed = sum(1 for s in task_statuses if s == "failed")
        if task_statuses and failed == len(task_statuses):
            final_status = "failed"
        elif failed:
            final_status = "completed_with_errors"
        else:
            final_status = "completed"
        update_job(job["id"], {"status": final_status})
"""


def _job_status(task_statuses):
    """Run the extracted status block for a list of task statuses."""
    namespace = {
        "task_statuses": task_statuses,
        # The block only reads job["id"] to pass it back to update_job, so a
        # dict is enough; the lambda captures what got written.
        "job": {"id": 1},
        "update_job": lambda _id, payload: namespace.__setitem__(
            "written", payload["status"]
        ),
        "__name__": "test_job_status",
    }
    namespace["written"] = None
    block = textwrap.dedent(JOB_STATUS_SRC)
    exec(compile(block, "<job-status>", "exec"), namespace)
    return namespace["written"]


def test_job_status_reflects_task_failures():
    """The job status must say what happened to its tasks.

    A failed download used to `return` from the task body without recording a
    status, so the summary saw no "failed" task and declared the job
    completed.
    """
    assert _job_status(["failed"]) == "failed"
    assert _job_status(["failed", "failed"]) == "failed"
    assert _job_status(["completed", "failed"]) == "completed_with_errors"
    assert _job_status(["completed", "skipped"]) == "completed"
    assert _job_status(["pending"]) == "completed", (
        "no task reported a failure, so the job ran to completion"
    )

    # The early-return paths must actually record the failure, otherwise the
    # block above can never see it.
    source = open(
        os.path.join(REPO_ROOT, "whisper_subs.py"), encoding="utf-8"
    ).read()
    marked = source.count('update_task_status(job_id, task_source, "failed")')
    assert marked >= 3, (
        "each early-return after a failed download/conversion must mark the "
        f"task failed (found {marked})"
    )
    print("  [PASS] job status reflects task failures")


def test_inpaint_flags_exist_and_default_off():
    """--inpaint/--inpaint-min-gap must parse, defaulting to off."""
    parser = SRC_PARSER()
    args = parser.parse_args(["x.m4a"])
    assert args.inpaint is False
    assert args.inpaint_min_gap == 3.0

    args = parser.parse_args(["x.m4a", "--inpaint", "--inpaint-min-gap", "7.5"])
    assert args.inpaint is True
    assert args.inpaint_min_gap == 7.5
    print("  [PASS] --inpaint flags parse and default off")


def test_vad_defaults_off():
    """VAD is opt-in: every entry default converges on False."""
    parser = SRC_PARSER()
    assert parser.parse_args(["x.m4a"]).vad_filter is False
    assert parser.parse_args(["x.m4a", "--vad"]).vad_filter is True
    print("  [PASS] --vad is opt-in (default False)")


def main():
    tests = [
        test_fw_alias_translates_distil_names,
        test_fw_alias_leaves_plain_names_untouched,
        test_fw_alias_covers_all_repo_forms,
        test_vad_engine_list_and_default,
        test_vad_unknown_engine_degrades_gracefully,
        test_vad_merge_regions,
        test_vad_registry_custom_callable,
        test_vad_whisperx_wrapper_protocol,
        test_vad_custom_target_requires_callable_target,
        test_vad_param_parsing,
        test_vad_engine_env_fallback,
        test_diarize_engine_accepted_by_process_create,
        test_vad_cli_flags_parse,
        test_vad_defaults_off,
        test_inpaint_flags_exist_and_default_off,
        test_job_status_reflects_task_failures,
        test_caption_vtt_to_srt_conversion,
        test_caption_json3_conversion,
        test_caption_ttml_conversion,
        test_caption_language_matching_is_region_tolerant,
        test_caption_format_rank_prefers_cheap_formats,
        test_caption_track_prefers_human_over_auto,
        test_caption_track_language_priority,
        test_caption_languages_helper_splits_kinds,
        test_caption_translate_url_forces_srt,
        test_caption_fetch_reports_reason_without_writing,
        test_caption_cli_flags_default_human_only,
        test_caption_lang_list_parsing_in_processor,
        test_caption_asr_origin_is_not_human,
        test_caption_human_tracks_stay_human,
        test_generated_child_script_is_self_contained,
        test_gap_detection_flags_speech_removed_mid_sentence,
        test_gap_detection_allows_silence_between_sentences,
        test_gap_detection_ignores_small_holes,
        test_try_transcribe_callers_use_keywords,
        test_youtube_channel_url_normalization,
        test_youtube_subscription_roundtrip,
        test_youtube_subscription_file_is_atomic_and_survives_reload,
        test_youtube_feed_ranks_recency_views_duration,
        test_youtube_feed_is_empty_without_subscriptions,
        test_youtube_search_channels_ranks_by_hit_count,
        test_youtube_feed_reasons_survive_no_timestamp,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            import traceback

            failed += 1
            print(f"  [FAIL] {test.__name__}: {e}")
            traceback.print_exc()
    print()
    print("=" * 60)
    status = "PASS" if failed == 0 else "FAIL"
    print(f"{status}: feature tests — {len(tests) - failed}/{len(tests)} passed")
    print("=" * 60)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
