import model
import sys
import caption.speech as speech

if __name__ == "__main__":
    args = model.getName(sys.argv, 'base', True)
    
    caption = speech.Speech(args)
    caption.start()