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
        num_speakers: Optional[int] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        """Transcribe with WhisperX.

        Diarization (``diarize=True``) needs an HF token and uses pyannote.
        ``num_speakers`` pins the count exactly; otherwise ``min_speakers``
        / ``max_speakers`` bound the automatic estimate.
        """
        import whisperx
        import torch

        _device = "cuda" if device == "cuda" and torch.cuda.is_available() else "cpu"

        write(f"Loading WhisperX model: {model}")
        # VAD runs inside the pipeline when enabled: upstream load_model
        # wires vad_method ("pyannote" needs an HF token; silero ships
        # weights with the package). Disabling here keeps raw segmentation.
        # A custom VAD runs before the model: its regions replace
        # whisperx's own segmentation. `vad_model` outranks `vad_method`
        # inside load_model, so naming one keeps whisperx's built-in
        # silero/pyannote path when no custom engine is requested.
        use_vad = kwargs.get("vad", True)
        vad_engine = kwargs.get("vad_engine")
        vad_model_obj = None
        if use_vad and vad_engine and vad_engine not in ("silero", "pyannote"):
            try:
                import vad as _vad_mod

                vad_model_obj = _vad_mod.build_whisperx_vad(
                    audio_file, vad_engine,
                    params=kwargs.get("vad_params_extra"), write=write,
                )
                if vad_model_obj is None:
                    write(f"VAD {vad_engine} produced no regions; using raw audio")
            except Exception as e:
                write(f"VAD {vad_engine} unavailable ({e}); using raw audio")

        load_kwargs = {}
        if use_vad and vad_model_obj is None:
            load_kwargs["vad_method"] = kwargs.get("vad_method", "silero")
            if load_kwargs["vad_method"] == "pyannote":
                load_kwargs["vad_options"] = {}
        else:
            load_kwargs["vad_model"] = vad_model_obj
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
                    diarize_segments = diarize_model(
                        audio,
                        num_speakers=num_speakers,
                        min_speakers=min_speakers,
                        max_speakers=max_speakers,
                    )
                    result = whisperx.assign_word_speakers(
                        diarize_segments, result
                    )
                except Exception as e:
                    write(f"Diarization failed ({e}), continuing without speakers")

        # Build cues: one per speaker turn, low-confidence words dropped.
        #
        # Two splits compose here, and the order matters:
        #   1. Speaker turns — consecutive words sharing a speaker form a
        #      group. pyannote labels each *word*, so a segment that spans
        #      a hand-over yields one cue per speaker.
        #   2. Confidence gaps *inside* a group — a dropped word means the
        #      model guessed (music, overlap), so the text either side is
        #      not contiguous and must not be joined (joining is what makes
        #      furigana read the wrong word: 今日は + 天気 → こんにちは).
        # The *unfiltered* group is what the gap splitter sees; passing the
        # filtered list would hide the very gaps it exists to find.
        min_conf = float(kwargs.get("min_word_confidence", 0.4))
        segments: List[Segment] = []
        for seg in result.get("segments", []):
            words = seg.get("words") or []
            seg_speaker = seg.get("speaker") or ""

            groups: List[List[Dict[str, Any]]] = []
            current: List[Dict[str, Any]] = []
            current_speaker: Optional[str] = None
            for w in words:
                # Fall back to the segment-level label when the diarizer
                # only annotated segments (older WhisperX, or no diarize).
                spk = w.get("speaker") or seg_speaker
                if spk != current_speaker:
                    if current:
                        groups.append(current)
                    current = []
                    current_speaker = spk
                current.append(w)
            if current:
                groups.append(current)

            for grp in groups:
                speaker = grp[0].get("speaker") or seg_speaker or ""
                kept = [
                    w for w in grp
                    if float(w.get("score", 1.0)) >= min_conf
                    and w.get("word", "").strip()
                ]
                if not kept:
                    continue
                for cue_start, cue_end, cue_words in _split_on_confidence_gaps(
                    kept, grp
                ):
                    cue_text = _rebuild_text(cue_words, detected_lang)
                    if not cue_text:
                        continue
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
