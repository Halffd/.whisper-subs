import model
import sys
args = model.getName(sys.argv, 'base', True)

from RealtimeSTT import AudioToTextRecorder
from pynput import keyboard
import threading
from flask import Flask, render_template, jsonify, request
import os
import signal
import caption.gui as gui

app = Flask(__name__)

# Global variables to share data between threads
transcribed_text = []
quit_program = False
PORT = 5000
ui = None
zoomFactor = 2
transparencyFactor = 1

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/transcript', methods=['GET'])
def get_transcript():
    global transcribed_text
    return jsonify({'text': transcribed_text})

def on_press(key):
    try:
        if key == keyboard.Key.cmd:
            if keyboard.Key.q in key:
                print('Win+Q pressed')
                end()
    except AttributeError:
        pass
def end():
    if os.name == 'nt':
        os._exit(1)
    else:
        os.kill(os.getpid(), signal.SIGINT)
def process_text(text):
    global transcribed_text, ui
    print(text, end=" ", flush=True)
    transcribed_text.append(text)
    if ui:
        ui.addNewLine(text)

def main_program():
    with AudioToTextRecorder(
        spinner=False,
        model=args['model_name'],
        language=args['lang'],
        # enable_realtime_transcription=True,
        realtime_model_type=args['realtime_model'],
    ) as recorder:
        print("Say something...")
        while True:
            recorder.text(process_text)

def start_server():
    print(f"Listening on http://localhost:{PORT}")
    app.run(debug=True, host='0.0.0.0', port=PORT)
def zoom(factor):
    if not gui or factor == 0 or gui.fontSize + factor <= 0:
        return
    gui.fontSize += factor
    gui.styling()
def zoomIn():
    zoom(zoomFactor)
def zoomOut():
    zoom(-zoomFactor)
def transparency(factor):
    if not gui or factor == 0 or gui.alphs + factor <= 0 or gui.alpha + factor > 255:
        return
    gui.alphs += factor
    gui.styling()
def transparencyAdd():
    transparency(transparencyFactor)
def transparencySub():
    transparency(-transparencyFactor)
def clear():
    if gui:
        gui.lines = []
        gui.clearCaption()
def input():
    with keyboard.GlobalHotKeys({
        '<ctrl>+<alt>+q': end,
        '<ctrl>+<alt>+=': zoomIn,
        '<ctrl>+<alt>+-': zoomOut,
        '<ctrl>+<alt>+0': transparencyAdd,
        '<ctrl>+<alt>+9': transparencySub,
        '<ctrl>+<alt>+x': clear
        }) as h:
        h.join()
if __name__ == "__main__":
    listener = keyboard.Listener(on_press=on_press)
    listener.start()

    transcription_thread = threading.Thread(target=main_program)
    transcription_thread.start()

    input_thread = threading.Thread(target=input)
    input_thread.start()
    # Wait for all threads to finish
    if args['gui']: 
         ui = gui.draw()
         ui.run()
    elif args['web_server']: 
         start_server()
    transcription_thread.join()
    input_thread.join()