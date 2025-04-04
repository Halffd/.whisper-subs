#!/bin/bash

# Name of the virtual environment
ENV_NAME="whisper_env"
PYTHON_VERSION="3.11"

# Function to handle errors
handle_error() {
    echo "Error: $1"
    exit 1
}

# Function to install packages
install_packages() {
    echo "Installing required packages..."
    
    # Install PyTorch with CUDA support
    pip install torch==2.5.1+cu121 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121 || \
    (echo "CUDA installation failed, falling back to CPU version..." && \
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu)

    # Try alternative approach - use OpenAI Whisper instead of faster-whisper
    echo "Installing OpenAI Whisper as an alternative to faster-whisper..."
    pip uninstall -y faster-whisper ctranslate2 || true
    pip install --upgrade openai-whisper || handle_error "Failed to install openai-whisper"
    
    # Install other required packages
    pip install --upgrade RealtimeSTT==0.2.3 || handle_error "Failed to install RealtimeSTT"
    pip install --upgrade pynput || handle_error "Failed to install pynput"
    
    # Install additional dependencies based on imports in speech.py
    pip install --upgrade webrtcvad || handle_error "Failed to install webrtcvad"
    pip install --upgrade flask || handle_error "Failed to install flask"
    
    # Create models directory if it doesn't exist
    MODEL_DIR="models"
    if [ ! -d "$MODEL_DIR" ]; then
        echo "Creating models directory..."
        mkdir -p "$MODEL_DIR"
    fi
    
    echo "Setup completed successfully!"
}

# Function to setup the environment
setup_environment() {
    # Check if python3-venv is installed
    if ! command -v python3 -m venv &> /dev/null; then
        echo "python3-venv not found. Installing..."
        sudo apt-get update && sudo apt-get install -y python3-venv || handle_error "Failed to install python3-venv"
    fi
    
    # Check if Python version is available
    if ! command -v python${PYTHON_VERSION} &> /dev/null; then
        # Try to find any Python 3.x version
        AVAILABLE_PYTHON=$(command -v python3.10 || command -v python3.9 || command -v python3.8 || command -v python3)
        
        if [ -n "$AVAILABLE_PYTHON" ]; then
            PYTHON_VERSION=$(basename $AVAILABLE_PYTHON | sed 's/python//')
            echo "Python ${PYTHON_VERSION} found, using it instead of 3.11"
        else
            echo "Python ${PYTHON_VERSION} not found. Please install it first."
            echo "You can use a PPA like deadsnakes on Ubuntu:"
            echo "sudo add-apt-repository ppa:deadsnakes/ppa"
            echo "sudo apt-get update"
            echo "sudo apt-get install python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev"
            exit 1
        fi
    fi
    
    # Create virtual environment if it doesn't exist
    if [ ! -d "${ENV_NAME}" ]; then
        echo "Creating new virtual environment with Python ${PYTHON_VERSION}: ${ENV_NAME}"
        python${PYTHON_VERSION} -m venv ${ENV_NAME} || handle_error "Failed to create virtual environment"
    fi
    
    # Activate virtual environment
    echo "Activating virtual environment..."
    source "${ENV_NAME}/bin/activate" || handle_error "Failed to activate virtual environment"
    
    # Install/upgrade pip
    echo "Upgrading pip..."
    python -m pip install --upgrade pip || handle_error "Failed to upgrade pip"
    
    # Install required packages
    install_packages
}

# Function to run the captioner
run_captioner() {
    # Activate virtual environment
    if [ ! -d "${ENV_NAME}" ]; then
        handle_error "Virtual environment not found. Please run with 'setup' first."
    fi
    
    echo "Activating virtual environment..."
    source "${ENV_NAME}/bin/activate" || handle_error "Failed to activate virtual environment"
    
    # Run the captioner with LD_PRELOAD to bypass executable stack issues
    echo "Running captioner..."
    python captioner.py
    
    # Store the exit status
    EXIT_STATUS=$?
    
    # Deactivate the environment
    deactivate
    
    # If there was an error running the captioner, show it
    if [ $EXIT_STATUS -ne 0 ]; then
        handle_error "Captioner exited with status $EXIT_STATUS"
    fi
}

# Main script logic
if [ $# -eq 0 ]; then
    echo "Usage: $0 [setup|run]"
    echo "  setup: Set up the environment and install dependencies"
    echo "  run: Run the captioner"
    exit 1
fi

case "$1" in
    setup)
        setup_environment
        ;;
    run)
        run_captioner
        ;;
    *)
        echo "Unknown argument: $1"
        echo "Usage: $0 [setup|run]"
        exit 1
        ;;
esac 