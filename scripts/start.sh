#!/bin/bash

# Create data directory if it doesn't exist
mkdir -p data

# Start the container
docker run --gpus all -it \
    --name whisper-subs \
    -v $(pwd)/data:/app/data \
    whisper-subs 