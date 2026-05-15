"""VoxtralAdapter - Mistral Voxtral multimodal ASR models."""
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from model import Segment, TranscriptionAdapter, register_adapter


@register_adapter
class VoxtralAdapter(TranscriptionAdapter):
    """Transcription via Mistral Voxtral models (multimodal audio LLM)."""

    @property
    def prefix(self) -> str:
        return "voxtral"

    @property
    def display_name(self) -> str:
        return "Voxtral (Mistral)"

    def is_available(self) -> bool:
        try:
            from transformers import AutoModel
            return True
        except ImportError:
            return False

    def get_model_names(self) -> List[str]:
        return ["voxtral-mini"]

    def transcribe(
        self,
        audio_file: str,
        model: str,
        language: Optional[str] = None,
        write: Callable = print,
        temperature: float = 0.0,
        device: str = 'cpu',
        **kwargs,
    ) -> Tuple[List[Segment], Any]:
        import torch
        from transformers import AutoProcessor, VoxtralForConditionalGeneration

        hf_model_map = {
            'voxtral-mini': 'mistral-community/Voxtral-Mini',
        }
        hf_model_id = hf_model_map.get(model, model)

        write(f"Loading Voxtral model: {hf_model_id}")
        torch_device = 'cuda:0' if device == 'cuda' and torch.cuda.is_available() else 'cpu'
        torch_dtype = torch.float16 if torch_device != 'cpu' else torch.float32

        processor = AutoProcessor.from_pretrained(hf_model_id)
        model_obj = VoxtralForConditionalGeneration.from_pretrained(
            hf_model_id, torch_dtype=torch_dtype, low_cpu_mem_usage=True,
        )
        model_obj.to(torch_device)

        write("Transcribing with Voxtral...")
        inputs = processor(
            audios=[audio_file],
            return_tensors='pt',
            sampling_rate=16000,
        ).to(torch_device)

        lang_instruction = f"Transcribe the following audio in {language}. " if language else "Transcribe the following audio. "
        prompt_text = processor.apply_chat_template(
            [{'role': 'user', 'content': lang_instruction}],
            tokenize=False,
            add_generation_prompt=True,
        )
        prompt_inputs = processor(text=prompt_text, return_tensors='pt').to(torch_device)

        generate_kwargs = {
            'max_new_tokens': 4096,
            'temperature': temperature if temperature > 0 else 0.0,
        }
        if temperature == 0.0:
            generate_kwargs['do_sample'] = False

        output_ids = model_obj.generate(**inputs, **generate_kwargs)
        text = processor.batch_decode(output_ids, skip_special_tokens=True)[0]

        segments: List[Segment] = [Segment(start=0.0, end=0.0, text=text.strip())]
        info = type('Info', (), {'duration': 0.0, 'language': language or 'auto'})()
        return segments, info
