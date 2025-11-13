import sys
import os
import argparse

# KMP_DUPLICATE_LIB_OK is a workaround for a common issue on macOS and Windows with Intel MKL libraries.
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

# --- Model Configuration ---
# A single, clear source of truth for all available model names.
MODEL_NAMES = [
    "tiny", "base", "small", "medium", "large", "large-v2", "large-v3",
    "tiny.en", "base.en", "small.en", "medium.en",
    "jlondonobo/whisper-medium-pt",
    "clu-ling/whisper-large-v2-japanese-5k-steps",
    "distil-whisper/distil-medium.en", "distil-whisper/distil-small.en",
    "distil-whisper/distil-base", "distil-whisper/distil-small",
    "distil-whisper/distil-medium", "distil-whisper/distil-large",
    "distil-whisper/distil-large-v2", "distil-whisper/distil-large-v3",
    "Systran/faster-distil-medium", "Systran/faster-distil-large",
    "Systran/faster-distil-large-v2", "Systran/faster-distil-large-v3",
    "japanese-asr/distil-whisper-large-v3-ja-reazonspeech-large"
]

def getIndex(model_name: str) -> int:
    """Returns the index of a given model name."""
    try:
        return MODEL_NAMES.index(model_name)
    except ValueError:
        return -1

def list_available_models():
    """Prints a formatted list of all available models with their indices."""
    print("Available models:")
    for i, model in enumerate(MODEL_NAMES):
        print(f"  {i:2d}: {model}")

# --- Argument Parsing ---

def getName(value: str):
    """
    Custom argparse type to validate and convert a model identifier (name or index)
    into a valid model name string.
    """
    try:
        if value in MODEL_NAMES:
            return value
        # Check if the value is an integer index
        model_index = int(value)
        if 0 <= model_index < len(MODEL_NAMES):
            return MODEL_NAMES[model_index]
        else:
            raise argparse.ArgumentTypeError(f"Model index {model_index} is out of range (0-{len(MODEL_NAMES)-1}).")
    except ValueError:
        # If it's not an integer, treat it as a model name
        if value in MODEL_NAMES:
            return value
        else:
            # Provide a helpful error message with close matches if possible
            import difflib
            matches = difflib.get_close_matches(value, MODEL_NAMES)
            error_msg = f"Invalid model name: '{value}'. Not found in available models."
            if matches:
                error_msg += f" Did you mean: '{', '.join(matches)}'?"
            raise argparse.ArgumentTypeError(error_msg)

def parse_arguments(description: str = "Whisper Model CLI"):
    """
    Parses command-line arguments using argparse for robust and clear configuration.
    Returns a namespace object with parsed arguments.
    """
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument(
        "model",
        nargs='?',  # Make the model argument optional
        type=getName,
        help="The primary Whisper model to use (name or index).",
        default=None # Default to None to handle multiple scenarios
    )
    parser.add_argument(
        "realtime_model",
        nargs='?',
        type=getName,
        help="[Captioner Mode] The faster, real-time model to use (name or index).",
        default=None
    )
    parser.add_argument(
        "--lang",
        type=str,
        default=None,
        help="Language code for transcription (e.g., 'en', 'ja'). Set to 'none' for auto-detection."
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all available models and their indices, then exit."
    )

    # --- Flags for Captioner Mode ---
    captioner_group = parser.add_argument_group('Captioner Mode Options')
    captioner_group.add_argument(
        "-w", "--web",
        action="store_true",
        help="Enable the web UI for the captioner."
    )
    captioner_group.add_argument(
        "-g", "--gui",
        action="store_true",
        help="Enable the GUI for the captioner."
    )
    captioner_group.add_argument(
        "--debug",
        dest="debug_mode",
        action="store_true",
        help="Enable debug mode."
    )
    captioner_group.add_argument(
        "--test",
        dest="test_mode",
        action="store_true",
        help="Enable test mode."
    )
    
    # --- Deprecated flags for backward compatibility ---
    # These will still be accepted but won't be shown in the help text.
    parser.add_argument("-m", "--model-flag", dest="model", type=getName, help=argparse.SUPPRESS)
    
    args = parser.parse_args()
    
    # If --list-models is used, print the list and exit cleanly.
    if args.list_models:
        list_available_models()
        sys.exit(0)

    # If no model is provided positionally, prompt the user.
    if args.model is None:
        list_available_models()
        try:
            selection = input("Choose a model by its index or name: ")
            args.model = getName(selection) # Validate user input
        except (EOFError, KeyboardInterrupt):
            print("\nNo model selected. Exiting.")
            sys.exit(1)
        except argparse.ArgumentTypeError as e:
            print(f"Error: {e}")
            sys.exit(1)

    # In captioner mode, if no realtime_model is specified, it defaults to the main model.
    if args.realtime_model is None:
        args.realtime_model = args.model

    # Handle 'none' as a special case for language to mean None
    if args.lang and args.lang.lower() == 'none':
        args.lang = None

    return args

if __name__ == '__main__':
    # Example of how to use the new parser
    print("--- Running Argument Parser Example ---")
    
    # To test, run from your terminal:
    # python model.py
    # python model.py 3
    # python model.py base.en
    # python model.py large-v3 --lang ja --web
    # python model.py --list-models
    
    try:
        config = parse_arguments()
        
        print("\n--- Parsed Configuration ---")
        print(f"Primary Model:  {config.model}")
        print(f"Real-time Model:{config.realtime_model}")
        print(f"Language:       {config.lang or 'Auto-Detect'}")
        print(f"Web UI:         {'Enabled' if config.web else 'Disabled'}")
        print(f"GUI:            {'Enabled' if config.gui else 'Disabled'}")
        print(f"Debug Mode:     {'Enabled' if config.debug_mode else 'Disabled'}")
        print(f"Test Mode:      {'Enabled' if config.test_mode else 'Disabled'}")
        print("--------------------------")

    except SystemExit as e:
        if e.code != 0:
            print(f"\nExited with code {e.code}. Likely due to --help, --list-models, or an error.")