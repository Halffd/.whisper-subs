import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QLabel, QWidget, QStyleOption, QStyle, QScrollArea, QDesktopWidget, QShortcut
from PyQt5.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal, QEvent
from PyQt5.QtGui import QPainter, QColor, QCursor, QKeySequence
import textwrap
import os

class CaptionerGUI(QMainWindow):
    mousePressPos = None
    mouseMovePos = None

    def __init__(self):
        super().__init__()
        self.lines = []
        self.fontSize = 55
        self.alpha = 128
        self.lineLimit = 0
        self.textLimit = 50
        self.zoomFactor = 2
        self.transparencyFactor = 3
        self.monitor = 2
        self.windowHeight = 300 if self.monitor == 1 else 210
        self.windowWidthOffset = 5
        self.top = False
        self.language = 'en'
        self.speech = None
        self.initUI()

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

        self.setWindowTitle("Captioner")
        
        self.setup_geometry()
        # Create shortcuts for the global hotkeys
        end_shortcut = QShortcut(QKeySequence(Qt.CTRL + Qt.Key_Q), self)
        end_shortcut.activated.connect(self.end)

        self.esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.esc_shortcut.activated.connect(self.end)
        
        zoom_in_shortcut = QShortcut(QKeySequence(Qt.Key_Equal), self)
        zoom_in_shortcut.activated.connect(self.zoomIn)

        zoom_out_shortcut = QShortcut(QKeySequence(Qt.Key_Minus), self)
        zoom_out_shortcut.activated.connect(self.zoomOut)

        transparency_add_shortcut = QShortcut(QKeySequence(Qt.Key_0), self)
        transparency_add_shortcut.activated.connect(self.transparencyAdd)

        transparency_sub_shortcut = QShortcut(QKeySequence(Qt.Key_9), self)
        transparency_sub_shortcut.activated.connect(self.transparencySub)

        clear_shortcut = QShortcut(QKeySequence(Qt.Key_X), self)
        clear_shortcut.activated.connect(self.clear)
        QApplication.instance().installEventFilter(self)
    
    def setup_geometry(self):
        desktop = QDesktopWidget()
        num_screens = desktop.screenCount()

        def get_screen_geometry(monitor_index):
            if monitor_index < num_screens:
                return desktop.screenGeometry(monitor_index)
            else:
                return desktop.screenGeometry(desktop.primaryScreen())

        screen_geometry = get_screen_geometry(self.monitor - 1)
        self.windowWidth = screen_geometry.width() - self.windowWidthOffset

        if self.top:
            self.setGeometry(screen_geometry.left(), screen_geometry.top(), self.windowWidth, self.windowHeight)
        else:
            self.setGeometry(screen_geometry.left(), screen_geometry.bottom() - self.windowHeight, self.windowWidth, self.windowHeight)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key_sequence = QKeySequence(event.modifiers() | event.key())
            if key_sequence == QKeySequence(Qt.CTRL | Qt.ALT | Qt.Key_Minus):
                self.zoomOut()
            elif key_sequence == QKeySequence(Qt.CTRL | Qt.ALT | Qt.Key_Equal):
                self.zoomIn()
            elif key_sequence == QKeySequence(Qt.CTRL | Qt.ALT | Qt.Key_X):
                self.clear()
            elif key_sequence == QKeySequence(Qt.CTRL | Qt.ALT | Qt.Key_Q):
                self.end()
        return super().eventFilter(obj, event)
    def zoom(self, factor):
        if not self or factor == 0 or self.fontSize + factor <= 0:
            return
        self.fontSize += factor
        self.styling()
    def zoomIn(self):
        self.zoom(self.zoomFactor)
    def zoomOut(self):
        self.zoom(-self.zoomFactor)
    def transparency(self, factor):
        if factor == 0 or self.alpha + factor <= 0 or self.alpha + factor > 255:
            return
        self.alpha += factor
        self.styling()
    def transparencyAdd(self):
        self.transparency(self.transparencyFactor)
    def transparencySub(self):
        self.transparency(-self.transparencyFactor)
    def end(self):
        print(self.speech)
        if self.speech:
            self.speech.stop = True
            print(self.speech.stop)
            self.speech.recorder.stop()
        QApplication.quit()
        """if os.name == 'nt':
            os._exit(1)
        else:
            os.kill(os.getpid(), signal.SIGINT)"""
    def clear(self):
        if self:
            self.lines = []
            self.clearCaption()
    # Show the scrollbar when the content is larger than the viewport
    def scrollbar_visibility(self):
        if self.scroll_area.verticalScrollBar().isVisible():
            self.scroll_area.verticalScrollBar().setVisible(True)
        else:
            self.scroll_area.verticalScrollBar().setVisible(False)

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
        self.scroll_area.setStyleSheet(f"font-size: {self.fontSize}px; color: white; background-color: rgba(0, 0, 0, {self.alpha});")
        self.caption_label.setStyleSheet(f"background-color: rgba(0, 0, 0, {self.alpha});")

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
        if len(text) > self.textLimit and self.language not in ['zh-CN', 'zh-TW', 'ja', 'th', 'my', 'lo', 'km', 'bo', 'mn', 'mn-Mong', 'dz', 'aii']:
            # Split the text into multiple lines without splitting words
            lines = textwrap.wrap(text, width=self.textLimit, break_long_words=False)
            self.lines.extend(lines)
        else:
            self.lines.append(text)

        if self.lineLimit > 0:
            # Remove the oldest lines if there are more than the limit
            while len(self.lines) > self.lineLimit:
                del self.lines[0]

        self.caption_label.setText('\n'.join(self.lines))

        # Scroll to the bottom if the text exceeds the height of the label and the user has not scrolled up
        self.update_scroll_position()
    def update_scroll_position(self):
        # Get the height of the caption label and the scroll area viewport
        caption_height = self.caption_label.height()
        viewport_height = self.scroll_area.viewport().height()

        # Check if the caption label height exceeds the viewport height
        if caption_height > viewport_height:
            # Get the current scroll bar value and the maximum value
            current_value = self.scroll_area.verticalScrollBar().value()
            max_value = self.scroll_area.verticalScrollBar().maximum()

            # If the scroll bar is already at the bottom, update the value to the maximum
            if current_value == max_value:
                self.scroll_area.verticalScrollBar().setValue(max_value)
            else:
                # Scroll to the bottom of the content
                self.scroll_area.verticalScrollBar().setValue(caption_height - viewport_height)

    def run(self):
        sys.exit(self.app.exec_())

def initialize():
    app = QApplication(sys.argv)
    gui = CaptionerGUI()
    gui.show()
    gui.app = app
    return gui