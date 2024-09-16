import sys
from RealtimeSTT import AudioToTextRecorder
from pynput import keyboard
import threading
import os
import signal
import caption.web as web
import caption.gui as gui
import caption.input as input
import caption.log as log
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

    def get_min_length_of_recording(self):
        conditions = {
            ('en', 'tiny.en'): 0.1,
            ('en', 'tiny'): 0.15,
            ('en', 'base.en'): 0.2,
            ('en', 'base'): 0.25,
            ('en', 'small.en'): 0.8,
            ('en', 'small'): 0.85,
            ('en', 'medium.en'): 4.8,
            ('en', 'medium'): 4.85,
            ('en', 'large'): 8.5,
            ('en', 'large-v2'): 19,
            ('en', 'large-v3'): 48,
            ('', 'tiny'): 0.5,
            ('', 'base'): 2,
            ('', 'small'): 10,
            ('', 'medium'): 30,
            ('', 'large'): 60,
            ('', 'large-v2'): 150,
            ('', 'large-v3'): 300,
        }

        lang = 'en' if not self.args['lang'] is None and 'en' in self.args['lang'] else ''

        return conditions.get((lang, self.args['model_name']), 1)
    def main_program(self):
        with AudioToTextRecorder(
            spinner=True,
            model=self.args['model_name'],
            language=self.args['lang'],
            compute_type="float32",
            #enable_realtime_transcription=True,
            realtime_model_type=self.args['realtime_model'],
            #level=logging.DEBUG,
            #debug_mode=True,
            webrtc_sensitivity=0, #if self.args['lang'] is None or 
            min_length_of_recording=self.get_min_length_of_recording(), #0.2 if 'en' in self.args['lang'] else 3 if 'base' in self.args['model_name'] or 'tiny' in self.args['model_name'] else 10,
            silero_sensitivity=0.1,
        ) as recorder:
            self.recorder = recorder
            print("> ", end="", flush=True)
            while not self.stop:
                recorder.text(self.process_text)
            os._exit(0)

    def start(self):
        control = input.Input(self.args)
        logger = log.Log(self.args)
        
        transcription_thread = threading.Thread(target=self.main_program)
        transcription_thread.start()

        if self.args['gui']:
            self.ui = gui.initialize()
            self.ui.language = self.args['lang']
            self.ui.speech = self
            self.ui.log = logger
            control.ui = self.ui
            self.ui.run()
        elif self.args['web']:
            web.Web(self.args).start_server()
        transcription_thread.join()
        if logger.file:
            logger.close_log_file()
