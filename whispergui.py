"""
Backward-compat stub - the GTK4 GUI has been refactored to ui.gtk_app.

This file re-exports everything so that existing callers and
`python whispergui.py` continue to work unchanged.
"""
from ui.gtk_app import *  # noqa: F401,F403
from ui.gtk_app import main
