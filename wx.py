"""
Backward-compat stub - the tkinter GUI has been refactored to ui.tk_app.

This file re-exports everything so that existing callers and
`python wx.py` continue to work unchanged.
"""
from ui.tk_app import *  # noqa: F401,F403
from ui.tk_app import main
