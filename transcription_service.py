from flask import Flask, request, jsonify
import os
import json
from youtubesubs import YoutubeSubs
import transcribe
from flask_socketio import SocketIO, emit
import shutil

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configure shared paths
HOST_OUTPUT_DIR = "/data/output"  # Maps to ~/Documents/Youtube-Subs on host
HOST_INPUT_DIR = "/data/input"    # Maps to ./input on host

def progress_callback(msg):
    """Send progress updates through WebSocket"""
    print(msg)  # Log to Docker logs
    socketio.emit('progress', {'message': msg})

@app.route('/transcribe', methods=['POST'])
def handle_transcription():
    try:
        data = request.get_json()
        
        # Extract parameters
        url = data.get('url')
        model_name = data.get('model_name', 'base')
        device = data.get('device', 'cuda')
        compute_type = data.get('compute_type', 'int8_float32')
        force_device = data.get('force_device', False)
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        
        # Initialize YoutubeSubs with host output directory
        yt = YoutubeSubs(
            model_name=model_name,
            device=device,
            compute=compute_type,
            force_device=force_device,
            subs_dir=HOST_OUTPUT_DIR,
            enable_logging=True
        )
        
        # Set time range if specified
        yt.start_time = start_time
        yt.end_time = end_time
        
        # Process URL
        yt.process_single_url(url, callback=progress_callback)
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/process_local', methods=['POST'])
def handle_local_file():
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        model_name = data.get('model_name', 'base')
        device = data.get('device', 'cuda')
        compute_type = data.get('compute_type', 'int8_float32')
        force_device = data.get('force_device', False)
        
        # Get the filename and create paths
        filename = os.path.basename(file_path)
        host_input_path = os.path.join(HOST_INPUT_DIR, filename)
        
        # Copy file to shared input directory if it's not already there
        if not os.path.exists(host_input_path):
            shutil.copy2(file_path, host_input_path)
        
        # Process the file
        success = transcribe.process_create(
            file=host_input_path,
            model_name=model_name,
            srt_file=os.path.join(HOST_OUTPUT_DIR, os.path.splitext(filename)[0] + ".srt"),
            device=device,
            compute_type=compute_type,
            force_device=force_device,
            write=progress_callback
        )
        
        # Cleanup input file
        if os.path.exists(host_input_path):
            os.remove(host_input_path)
            
        return jsonify({"status": "success" if success else "error"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True) 