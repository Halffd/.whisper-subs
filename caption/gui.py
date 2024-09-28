import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QLabel, QWidget, QStyleOption, QStyle, QScrollArea, QDesktopWidget, QShortcut, QSizePolicy
from PyQt5.QtCore import Qt, QRect, QSize, QPoint, pyqtSignal, pyqtSlot, QEvent, QMetaObject
from PyQt5.QtGui import QPainter, QColor, QCursor, QKeySequence
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import textwrap

import string
import os
class CaptionerGUI(QMainWindow):
    mousePressPos = None
    mouseMovePos = None

    clearSignal = pyqtSignal()
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
        self.windowWidthOffset = 300
        self.lastGeometry = QRect(0, 0, 0, 0)
        self.top = False
        self.scrolling = False
        self.previous_value = -1
        self.max_value = -1
        self.language = 'en'
        self.speech = None
        self.log = None
        self.initUI()

    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)  # Set margins to zero
        layout.setSpacing(0)  # Set spacing to zero
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

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

        top_shortcut = QShortcut(QKeySequence(Qt.Key_Home), self)
        top_shortcut.activated.connect(self.toTop)

        bottom_shortcut = QShortcut(QKeySequence(Qt.Key_End), self)
        bottom_shortcut.activated.connect(self.toBottom)
        
        transparency_add_shortcut = QShortcut(QKeySequence(Qt.Key_0), self)
        transparency_add_shortcut.activated.connect(self.transparencyAdd)

        transparency_sub_shortcut = QShortcut(QKeySequence(Qt.Key_9), self)
        transparency_sub_shortcut.activated.connect(self.transparencySub)
        
        clear_shortcut = QShortcut(QKeySequence(Qt.Key_X), self)
        clear_shortcut.activated.connect(self.clearEmit)
        
        top_shortcut = QShortcut(QKeySequence(Qt.Key_B), self)
        top_shortcut.activated.connect(self.toggleTop)
        
        move_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        move_shortcut.activated.connect(self.move_monitor)
        
        
        # Setup fullscreen shortcut
        fullscreen_shortcut = QShortcut(QKeySequence("Return"), self)
        fullscreen_shortcut.activated.connect(self.fullscreen)
        fullwidth_shortcut = QShortcut(QKeySequence(Qt.Key_W), self)
        fullwidth_shortcut.activated.connect(self.fullwidth)
        fullheight_shortcut = QShortcut(QKeySequence(Qt.Key_H), self)
        fullheight_shortcut.activated.connect(self.fullheight)
        
        self.scroll_area.verticalScrollBar().setVisible(False)
        self.previous_value = self.scroll_area.verticalScrollBar().value()
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.new_scroll)
        QApplication.instance().installEventFilter(self)
    def fullscreen(self):
        # Get the current screen geometry
        desktop = QDesktopWidget()
        screen_geometry = desktop.screenGeometry(self.monitor - 1)
        if self.lastGeometry.width() <= 0:
            self.lastGeometry = self.geometry()
            # Set the window to cover the entire screen
            self.setGeometry(screen_geometry)
            self.showFullScreen()
        else:
            self.setGeometry(self.lastGeometry)
            self.lastGeometry = QRect(0, 0, 0, 0)
        self.write(f"Set to fullscreen with geometry: {screen_geometry}")
    def fullwidth(self):
        # Get the current screen geometry
        desktop = QDesktopWidget()
        screen_geometry = desktop.screenGeometry(self.monitor - 1)
        if self.lastGeometry.width() <= 0:
            self.lastGeometry = self.geometry()
            # Set the window to cover the entire screen
            self.setGeometry(screen_geometry.left(), self.y(), screen_geometry.width(), self.height())
        else:
            self.setGeometry(self.lastGeometry)
            self.lastGeometry = QRect(0, 0, 0, 0)
        
        # Set the window to full width and maintain its current height
        self.write(f"Set to full width: {screen_geometry.width()} at position {self.y()}")

    def fullheight(self):
        # Get the current screen geometry
        desktop = QDesktopWidget()
        screen_geometry = desktop.screenGeometry(self.monitor - 1)
        if self.lastGeometry.width() <= 0:
            self.lastGeometry = self.geometry()       
            # Set the window to full height and maintain its current width
            self.setGeometry(self.x(), screen_geometry.top(), self.width(), screen_geometry.height())
        else:
            self.setGeometry(self.lastGeometry)
            self.lastGeometry = QRect(0, 0, 0, 0)
        self.write(f"Set to full height: {screen_geometry.height()} at position {screen_geometry.top()}")
    def setup_geometry(self, fullscreen = False):
        desktop = QDesktopWidget()
        num_screens = desktop.screenCount()

        def get_screen_geometry(monitor_index, fullscreen = False):
            if monitor_index < num_screens:
                return desktop.screenGeometry(monitor_index)
            else:
                return desktop.screenGeometry(desktop.primaryScreen())

        screen_geometry = get_screen_geometry(self.monitor - 1)
        self.windowWidth = screen_geometry.width() - self.windowWidthOffset

        if fullscreen:
            windowHeight = screen_geometry.height()
            windowWidth = screen_geometry.width()
            self.setGeometry(screen_geometry.left(), screen_geometry.top(), windowWidth, windowHeight)
        else:
            if self.top:
                self.setGeometry(screen_geometry.left(), screen_geometry.top(), self.windowWidth, self.windowHeight)
            else:
                self.setGeometry(screen_geometry.left(), screen_geometry.bottom() - self.windowHeight, self.windowWidth, self.windowHeight)
    def move_monitor(self):
        pos = self.pos()
        if pos.x() < 0:
            self.monitor = 1
        else:
            self.monitor = 2
        self.setup_geometry()
        self.setup_geometry()
    def toggleTop(self):
        self.top = not self.top
        pos = self.pos()
        #print(pos.x(),'\n')
        if pos.x() < 0:
            self.monitor = 2
        else:
            self.monitor = 1
        self.setup_geometry()
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
    def toBottom(self):
        max_value = self.scroll_area.verticalScrollBar().maximum()
        current_value = self.scroll_area.verticalScrollBar().value()
        self.write('toBottom ', self.previous_value, current_value, max_value)
        self.scroll_area.verticalScrollBar().setValue(max_value)
        self.previous_value = max_value
    def toTop(self):
        """
        Scroll to the top of the text area.
        """
        self.write("toTop")
        self.scroll_area.verticalScrollBar().setValue(0)
    def end(self):
        #print(self.speech)
        self.write("End")
        self.log.close_log_file()
        if self.speech:
            self.speech.stop = True
            #print(self.speech.stop)
            self.speech.recorder.stop()
        QApplication.quit()
        """if os.name == 'nt':
            os._exit(1)
        else:
            os.kill(os.getpid(), signal.SIGINT)"""
    @pyqtSlot()
    def clearEmit(self):
        self.clearSignal.emit()
    @pyqtSlot()
    def clear(self):
        if self:
            self.lines = []
            self.caption_label.setText("")
            self.log.write_log('-- Clear --')
            #self.clearCaption()
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
        self.write("Style change ", self.fontSize, self.alpha)
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

    @pyqtSlot()
    def call_adjust_size(self):
        self.caption_label.adjustSize()
        self.max_value = self.scroll_area.verticalScrollBar().maximum()
        self.scroll_area.verticalScrollBar().setValue(self.max_value)
    
    def normalize_text(self, text):
        # Normalize the text: lower case, strip spaces, and remove punctuation
        return text.lower().strip().translate(str.maketrans('', '', string.punctuation))

    def is_similar(self, new_text, existing_lines, threshold=0.8, recent_count=7):
        # Get the most recent lines
        recent_lines = existing_lines[-recent_count:]
        vectorizer = TfidfVectorizer().fit_transform([new_text] + recent_lines)
        vectors = vectorizer.toarray()
        csim = cosine_similarity(vectors)
        return any(csim[0][i] > threshold for i in range(1, len(csim)))
    
    def addNewLine(self, text):
        if len(self.lines) > 0:
            # Normalize the incoming text
            normalized_text = self.normalize_text(text)
            # Create a list of normalized lines for similarity checking
            normalized_lines = [self.normalize_text(line) for line in self.lines]

            # Check for similarity with existing lines
            if self.is_similar(normalized_text, normalized_lines):
                return

        # Handle text length limit and specific languages
        #if len(text) > self.textLimit and self.language not in ['zh-CN', 'zh-TW', 'ja', 'th', 'my', 'lo', 'km', 'bo', 'mn', 'mn-Mong', 'dz', 'aii']:
            # Split the text into multiple lines without splitting words
        #    lines = textwrap.wrap(text, width=self.textLimit, break_long_words=False)
        #    self.lines.extend(lines)
        #else:
        self.lines.append(text)

        # Ensure the number of lines does not exceed the limit
        if self.lineLimit > 0:
            while len(self.lines) > self.lineLimit:
                del self.lines[0]

        self.caption_label.setText('\n'.join(self.lines))
        self.log.write_log(f'{text}')
        self.update_scroll_position()
    def new_scroll(self) -> None:
        current_value = self.scroll_area.verticalScrollBar().value()
        max_value = self.scroll_area.verticalScrollBar().maximum()
        if current_value == max_value:
            self.previous_value = max_value
    def update_scroll_position(self):
        self.scrolling = True
        caption_height = self.caption_label.height()
        viewport_height = self.scroll_area.viewport().height()
        # Check if the caption label height exceeds the viewport height
        
        if caption_height > viewport_height:
            # Get the current scroll bar value and the maximum value
            current_value = self.scroll_area.verticalScrollBar().value()
            max_value = self.scroll_area.verticalScrollBar().maximum()
            # If the scroll bar is already at the bottom, update the value to the maximum
            if current_value == max_value:
                QMetaObject.invokeMethod(self, "call_adjust_size", Qt.QueuedConnection)
                QApplication.processEvents()  # Process all pending events, ensuring the layout is updated
                self.previous_value = self.max_value
            else:
                # Check if the scroll position has changed
                if current_value == self.previous_value or self.previous_value < 0:
                    # Scroll to the bottom of the content
                    QMetaObject.invokeMethod(self, "call_adjust_size", Qt.QueuedConnection)
                    QApplication.processEvents()  # Process all pending events, ensuring the layout is updated
                    
                    self.previous_value = self.max_value
        self.scrolling = False
    def run(self):
        sys.exit(self.app.exec_())
    def write(self, *kwargs):
        #print(*kwargs)
        if self.log is not None and self.log.test is not None:
            self.log.write_log(' '.join(map(str, kwargs)), self.log.test)

def initialize():
    app = QApplication(sys.argv)
    gui = CaptionerGUI()
    gui.show()
    gui.clearSignal.connect(gui.clear)
    gui.app = app
    return gui