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
    pattern = r"^(.*?)\\[^\\]*\.py$"
    path = arg[0] if len(arg[0]) > 12 else os.getcwd()
    match = re.match(pattern, path)

    if match:
        path = match.group(1)  # Get the captured group

    print(path)
    result = {
        "model_name": default,
        "realtime_model": None,
        "lang": None,
        "path": path,
    }
    if len(arg) > 1 and (arg[1] in ["-h", "--help"] or "-1" in arg):
        main_module = sys.modules['__main__'].__file__
        print(f"Usage: python {main_module}.py [options] [model] [realtime_model] [language]")
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
                arg[1] = input("Choose a model: ")
            elif '-h' in arg[1]:
                sys.exit(1)
    if captioner:
        result["lang"] = None
        for i in range(1, len(arg)):
            rem = len(arg) - i
            skip = i < len(arg) - 3
            j = i + 1 if skip else i
            #print(i, '/',len(arg), arg[i], j, arg[j], rem)
            if arg[i] == "-m" or arg[i] == "--model" or rem == 3:
                if is_numeric(arg[j]):
                    num = int(arg[j])
                    if num < 0:
                        num = str(input("Model: "))
                        nums = num.split(' ')
                        num2 = None
                        if len(nums) > 1:
                            num = int(nums[0])
                            num2 = int(nums[1])
                        else:
                            num = int(num)
                        result["model_name"] = available_models[num]
                        result["realtime_model"] = result["model_name"] if not num2 else num2
                    else:
                        result["model_name"] = available_models[num]
                else:
                    result["model_name"] = arg[j]
                if skip:
                    i += 1
            elif arg[i] == "--realtime-model" or rem == 2:
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
                result["web"] = True
            elif arg[i] == "-g" or arg[i] == "--gui":
                result["gui"] = True
            elif arg[i] == "--debug":
                result["debug_mode"] = True
            elif arg[i] == "--test":
                result["test_mode"] = True
            elif arg[i] == "--lang" or rem == 1:
                if arg[j] == "-1":
                    arg[j] = input("Language: ")
                result["lang"] = arg[j] if arg[j] != 'none' else None
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
                result= available_models[num]
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
