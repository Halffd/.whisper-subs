from RealtimeSTT import AudioToTextRecorder

with AudioToTextRecorder() as recorder:
    print(recorder.text())