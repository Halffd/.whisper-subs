FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create working directory
WORKDIR /app

# Copy necessary files
COPY transcribe.py .
COPY youtubesubs.py .

# Create volume mount points
VOLUME ["/data/input", "/data/output"]

# Run the transcription service
CMD ["python", "transcription_service.py"]
