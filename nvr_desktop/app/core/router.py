"""Router: which page is shown (QML singleton `Router`). The desktop equivalent of React Router.

Pages: dashboard, live, playback, cameras, camera (id), discover, nodes, node (id), assignments, settings.
`go(page, id)` navigates; `back()` returns to the previous page; `params` holds extra values
(e.g. Playback opened from a camera at a given time).
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

PAGES = ("dashboard", "live", "playback", "cameras", "camera", "discover", "nodes", "node", "assignments", "settings")


class Router(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page = "dashboard"
        self._id = 0
        self._params: dict = {}
        self._history: list[tuple[str, int, dict]] = []

    @Slot(str)
    @Slot(str, int)
    @Slot(str, int, "QVariant")
    def go(self, page: str, item_id: int = 0, params=None) -> None:
        if page not in PAGES:
            raise ValueError(f"unknown page {page!r}")
        self._history.append((self._page, self._id, self._params))
        del self._history[:-50]
        self._page, self._id, self._params = page, item_id, dict(params or {})
        self.changed.emit()

    @Slot()
    def back(self) -> None:
        if self._history:
            self._page, self._id, self._params = self._history.pop()
            self.changed.emit()

    page = Property(str, lambda self: self._page, notify=changed)
    id = Property(int, lambda self: self._id, notify=changed)
    params = Property("QVariant", lambda self: self._params, notify=changed)
