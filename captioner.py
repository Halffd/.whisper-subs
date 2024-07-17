from RealtimeSTT import AudioToTextRecorder

def process_text(text):
  print(text, end=" ", flush=True)

if __name__ == '__main__':
  with AudioToTextRecorder(
    spinner=False,
    model="tiny.en",
    language="en",
    # enable_realtime_transcription=True,
    realtime_model_type="tiny.en"
  ) as recorder:
    print("Say something...")
    while True:
      recorder.text(process_text)