"""WhisperXAdapter - WhisperX with forced alignment and diarization."""
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class WhisperXAdapter(TranscriptionAdapter):
    """Transcription via WhisperX (faster-whisper + alignment + diarization)."""

    @property
    def prefix(self) -> str:
        return "whisperx"

    @property
    def display_name(self) -> str:
        return "WhisperX"

    def is_available(self) -> bool:
        try:
            import whisperx
            return True
        except ImportError:
            return False

    def get_model_names(self) -> List[str]:
        return ["large-v3", "large-v2", "medium", "small", "base", "tiny",
                "medium.en", "small.en", "base.en", "tiny.en"]

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        device: str = 'cpu',
        compute_type: str = 'int8',
        diarize: bool = False,
        hf_token: Optional[str] = None,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        import whisperx
        import torch

        _device = "cuda" if device == "cuda" and torch.cuda.is_available() else "cpu"

        write(f"Loading WhisperX model: {model}")
        # VAD runs inside the pipeline when enabled: upstream load_model
        # wires vad_method ("pyannote" needs an HF token; silero ships
        # weights with the package). Disabling here keeps raw segmentation.
        use_vad = kwargs.get("vad", True)
        load_kwargs = {}
        if use_vad:
            load_kwargs["vad_method"] = kwargs.get("vad_method", "silero")
            if load_kwargs["vad_method"] == "pyannote":
                load_kwargs["vad_options"] = {}
        asr = whisperx.load_model(
            model,
            _device,
            compute_type=compute_type,
            **load_kwargs,
        )
        audio = whisperx.load_audio(audio_file)

        write("Transcribing...")
        result = asr.transcribe(audio, batch_size=16, language=language)
        detected_lang = result.get("language", language or "en")
        write(f"Detected language: {detected_lang}")

        # Forced alignment: word-level timestamps + per-word confidence.
        # The wav2vec2 alignment heads are per-language, so the model must
        # be tagged with the detected language — a bare align() silently
        # misaligns ja/en mixes. Char alignments are off; words suffice.
        try:
            align_model, align_metadata = whisperx.load_align_model(
                language_code=detected_lang, device=_device,
            )
            result = whisperx.align(
                result["segments"], align_model, align_metadata, audio,
                _device, return_char_alignments=False,
            )
        except Exception as e:
            write(f"Alignment unavailable ({e}), using segment-level output")
            return _segments_from_result(result, detected_lang, diarize=False)

        # Diarization after alignment so words carry speaker labels.
        # whisperx >= 3.3.4 moved DiarizationPipeline to whisperx.diarize;
        # older releases expose it at the top level.
        if diarize:
            _hf_token = hf_token or os.environ.get("HF_TOKEN")
            if not _hf_token:
                write("HF_TOKEN not set, skipping diarization")
            else:
                try:
                    write("Running pyannote diarization...")
                    diarize_cls = getattr(
                        whisperx, "diarize", whisperx
                    ).DiarizationPipeline
                    diarize_model = diarize_cls(token=_hf_token, device=_device)
                    diarize_segments = diarize_model(audio)
                    result = whisperx.assign_word_speakers(
                        diarize_segments, result
                    )
                except Exception as e:
                    write(f"Diarization failed ({e}), continuing without speakers")

        # Confidence filter: low-score words are the model guessing at
        # lyrics/music/overlapping speech. Drop them and rebuild cue text.
        min_conf = float(kwargs.get("min_word_confidence", 0.4))
        segments: List[Segment] = []
        for seg in result.get("segments", []):
            words = seg.get("words") or []
            kept = [
                w for w in words
                if float(w.get("score", 1.0)) >= min_conf and w.get("word", "").strip()
            ]
            if not kept:
                continue
            # A confidence gap inside the cue means the model guessed
            # mid-sentence (music, overlap). Split there instead of
            # silently joining unrelated text — furigana on a re-joined
            # cue reads the wrong word boundaries (今日は+天気 would
            # come out こんにちは…).
            for cue_start, cue_end, cue_words in _split_on_confidence_gaps(
                kept, words
            ):
                cue_text = _rebuild_text(cue_words, detected_lang)
                if not cue_text:
                    continue
                speaker = seg.get("speaker", "")
                prefix = f"[{speaker}] " if speaker else ""
                segments.append(Segment(
                    start=cue_start,
                    end=cue_end,
                    text=prefix + cue_text,
                    words=cue_words,
                    confidence=_mean_confidence(cue_words),
                    language=detected_lang,
                    speaker=speaker or None,
                ))

        info = type("Info", (), {
            "duration": result.get("segments", [{}])[-1].get("end", 0.0) if segments else 0.0,
            "language": detected_lang,
            "word_count": sum(len(s.words or []) for s in segments),
        })()

        # Furigana: last, so the filter operates on confident text and the
        # annotations ride on top of it. pykakasi import failure disables
        # the feature without failing the transcription.
        if kwargs.get("furigana", False):
            try:
                from furigana import render_furigana

                render_furigana(segments)
                write("Furigana annotations applied")
            except ImportError as e:
                write(f"Furigana skipped (pip install pykakasi): {e}")

        return segments, info


def _split_on_confidence_gaps(kept_words, all_words):
    """Split kept words where dropped (low-confidence) words intervened.

    Returns (start, end, words) triples. A dropped word means the model
    was unsure of *something* between the surviving words — music, crosstalk
    — and the surviving words either side of the drop often belong to
    different utterances. Joining them produces cues whose furigana reads
    the wrong boundaries (今日は_いい_天気 → 今日は天気 → こんにちは…).
    Timing comes from the words themselves: each group spans its own
    first/last word.
    """
    if len(kept_words) == len(all_words):
        return [
            (
                float(kept_words[0].get("start", 0.0)),
                float(kept_words[-1].get("end", 0.0)),
                kept_words,
            )
        ]

    kept_ids = {id(w) for w in kept_words}
    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for w in all_words:
        if id(w) in kept_ids:
            current.append(w)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    return [
        (
            float(g[0].get("start", 0.0)),
            float(g[-1].get("end", 0.0)),
            g,
        )
        for g in groups
        if g
    ]


def _rebuild_text(words, language):
    """Rebuild cue text from filtered words.

    CJK alignment emits per-character/short-token pieces with no spaces;
    joining with spaces would render「こん にち は」. Space-joining only
    for whitespace-delimited languages.
    """
    parts = [w["word"] for w in words]
    if language in ("ja", "zh", "zh-cn", "zh-tw", "zh-hans", "zh-hant", "yue"):
        return "".join(parts).strip()
    return " ".join(p.strip() for p in parts if p.strip()).strip()


def _mean_confidence(words):
    scores = [float(w.get("score", 0.0)) for w in words]
    return round(sum(scores) / len(scores), 3) if scores else 0.0


def _segments_from_result(result, detected_lang, diarize=False):
    """Segment-level fallback when alignment is unavailable."""
    segments: List[Segment] = []
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        speaker = seg.get("speaker", "") if diarize else ""
        if speaker:
            text = f"[{speaker}] {text}"
        if not text:
            continue
        segments.append(Segment(
            start=seg.get("start", 0.0),
            end=seg.get("end", 0.0),
            text=text,
            language=detected_lang,
            speaker=speaker or None,
        ))
    info = type("Info", (), {
        "duration": result.get("segments", [{}])[-1].get("end", 0.0) if segments else 0.0,
        "language": detected_lang,
        "word_count": 0,
    })()
    return segments, info
