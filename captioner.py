import model
import sys
args = model.getName(sys.argv, 'base', True)

import caption.speech as speech

if __name__ == "__main__":
    speech = speech.Speech(args)
    speech.start()