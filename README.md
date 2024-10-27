```markdown
# .whisper-subs

Welcome to the .whisper-subs project! This repository contains various scripts and tools for transcribing YouTube videos, MKV files, and more. With a focus on flexibility and usability, .whisper-subs aims to provide a comprehensive solution for audio and video transcription.

## Features

- **YouTube Transcription**: Easily transcribe videos from YouTube URLs or entire channels using `yt-dlp`.
- **MKV File Selector**: Select and transcribe MKV files with a variety of models.
- **Live Captioner**: A real-time captioning tool built with PyQt for easy viewing of transcriptions.
- **Transcription Logs**: Maintain a detailed log of each transcription performed.
- **Web Server Option**: Access transcription services through a web interface.
- **AI Tools**: Ongoing development in the AI folder, including OCR transformers, LORA testing, and Torch tests.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/.whisper-subs.git
   ```
2. Navigate to the project directory:
   ```bash
   cd .whisper-subs
   ```
3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Transcribing YouTube URLs or Channels

To transcribe a YouTube video or channel, run:
```bash
python youtube-subs.py <model name>
```
Video URL is got from clipboard

### MKV File Selection

To transcribe an MKV file, use:
```bash
python fasterwhisper.py
```

### Live Captioner

To start the live captioning interface, execute:
```bash
python captioner.py
```

### Viewing Transcription Logs

Logs are saved in the `logs/` directory for your reference.

## Development

The `ai` folder contains ongoing development work for various AI-related functionalities, including:

- OCR transformers
- LORA tests
- Torch tests

Feel free to contribute to these modules as they evolve!

---

For any issues or feature requests, please open an issue in the GitHub repository.
```

You can modify the section headers or any other part of the README as needed!
