import sys
import re

def is_numeric(input_str):
    try:
        float(input_str)
        return True
    except ValueError:
        return False

def getName(arg, default, captioner=False):
    available_models = [
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
        "whisper-medium-portuguese",
        "whisper-large-v2-japanese",
        "distil-medium.en",
        "distil-small.en",
        "distil-base",
        "distil-small",
        "distil-medium",
        "distil-large",
        "distil-large-v2",
        "distil-large-v3",
        "faster-distil-medium",
        "faster-distil-large",
        "faster-distil-large-v2",
        "faster-distil-large-v3",
        "japanese-asr/distil-whisper-large-v3-ja-reazonspeech-large"
    ]

    result = {
        "model_name": default,
        "realtime_model": None,
        "lang": None
    }

    if len(arg) > 1 and (arg[1] in ["-h", "--help"] or arg[1] == '-1'):
        main_module = sys.modules['__main__'].__file__
        print(f"Usage: python {main_module}.py [options] [model] [realtime_model] [language]")
        print("Available models:")
        for i, model in enumerate(available_models):
            print(f"- {i}: {model}")
        print("     -1: Default model")
        if captioner:
            print("     -w, --web: Web server available")
            print("     -g, --gui: User interface")
            print('     --debug: Debug mode')
            print('     --test: Test mode')
        if arg[1] == '-1':
            arg[1] = input("Choose a model: ")
        else:
            sys.exit(1)
    if captioner:
        for i in range(1, len(arg)):
            skip = i < len(arg) - 3
            j = i + 1 if skip else i
            if arg[i] == "-m" or arg[i] == "--model" or arg[i] == arg[-3]:
                if is_numeric(arg[j]):
                    num = int(arg[j])
                    if num < 0:
                        result["model_name"] = default
                    else:
                        result["model_name"] = available_models[num]
                else:
                    result["model_name"] = arg[j]
                if skip:
                    i += 1
            elif arg[i] == "--realtime-model" or arg[i] == arg[-2]:
                if is_numeric(arg[j]):
                    num = int(arg[j])
                    if num < 0:
                        result["realtime_model"] = default
                    else:
                        result["realtime_model"] = available_models[num]
                else:
                    result["realtime_model"] = arg[j]
                if skip:
                    i += 1
            elif arg[i] == "-w" or arg[i] == "--web":
                result["web_server"] = True
            elif arg[i] == "-g" or arg[i] == "--gui":
                result["gui"] = True
            elif arg[i] == "--debug":
                result["debug_mode"] = True
            elif arg[i] == "--test":
                result["test_mode"] = True
            elif arg[i] == "--lang" or arg[i] == arg[-1]:
                result["lang"] = arg[j]
                if skip:
                    i += 1
            else:
                print(f"Error: Unknown argument '{arg[i]}'. Please use --model to specify the model.")
                sys.exit(1)

        if result["model_name"] not in available_models:
            print(f"Error: {result['model_name']} is not a valid model name. Please choose from the available models.")
            sys.exit(1)
    else:
        if len(arg) <= 1:
            arg = [0, default]
        if is_numeric(arg[1]):
            num = int(arg[1])
            if num < 0:
                result = default
            else:
                result= available_models[num]
        else:
            result = arg[1]
    print(result)
    return result