import sys
import os
from pynput import keyboard

class Input:
    def __init__(self, args):
        self.args = args
        self.gui = None #gui.CaptionerGUI()  # Initialize GUI as None
        # Set up hotkeys
        self.listener = keyboard.GlobalHotKeys({
            '<alt>+<backspace>': self.quit,
            '<ctrl>+<shift>+<backspace>': self.reload,
            '<ctrl>+<up>': self.increase_font_size,
            '<ctrl>+<down>': self.decrease_font_size,
            '<ctrl>+<alt>+x': self.clear_text,
            '<ctrl>+<shift>+<left>': self.move_monitor,
            '<ctrl>+<shift>+<down>': self.toggle_top,
            '<ctrl>+<page_up>': self.increase_transparency,
            '<ctrl>+<page_down>': self.decrease_transparency
        })
        self.listener.start()

    def reload(self):
        """Reload the application."""
        os.execv(sys.executable, ['py'] + self.args)

    def quit(self):
        """Quit the application."""
        if self.gui:
            self.gui.end()
        else:
            sys.exit()  # Exit if no GUI is provided

    def increase_font_size(self):
        """Increase the font size."""
        self.gui.zoomIn()
    def decrease_font_size(self):
        """Decrease the font size."""
        self.gui.zoomOut()

    def clear_text(self):
        """Clear the text."""
        self.gui.clear()

    def move_monitor(self):
        self.gui.move_monitor()

    def toggle_top(self):
        self.gui.toggleTop()

    def increase_transparency(self):
        """Increase transparency."""
        self.gui.transparencyAdd()
    def decrease_transparency(self):
        """Decrease transparency."""
        self.gui.transparencySub()
# Example usage
if __name__ == "__main__":
    input_handler = Input(sys.argv)