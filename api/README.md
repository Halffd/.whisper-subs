# WhisperSubs API

A FastAPI server for audio/video transcription services using Whisper.

## Features

- REST API for starting transcription tasks
- Background processing for long-running tasks
- Task status tracking
- Support for all Whisper models
- Support for YouTube, Twitch, and local file processing

## Installation

1. Install dependencies:
   ```bash
   pip install -r api/requirements.txt
   pip install -r requirements.txt  # project requirements
   ```

2. Install additional requirements:
   ```bash
   pip install uvicorn[standard]
   ```

## Usage

### Running the Server

```bash
# Run the server directly
python api/main.py --host 0.0.0.0 --port 8000

# Or with auto-reload for development
python api/main.py --host 0.0.0.0 --port 8000 --reload
```

### Using Docker

```bash
# Build the image
docker build -f api/Dockerfile -t whispersubs-api .

# Run the container
docker run -p 8000:8000 -d whispersubs-api
```

## API Endpoints

### GET /
- **Description**: Health check and server info
- **Response**: Basic server information

### GET /models
- **Description**: Get list of available Whisper models
- **Response**: Array of model names

### POST /transcribe
- **Description**: Start a new transcription task
- **Request Body**:
  ```json
  {
    "source": "https://youtube.com/watch?v=example",
    "model_name": "large",
    "device": "cpu",
    "compute_type": "int8",
    "force": false,
    "ignore_subs": false,
    "sub_lang": null,
    "run_mpv": false,
    "force_retry": false
  }
  ```
- **Response**: Task information with ID

### GET /tasks/{task_id}
- **Description**: Get status of a specific task
- **Response**: Task status and result information

### GET /tasks
- **Description**: List all tasks
- **Response**: Array of all tasks

### GET /jobs
- **Description**: List all transcription jobs
- **Response**: Array of all jobs

### GET /health
- **Description**: Health check endpoint
- **Response**: Health status

## Example Usage

### Start a transcription:

```bash
curl -X POST http://localhost:8000/transcribe \
  -H "Content-Type: application/json" \
  -d '{
    "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "model_name": "large",
    "device": "cpu",
    "compute_type": "int8"
  }'
```

### Check task status:
```bash
curl http://localhost:8000/tasks/{task_id}
```

## Environment

The API expects the same environment as the original whisper_subs.py, including:
- FFmpeg installed
- Appropriate Python dependencies
- Access to the same directories used by the original script