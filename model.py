import sys
import re

import os
os.environ["KMP_DUPLICATE_LIB_OK"]="TRUE"

first = True
model_names = [
        "tiny",
        "base",
        "small",
        "medium",
        "large",
        "large-v2",
        "large-v3",
        "tiny.en",
        "base.en",
        "small.en",
        "medium.en",
        "jlondonobo/whisper-medium-pt",
        "clu-ling/whisper-large-v2-japanese-5k-steps",
        "distil-whisper/distil-medium.en",
        "distil-whisper/distil-small.en",
        "distil-whisper/distil-base",
        "distil-whisper/distil-small",
        "distil-whisper/distil-medium",
        "distil-whisper/distil-large",
        "distil-whisper/distil-large-v2",
        "distil-whisper/distil-large-v3",
        "Systran/faster-distil-medium",
        "Systran/faster-distil-large",
        "Systran/faster-distil-large-v2",
        "Systran/faster-distil-large-v3",
        "japanese-asr/distil-whisper-large-v3-ja-reazonspeech-large"
    ]
def __getattr__(name):
    global model_names
    if name == "model_names":
        return model_names
    else:
        return None #super().__getattr__(name)
def is_numeric(input_str):
    try:
        float(input_str)
        return True
    except ValueError:
        return False
def getIndex(model_name):
    global model_names
    return model_names.index(model_name)
def getName(arg, default, captioner = False):
    global first
    if not first:
        return
    available_models = model_names
    # Use a platform-independent way to extract directory path
    path = os.path.dirname(arg[0]) if len(arg[0]) > 12 else os.getcwd()
    
    # Initialize result dictionary with defaults
    result = {
        "model_name": default,
        "realtime_model": None,
        "lang": None,
        "path": path,
        "gui": False,
        "web": False,
        "debug_mode": False,
        "test_mode": False
    }
    
    if len(arg) > 1 and (arg[1] in ["-h", "--help"] or "-1" in arg):
        main_module = os.path.basename(sys.modules['__main__'].__file__)
        print(f"Usage: python {main_module} [options] [model] [realtime_model] [language]")
        print("     -1: Default model")
        if captioner:
            print("     -w, --web: Web server available")
            print("     -g, --gui: User interface")
            print('     --debug: Debug mode')
            print('     --test: Test mode')
        if "-1" in arg:
            print("Available models:")
            for i, model in enumerate(available_models):
                print(f"- {i}: {model}")
            if arg[1] == '-1':
                try:
                    arg[1] = input("Choose a model: ")
                except EOFError:
                    sys.exit(0)
            elif '-h' in arg[1]:
                sys.exit(0)
    
    if captioner:
        i = 1
        while i < len(arg):
            if arg[i] == "-m" or arg[i] == "--model":
                if i + 1 < len(arg):
                    if is_numeric(arg[i+1]):
                        num = int(arg[i+1])
                        if num < 0:
                            try:
                                num = input("Model: ")
                                nums = num.split(' ')
                                num2 = None
                                if len(nums) > 1:
                                    num = int(nums[0])
                                    num2 = int(nums[1])
                                else:
                                    num = int(num)
                                result["model_name"] = available_models[num]
                                result["realtime_model"] = result["model_name"] if not num2 else available_models[num2]
                            except (ValueError, IndexError, EOFError):
                                print("Invalid model number. Using default.")
                        else:
                            try:
                                result["model_name"] = available_models[num]
                            except IndexError:
                                print(f"Invalid model index {num}. Using default.")
                    else:
                        result["model_name"] = arg[i+1]
                    i += 2
                else:
                    i += 1
            elif arg[i] == "--realtime-model":
                if i + 1 < len(arg):
                    if is_numeric(arg[i+1]):
                        num = int(arg[i+1])
                        if num < 0:
                            result["realtime_model"] = default
                        else:
                            try:
                                result["realtime_model"] = available_models[num]
                            except IndexError:
                                print(f"Invalid realtime model index {num}. Using default.")
                    else:
                        result["realtime_model"] = arg[i+1]
                    i += 2
                else:
                    i += 1
            elif arg[i] == "-w" or arg[i] == "--web":
                result["web"] = True
                i += 1
            elif arg[i] == "-g" or arg[i] == "--gui":
                result["gui"] = True
                i += 1
            elif arg[i] == "--debug":
                result["debug_mode"] = True
                i += 1
            elif arg[i] == "--test":
                result["test_mode"] = True
                i += 1
            elif arg[i] == "--lang":
                if i + 1 < len(arg):
                    if arg[i+1] == "-1":
                        try:
                            arg[i+1] = input("Language: ")
                        except EOFError:
                            arg[i+1] = None
                    result["lang"] = arg[i+1] if arg[i+1] != 'none' else None
                    i += 2
                else:
                    i += 1
            else:
                # Positional arguments handling
                if result["model_name"] == default:
                    # First unrecognized argument is the model
                    if is_numeric(arg[i]):
                        num = int(arg[i])
                        if num >= 0 and num < len(available_models):
                            result["model_name"] = available_models[num]
                    else:
                        result["model_name"] = arg[i]
                elif result["realtime_model"] is None:
                    # Second unrecognized argument is the realtime model
                    if is_numeric(arg[i]):
                        num = int(arg[i])
                        if num >= 0 and num < len(available_models):
                            result["realtime_model"] = available_models[num]
                    else:
                        result["realtime_model"] = arg[i]
                elif result["lang"] is None:
                    # Third unrecognized argument is the language
                    result["lang"] = arg[i] if arg[i] != 'none' else None
                else:
                    print(f"Warning: Ignoring unknown argument '{arg[i]}'")
                i += 1

        # Validate model name
        if result["model_name"] not in available_models:
            print(f"Warning: {result['model_name']} is not a recognized model name.")

    else:
        # For non-captioner usage
        if len(arg) <= 1:
            return default
        
        name = arg[1]
        args = name.split(' ')
        if len(args) > 1:
            name = args[0]
        
        if is_numeric(name):
            num = int(name)
            if num < 0:
                result = default
            else:
                try:
                    result = available_models[num]
                except IndexError:
                    print(f"Invalid model index {num}. Using default.")
                    result = default
        else:
            result = arg[1]
        
        if len(args) > 1:
            result = {
                "model_name": result,
                "lang": args[1]
            }
    
    print(result)
    first = False
    return result
