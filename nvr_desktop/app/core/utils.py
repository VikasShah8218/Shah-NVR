"""Small desktop helpers for QML (singleton `Utils`): clipboard, opening files/folders."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from app.core.toasts import ToastBus


class Utils(QObject):
    def __init__(self, toasts: ToastBus, parent=None):
        super().__init__(parent)
        self._toasts = toasts

    @Slot(str)
    @Slot(str, str)
    def copy(self, text: str, message: str = "Copied") -> None:
        QGuiApplication.clipboard().setText(text)
        self._toasts.success(message)

    @Slot(str)
    def openFolderOf(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
