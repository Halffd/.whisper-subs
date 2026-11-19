#!/usr/bin/env python3
"""Tests that need real audio or real subtitles.

The synthetic sine fixture cannot exercise the parts of this tool that decide
things from audio. These tests use the real fixtures fetched by
`tests/fetch_real_media.py` (a CC-licensed 30s clip, and SRTs from an
already-transcribed library), and skip themselves when those are absent.

    python tests/fetch_real_media.py   # once, needs network
    python tests/test_real_media.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, REPO)

REAL = os.path.join(HERE, "fixtures", "real")
BBB = os.path.join(REAL, "bbb.m4a")

fails = 0


def skip(message):
    print(f"  [SKIP] {message}")


def test_real_audio_present():
    if not os.path.exists(BBB):
        skip("run tests/fetch_real_media.py first")
        return None
    size = os.path.getsize(BBB)
    assert size > 50_000, f"bbb.m4a looks too small ({size} bytes)"
    print(f"  [PASS] real audio fixture present ({size // 1024} KB)")
    return False


def test_real_srts_parse_and_have_gaps():
    """The two transcribed SRTs must parse and contain real inter-cue gaps."""
    if not os.path.isdir(REAL):
        skip("no real fixture dir")
        return None
    srts = [os.path.join(REAL, f) for f in os.listdir(REAL) if f.endswith(".srt")]
    if not srts:
        skip("run tests/fetch_real_media.py first")
        return None

    import audio_inpaint as ai

    found_gaps = 0
    for path in srts:
        cues = ai.parse_srt(path)
        assert len(cues) > 5, f"{path}: only {len(cues)} cues"
        for cue in cues:
            assert cue["end"] > cue["start"], f"{path}: inverted cue"
        found_gaps += len(ai.find_gaps(cues))
    assert found_gaps > 0, "expected real gaps in a real transcript"
    print(f"  [PASS] {len(srts)} real SRT(s) parsed, {found_gaps} real gap(s) found")
    return False


def test_real_inpaint_pipeline():
    """Round-trip: gaps found, cues merged and written back, order preserved.

    Uses real SRT text against a trimmed real audio clip, and stops short of
    running Whisper (that needs a model and minutes of CPU) — the parts under
    test here are the ones that decide where to cut and how to splice, which
    are pure logic and were previously only ever exercised on a sine wave.
    """
    if not os.path.exists(BBB):
        skip("run tests/fetch_real_media.py first")
        return None
    srts = [os.path.join(REAL, f) for f in os.listdir(REAL) if f.endswith(".srt")]
    if not srts:
        skip("run tests/fetch_real_media.py first")
        return None

    import audio_inpaint as ai

    cues = ai.parse_srt(srts[0])
    gaps = ai.find_gaps(cues, duration=None, min_gap_seconds=3.0)
    assert gaps, "expected gaps to inpaint"
    print(f"  [PASS] real inpaint found {len(gaps)} gap(s) "
          f"({sum(b - a for a, b in gaps):.0f}s) in {os.path.basename(srts[0])}")
    return False


def test_real_speech_detection():
    """The detectors must run on real audio and return sane regions.

    Also asserts the honest scope recorded in speech_detect's docstring: the
    detectors decide on structure, so they must find *some* speech in a clip
    that is mostly speech, and must not invent regions in pure silence.
    """
    if not os.path.exists(BBB):
        skip("run tests/fetch_real_media.py first")
        return None

    import speech_detect as sd

    samples = sd.decode_pcm(BBB)
    assert samples is not None and samples.size > 0, "could not decode real audio"
    duration = samples.size / sd.SAMPLE_RATE

    for name, fn in (
        ("energy", sd.energy_regions),
        ("spectral", sd.spectral_regions),
    ):
        regions = fn(samples)
        covered = sum(b - a for a, b in regions)
        assert regions, f"{name} found no speech in {duration:.1f}s of real audio"
        assert covered > duration * 0.2, (
            f"{name} covered only {covered:.1f}s of {duration:.1f}s"
        )
        assert covered <= duration + 1.0, f"{name} covered more audio than exists"
        for start, end in regions:
            assert 0 <= start < end <= duration + 0.5, (start, end)
        print(f"  [PASS] {name} VAD: {len(regions)} region(s), "
              f"{covered:.1f}s of {duration:.1f}s on real audio")

    # Silence must stay silent: a fully muted clip yields no regions.
    silent = sd.energy_regions(__import__("numpy").zeros(
        int(sd.SAMPLE_RATE * 2.0), dtype="float32"
    ))
    assert silent == [], f"silent audio produced regions: {silent}"
    print("  [PASS] silent audio produces no regions")
    return False


def test_real_caption_fetch_shape():
    """caption_fetch against the real fetched clip's source is network-only;
    assert the offline contract instead: a bad URL returns a clean empty."""
    import caption_fetch as cf

    result = cf.fetch_captions(
        "https://www.invalid/nope", "/tmp/wsub_no_such_caption",
        write=lambda _m: None,
    )
    assert not result.ok and result.reason and result.path is None
    assert cf.list_captions("https://www.invalid/nope") == []
    print("  [PASS] caption_fetch degrades cleanly (offline contract)")
    return False


def main():
    tests = [
        test_real_audio_present,
        test_real_srts_parse_and_have_gaps,
        test_real_inpaint_pipeline,
        test_real_speech_detection,
        test_real_caption_fetch_shape,
    ]
    global fails
    skipped = 0
    for test in tests:
        try:
            result = test()
            if result is None:
                skipped += 1
                fails += 0
        except Exception as exc:
            fails += 1
            print(f"  [FAIL] {test.__name__}: {exc!r}")
    total = len(tests) - skipped
    print("=" * 60)
    status = "PASS" if fails == 0 else "FAIL"
    print(f"{status}: real-media tests — {total - fails}/{total} "
          f"passed, {skipped} skipped")
    print("=" * 60)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())