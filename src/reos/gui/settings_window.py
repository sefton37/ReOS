"""Settings window.

UX principle:
- Opened from left navigation.
- Separate window (chat stays centered in main window).

Contains:
- Ollama settings (server URL, test connection, select model, save)
- Agent personas (view/edit system prompt + default context, tune knobs, save/select)
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMainWindow

from ..db import Database
from .settings_widget import SettingsWidget


class SettingsWindow(QMainWindow):
    """Standalone window for managing Settings."""

    def __init__(self, *, db: Database) -> None:
        super().__init__()
        self._db = db
        self.setWindowTitle("ReOS - Settings")
        self.resize(QSize(1100, 800))

        self._widget = SettingsWidget(db=self._db)
        self.setCentralWidget(self._widget)

    def refresh(self) -> None:
        self._widget.refresh()
