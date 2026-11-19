"""Furigana rendering for Japanese cues.

Readings are context-dependent: 今日 alone is きょう but 今日は can tokenize
as the greeting こんにちは, and 行 is い/ぎょう depending on okurigana.
Whole-cue kakasi conversion mangles both. WhisperX word alignment supplies
morpheme-ish boundaries, so readings are computed **per aligned word** —
kakasi on a single word picks the right dictionary entry far more often.

Cues without word-level detail (plain whisper backends) fall back to
whole-cue conversion, best effort.

Chinese is never annotated: pykakasi is Japanese-only; pinyin/jyutping
would need a different dictionary.
"""

from typing import Any, Dict, List, Optional

import pykakasi

# One converter: construction loads the dictionary (~100ms) — reused.
_KKS = pykakasi.kakasi()

# Skip annotations for chunks this long: long kanji strings are usually
# proper nouns or compounds kakasi mangles, and a wrong reading across six
# kanji hurts more than no reading.
_MAX_FURIGANA_CHUNK = 6

_CJK_RANGES = (
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # Extension A
    (0x20000, 0x2A6DF),  # Extension B+
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _has_kanji(text: str) -> bool:
    return any(_is_cjk(c) for c in text)


def _reading_of(token: str) -> Optional[str]:
    """Kana reading of one word/token; None when identity or unknown."""
    if not token or not _has_kanji(token):
        return None
    if len(token) > _MAX_FURIGANA_CHUNK:
        return None
    items = _KKS.convert(token)
    reading = "".join(i.get("hira", "") for i in items)
    # Identity means the token was already kana-shaped or unknown to the
    # dictionary; annotating would duplicate the same characters.
    return None if reading == token or not reading else reading


def _annotate_words(words: List[Dict[str, Any]]) -> str:
    """Build cue text annotating kanji-bearing words with their readings.

    WhisperX Japanese alignment emits per-character words; kakasi on a
    single kanji picks an arbitrary on/kun reading (今→いま, 日→にち).
    Adjacent CJK words merge into one token first — kakasi on the merged
    chunk reads 今日 as きょう and 天気 as てんき.
    """
    tokens = _merge_cjk_runs([w.get("word", "") for w in words])
    out: List[str] = []
    for token in tokens:
        reading = _reading_of(token)
        if reading:
            out.append(f"{token}（{reading}）")
        else:
            out.append(token)
    return "".join(out).strip()


def _merge_cjk_runs(tokens: List[str]) -> List[str]:
    """Join adjacent CJK tokens; keep kana/latin as-is."""
    merged: List[str] = []
    run: List[str] = []
    for t in tokens:
        if t and _has_kanji(t):
            run.append(t)
        else:
            if run:
                merged.append("".join(run))
                run = []
            merged.append(t)
    if run:
        merged.append("".join(run))
    return merged


def _annotate_whole_text(text: str) -> str:
    """Fallback without word timings: kakasi over the full cue.

    Best effort — whole-cue conversion can mis-tokenize greetings
    (今日は → こんにちは). Only annotate chunks the dictionary resolves
    unambiguously; skip the rest rather than guess wrong.
    """
    if not _has_kanji(text):
        return text
    out: List[str] = []
    for item in _KKS.convert(text):
        orig = item.get("orig", "")
        if not orig:
            continue
        reading = item.get("hira", "")
        if (
            _has_kanji(orig)
            and reading
            and reading != orig
            and len(orig) <= _MAX_FURIGANA_CHUNK
        ):
            out.append(f"{orig}（{reading}）")
        else:
            out.append(orig)
    return "".join(out)


def render_furigana(segments: List) -> List:
    """Annotate Japanese cues in-place; returns the list for chaining.

    Language gating: only cues tagged ja (or untagged cues containing
    CJK, for segment-level backends that don't emit language) are
    annotated.
    """
    for seg in segments:
        lang = (getattr(seg, "language", None) or "").lower()
        if lang:
            if not lang.startswith("ja"):
                continue
        elif not _has_kanji(seg.text):
            continue

        # Speaker labels ride on the text ("[SPK_1] …") and must survive
        # the rebuild — strip, annotate, re-attach.
        prefix = ""
        text = seg.text
        speaker = getattr(seg, "speaker", None)
        if speaker and text.startswith(f"[{speaker}] "):
            prefix = f"[{speaker}] "
            text = text[len(prefix):]

        words = getattr(seg, "words", None)
        if words:
            annotated = _annotate_words(words)
            # Word reconstruction may drift from the original text (the
            # confidence filter upstream already trimmed it). Only use it
            # when it produced content; otherwise fall back.
            seg.text = prefix + (annotated if annotated else _annotate_whole_text(text))
        else:
            seg.text = prefix + _annotate_whole_text(text)
    return segments
