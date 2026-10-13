"""Poller: call a refresh function every N seconds (the desktop equivalent of TanStack Query polling)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer


class Poller(QObject):
    def __init__(self, refresh: Callable[[], None], seconds: float, parent: QObject | None = None):
        super().__init__(parent)
        self._refresh = refresh
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self.set_interval(seconds)

    def set_interval(self, seconds: float) -> None:
        self._timer.setInterval(max(500, int(seconds * 1000)))

    def start(self, immediately: bool = True) -> None:
        if immediately:
            self._refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def active(self) -> bool:
        return self._timer.isActive()
