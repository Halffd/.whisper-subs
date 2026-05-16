"""ParakeetAdapter - NVIDIA NeMo Parakeet ASR models."""
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class ParakeetAdapter(TranscriptionAdapter):
    """Transcription via NVIDIA NeMo Parakeet models (TDT/CTC/RNNT)."""

    @property
    def prefix(self) -> str:
        return "parakeet"

    @property
    def display_name(self) -> str:
        return "NVIDIA Parakeet (NeMo)"

    def is_available(self) -> bool:
        try:
            import nemo
            import hydra
            import fiddle
            return True
        except ImportError:
            return False

    def get_model_names(self) -> List[str]:
        return [
            "parakeet-tdt-0.6b-v2",
            "parakeet-tdt-0.6b-v3",
            "parakeet-ctc-1.1b",
            "parakeet-rnnt-1.1b",
            "parakeet-ctc-0.6b",
            "parakeet-rnnt-0.6b",
        ]

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        try:
            import nemo.collections.asr as nemo_asr
        except ImportError as e:
            raise ImportError(
                f"NeMo ASR dependencies not available: {e}. "
                f"Install with: pip install nemo-toolkit[asr] hydra-core fiddle"
            ) from e

        nemo_model_map = {
            'parakeet-tdt-0.6b-v2': 'nvidia/parakeet-tdt-0.6b-v2',
            'parakeet-tdt-0.6b-v3': 'nvidia/parakeet-tdt-0.6b-v3',
            'parakeet-ctc-1.1b': 'nvidia/parakeet-ctc-1.1b',
            'parakeet-rnnt-1.1b': 'nvidia/parakeet-rnnt-1.1b',
            'parakeet-ctc-0.6b': 'nvidia/parakeet-ctc-0.6b',
            'parakeet-rnnt-0.6b': 'nvidia/parakeet-rnnt-0.6b',
        }
        nemo_id = nemo_model_map.get(model, model)

        write(f"Loading Parakeet model: {nemo_id}")
        try:
            asr_model = nemo_asr.models.ASRModel.from_pretrained(
                model_name=nemo_id,
            )
        except Exception as e:
            err_msg = str(e)
            if '401' in err_msg or 'Unauthorized' in err_msg or 'Repository Not Found' in err_msg:
                raise RuntimeError(
                    f"Cannot access '{nemo_id}' on HuggingFace (gated model). "
                    f"You need to:\n"
                    f"  1. Request access at https://huggingface.co/{nemo_id}\n"
                    f"  2. Set your HF token: huggingface-cli login\n"
                    f"     or: export HF_TOKEN=your_token\n"
                    f"Original error: {e}"
                ) from e
            raise

        write("Transcribing with Parakeet...")
        output = asr_model.transcribe([audio_file], timestamps=True)

        segments: List[Segment] = []
        if output and isinstance(output, list) and len(output) > 0:
            result = output[0]
            ts = None
            if hasattr(result, 'timestamp') and result.timestamp:
                ts = result.timestamp
            elif isinstance(result, dict) and 'timestamp' in result:
                ts = result['timestamp']

            if ts:
                seg_timestamps = ts.get('segment', []) if isinstance(ts, dict) else []
                if seg_timestamps:
                    for stamp in seg_timestamps:
                        if isinstance(stamp, dict):
                            segments.append(Segment(
                                start=float(stamp.get('start', 0.0)),
                                end=float(stamp.get('end', 0.0)),
                                text=stamp.get('segment', stamp.get('word', '')).strip(),
                            ))
                        else:
                            segments.append(Segment(
                                start=float(getattr(stamp, 'start', 0.0)),
                                end=float(getattr(stamp, 'end', 0.0)),
                                text=getattr(stamp, 'segment', getattr(stamp, 'word', '')).strip(),
                            ))
                if not segments:
                    word_timestamps = ts.get('word', []) if isinstance(ts, dict) else []
                    for stamp in word_timestamps:
                        if isinstance(stamp, dict):
                            segments.append(Segment(
                                start=float(stamp.get('start', 0.0)),
                                end=float(stamp.get('end', 0.0)),
                                text=stamp.get('word', stamp.get('text', '')).strip(),
                            ))
                        else:
                            segments.append(Segment(
                                start=float(getattr(stamp, 'start', 0.0)),
                                end=float(getattr(stamp, 'end', 0.0)),
                                text=getattr(stamp, 'word', getattr(stamp, 'text', '')).strip(),
                            ))

        if not segments:
            text = ''
            if output and isinstance(output, list) and len(output) > 0:
                result = output[0]
                text = result.text if hasattr(result, 'text') else str(result)
            elif hasattr(output, 'text'):
                text = output.text
            segments = [Segment(start=0.0, end=0.0, text=text)]

        info = type('Info', (), {
            'duration': segments[-1].end if segments else 0.0,
            'language': language or 'en',
        })()
        return segments, info
