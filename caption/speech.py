import sys
from RealtimeSTT import AudioToTextRecorder
from pynput import keyboard
import threading
import os
import signal
import caption.web as web
import caption.gui as gui
import logging

class Speech:
    def __init__(self, args):
        self.transcribed_text = []
        self.quit_program = False
        self.ui = None
        self.args = args
        self.stop = False
        self.recorder = None

    def process_text(self, text):
        print(text, end=" ", flush=True)
        self.transcribed_text.append(text)
        if self.ui:
            self.ui.addNewLine(text)

    def main_program(self):
        with AudioToTextRecorder(
            spinner=True,
            model=self.args['model_name'],
            language=self.args['lang'],
            #enable_realtime_transcription=True,
            realtime_model_type=self.args['realtime_model'],
            #level=logging.DEBUG,
            #webrtc_sensitivity=1,
            min_length_of_recording=0.75 if self.args['lang'] is None or 'en' in self.args['lang'] else 3,
            silero_sensitivity=0.2,
        ) as recorder:
            self.recorder = recorder
            print("Say something...")
            while not self.stop:
                recorder.text(self.process_text)

    def start(self):
        transcription_thread = threading.Thread(target=self.main_program)
        transcription_thread.start()

        if self.args['gui']:
            self.ui = gui.initialize()
            self.ui.language = self.args['lang']
            self.ui.speech = self
            self.ui.run()
        elif self.args['web']:
            web.Web(self.args).start_server()
        transcription_thread.join()
