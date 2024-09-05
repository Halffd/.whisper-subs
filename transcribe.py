import model
import faster_whisper
import torch
import logging
import psutil
import time
import sys
import subprocess

audiofile, modelname, langcode = '', 'base', None
"""
def on_error(exc_type, exc_value, tb):
    global audiofile, modelname, langcode
    import traceback
    traceback.print_exception(exc_type, exc_value, tb)
    print(audiofile, modelname, langcode, '\nrestarting')
    transcribe_audio(audiofile, modelname, langcode)


sys.excepthook = on_error
"""
logging.basicConfig()
logging.getLogger("faster_whisper").setLevel(logging.DEBUG)

def check_memory_usage():
    process = psutil.Process()
    memory_percent = process.memory_percent()
    print(f"{memory_percent}% Memory Usage")
    if memory_percent > 95:  # Check if memory usage is above 90%
        print(f"High memory usage detected ({memory_percent:.1f}%). Waiting...")
        time.sleep(10)  # Wait for 10 seconds
        check_memory_usage()  # Recursively check again
def transcribe_audio(audio_file, model_name, language = None):
    """
    Transcribes the audio from the given file using the specified Whisper model.

    Args:
        audio_file (str): Path to the audio file.
        model_name (str): The name of the Whisper model to use.

    Returns:
        The transcription result.
    """
    global audiofile, modelname, langcode
    audiofile = audio_file
    modelname = model_name
    langcode = language
    delay = 1
    model_names = model.model_names
    if model_name in model_names:
        i = model_names.index(model_name)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute = 'int8_float32' #'float32'
        for c in range(0, 3):
            if i == 2:
                device = 'cpu'
            elif i == 1:
                compute = 'int8'
            for j in range(i, -1, -1):
                check_memory_usage()
                model_name = model_names[j]
                print(model_name)
                #compute = 'int16' if 'large' in model_name or 'medium' in model_name else 'float32'
                if device == 'cuda':
                    torch.cuda.empty_cache()
                try:
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
def process_create(file, model_name, language):
    own_module = os.module
    subprocess.Popen(own_module)
if __name__ == "__main__":
    path, file, model_name, language = sys.argv[0], sys.argv[1], sys.argv[2], sys.arv[3]
    print(f"{path}: Transctribing {file} using model {model_name} and language {language}")
    transcribe_audio(file, model_name, language)