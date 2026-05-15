"""
Backward-compat stub - the PyQt6 GUI has been refactored to ui.pyqt_app.

This file re-exports everything so that existing callers and
`python fastwhisper.py` continue to work unchanged.
"""
from ui.pyqt_app import *  # noqa: F401,F403
from ui.pyqt_app import main
