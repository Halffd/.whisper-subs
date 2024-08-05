import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QLabel, QWidget, QStyleOption, QStyle, QScrollArea
from PyQt5.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal, QEvent
from PyQt5.QtGui import QPainter, QColor, QCursor

class CaptionerGUI(QMainWindow):
    mousePressPos = None
    mouseMovePos = None

    def __init__(self):
        super().__init__()
        self.initUI()
        self.lines = []
        self.fontSize = 55
        self.alpha = 128

    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.caption_label = QLabel("Caption goes here")
        self.caption_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.caption_label.setWordWrap(True)
        self.caption_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.caption_label.setCursor(Qt.IBeamCursor)

        self.scroll_area.setWidget(self.caption_label)
        layout.addWidget(self.scroll_area)

        self.styling()
        self.setCentralWidget(central_widget)
        self.setGeometry(100, 100, 800, 150)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mousePressPos = event.globalPos() - self.pos()
            self.mouseMovePos = event.globalPos() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        self.move(event.globalPos() - self.mouseMovePos)
        self.mouseMovePos = event.globalPos() - self.pos()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mousePressPos = None
            self.mouseMovePos = None
            event.accept()

    def styling(self):
        self.caption_label.setStyleSheet(f"font-size: {self.fontSize}px; color: white; background-color: rgba(0, 0, 0, {self.alpha}); selection-background-color: rgba(255, 255, 255, 128);")

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

        # Scroll to the bottom if the text exceeds the height of the label
        if self.caption_label.height() > self.scroll_area.height():
            self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def run(self):
        sys.exit(self.app.exec_())

def draw():
    app = QApplication(sys.argv)
    gui = CaptionerGUI()
    gui.show()
    gui.app = app
    return gui