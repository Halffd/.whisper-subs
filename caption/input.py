import sys
import os
import keyboard  # Import the keyboard library

class Input:
    def __init__(self, args, gui):
        self.args = args
        # Set up hotkeys
        keyboard.add_hotkey('alt+backspace', self.quit, args=(gui,))  # Quit hotkey
        keyboard.add_hotkey('ctrl+shift+backspace', self.reload)  # Reload hotkey

    def reload(self):
        os.execv(self.args[0], self.args)  # Using os.execv

    def quit(self, gui=None):
        if gui:
            gui.end()
        else:
            sys.exit()  # Exit if no GUI is provided
