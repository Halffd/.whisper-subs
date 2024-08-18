import model
import faster_whisper
import torch
import logging

logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)

def transcribe_audio(audio_file, model_name, language = None):
    """
    Transcribes the audio from the given file using the specified Whisper model.

    Args:
        audio_file (str): Path to the audio file.
        model_name (str): The name of the Whisper model to use.

    Returns:
        The transcription result.
    """
    model_names = model.model_names
    if model_name in model_names:
        i = model_names.index(model_name)
        for j in range(i, -1, -1):
            model_name = model_names[j]
            print(model_name)
            #compute = 'int16' if 'large' in model_name or 'medium' in model_name else 'float32'
            compute = 'float32'
            try:
                device = "cuda" if torch.cuda.is_available() else "cpu"
                print(f"Trying model {model_name} on {device}")
                whisper_model = faster_whisper.WhisperModel(model_name, device=device, compute_type=compute)
                if language is not None:
                    segments, info = whisper_model.transcribe(audio_file,
                                                    language=language, 
                                                    vad_filter=True,
                                                    vad_parameters=dict(min_silence_duration_ms=500,
                                                                        max_speech_duration_s=5))
                    return segments
                else:
                    segments, info = whisper_model.transcribe(audio_file,
                                                    vad_filter=True,
                                                    vad_parameters=dict(min_silence_duration_ms=500,
                                                                        max_speech_duration_s=5))
                    return segments
            except RuntimeError as e:
                print(e)
            except Exception as e:
                print(e)
    else:
        print(f"Model '{model_name}' not found in the available model names.")
    return None
