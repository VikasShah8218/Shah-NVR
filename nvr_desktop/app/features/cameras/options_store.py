"""CameraOptionsStore: a searchable camera list for pickers and the Live sidebar, loaded 50 at a time
("Load more"), with small rows from GET /api/v1/cameras/options (id, name, status, profiles...).
Port of the web `useCameraOptions` hook. One instance per page (own search text): LiveCameras, PlaybackCameras,
EncoderCameras.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from app.core.context import AppContext
from app.core.list_model import DictListModel
from app.core.poller import Poller
from app.core.store import BaseStore

OPTION_ROLES = ["id", "name", "enabled", "has_ptz", "profiles", "status", "node_id", "group_id", "group_path"]
PAGE = 50
MAX_RELOAD = 200  # a poll reloads what is shown, up to this many rows
SEARCH_DEBOUNCE_MS = 300


class CameraOptionsStore(BaseStore):
    changed = Signal()
    searchChanged = Signal()

    def __init__(self, ctx: AppContext, poll: bool = True, parent=None):
        super().__init__(ctx, parent)
        self.model = DictListModel(OPTION_ROLES, parent=self)
        self._rows: list[dict] = []
        self._total = 0
        self._search = ""
        self._query = ""
        self._seq = 0
        self._loading_more = False
        self._debounce = QTimer(self, singleShot=True, interval=SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._apply_search)
        ctx.centralChanged.connect(self.refresh)
        self._poller = Poller(self.refresh, ctx.prefs.pollSeconds, self) if poll else None
        if self._poller:
            ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
            self._poller.start()
        else:
            self.refresh()

    # ------------------------------------------------------------------ loading
    def _request(self, limit: int, offset: int):
        rows, total = self.api.camera_options(q=self._query, limit=limit, offset=offset)
        return [r.to_qml() for r in rows], total

    @Slot()
    def refresh(self) -> None:
        """Reload from the top, keeping as many rows as are shown (so "Load more" survives a poll)."""
        self._seq += 1
        seq, limit = self._seq, min(MAX_RELOAD, max(PAGE, len(self._rows)))

        def ok(result):
            if seq == self._seq:
                self._set(*result)

        self.fetch(f"options-{seq}", lambda: self._request(limit, 0), ok)

    @Slot()
    def loadMore(self) -> None:
        if self._loading_more or len(self._rows) >= self._total:
            return
        self._loading_more = True
        self.changed.emit()
        seq, offset = self._seq, len(self._rows)

        def ok(result):
            self._loading_more = False
            if seq == self._seq:
                rows, total = result
                known = {r["id"] for r in self._rows}
                self._set(self._rows + [r for r in rows if r["id"] not in known], total)
            else:
                self.changed.emit()

        def err(_exc):
            self._loading_more = False
            self.changed.emit()

        self.fetch(f"options-more-{seq}-{offset}", lambda: self._request(PAGE, offset), ok, on_err=err)

    def _set(self, rows: list[dict], total: int) -> None:
        self._rows, self._total = rows, total
        self.model.set_items(rows)
        self.changed.emit()

    # ------------------------------------------------------------------ search
    @Slot(str)
    def setSearch(self, text: str) -> None:
        if text != self._search:
            self._search = text
            self.searchChanged.emit()
            self._debounce.start()

    def _apply_search(self) -> None:
        query = self._search.strip()
        if query != self._query:
            self._query = query
            self._rows = []
            self.refresh()

    @Slot(int, result="QVariant")
    def byId(self, camera_id: int):
        return next((r for r in self._rows if r["id"] == camera_id), None)

    rows = Property("QVariantList", lambda self: self._rows, notify=changed)
    total = Property(int, lambda self: self._total, notify=changed)
    hasMore = Property(bool, lambda self: len(self._rows) < self._total, notify=changed)
    loadingMore = Property(bool, lambda self: self._loading_more, notify=changed)
    moreLabel = Property(str, lambda self: f"Load more ({len(self._rows)} of {self._total})", notify=changed)
    search = Property(str, lambda self: self._search, notify=searchChanged)
    query = Property(str, lambda self: self._query, notify=searchChanged)
    listModel = Property(QObject, lambda self: self.model, constant=True)


# One QML singleton per page, each with its own search text (distinct types keep the QML registration simple).
class LiveCamerasStore(CameraOptionsStore):
    """Live View sidebar."""


class PlaybackCamerasStore(CameraOptionsStore):
    """Playback camera picker."""


class EncoderCamerasStore(CameraOptionsStore):
    """Bulk encoder target list (Video tab). No polling: it is a pick list."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, poll=False, parent=parent)
