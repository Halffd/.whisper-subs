import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QLabel, QWidget, QStyleOption, QStyle
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QPainter, QColor

class CaptionerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.lines = []

    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        self.caption_label = QLabel("Caption goes here")
        self.caption_label.setAlignment(Qt.AlignCenter)
        self.caption_label.setStyleSheet("font-size: 45px; color: white; background-color: rgba(0, 0, 0, 128);")

        layout.addWidget(self.caption_label)
        self.setCentralWidget(central_widget)

        self.setGeometry(100, 100, 800, 150)

    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, painter, self)

    def editCaption(self, new_caption):
        self.caption_label.setText(new_caption)

    def clearCaption(self):
        self.caption_label.clear()
    def addNewLine(self, text):
        if len(text) > 50:
            # Split the text into multiple lines
            lines = [text[i:i+50] for i in range(0, len(text), 50)]
            self.lines.extend(lines)
        else:
            self.lines.append(text)

        # Remove the oldest lines if there are more than 4
        while len(self.lines) > 4:
            del self.lines[0]

        self.caption_label.setText('\n'.join(self.lines))
    def run(self):
        sys.exit(self.app.exec_())
def draw():
    app = QApplication(sys.argv)
    gui = CaptionerGUI()
    gui.show()
    gui.app = app
    
    return gui