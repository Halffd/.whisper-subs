#!/bin/bash
# Script to run the WhisperSubs API server

# Check if required packages are installed
python -c "import fastapi, uvicorn, pydantic" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Error: Required packages not found. Please install them:"
    echo "pip install fastapi uvicorn[standard] pydantic"
    exit 1
fi

# Set default values
HOST="${1:-0.0.0.0}"
PORT="${2:-8000}"

echo "Starting WhisperSubs API server on $HOST:$PORT"
echo "API Documentation available at: http://$HOST:$PORT/docs"

# Run the server with uvicorn
uvicorn api.server:app --host $HOST --port $PORT --reload