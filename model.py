import sys
import re

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

def getName(arg, default, captioner = False):
    global first
    if not first:
        return
    available_models = model_names

    result = {
        "model_name": default,
        "realtime_model": None,
        "lang": None
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
                        num = int(input("Model: "))
                        result["model_name"] = available_models[num]
                        result["realtime_model"] = result["model_name"]
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
