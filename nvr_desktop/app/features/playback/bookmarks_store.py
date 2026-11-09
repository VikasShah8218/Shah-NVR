"""BookmarksStore: bookmarks on the Playback page (port of nvr_client BookmarksPanel.tsx + the
PlaybackPage marker wiring).

Two views of the same central data (`/api/v1/bookmarks`):
* `markers` - the selected camera/profile/day's bookmarks, placed on the visible timeline window
  (app/features/playback/markers.py). Refreshed when the camera, profile or day changes.
* `rows` - the searchable panel list: this camera or all cameras, newest first, 25 per page.
Create / edit / delete refresh both. Bookmarks are shared with the web client (same central API).
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Property, QTimer, Signal, Slot

from app.core.context import AppContext
from app.core.paging import clamp_page, offset_for
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.playback.markers import bookmark_marker, place_markers
from app.features.playback.timeline import DAY

SEARCH_DEBOUNCE_MS = 300
PANEL_LIMIT = 25  # rows per panel page
DAY_LIMIT = 1000


def _utc(ms: float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


class BookmarksStore(BaseStore):
    markersChanged = Signal()
    rowsChanged = Signal()
    filterChanged = Signal()

    def __init__(self, ctx: AppContext, playback, parent=None):
        super().__init__(ctx, parent)
        self._playback = playback
        self._day_markers: list[dict] = []
        self._rows: list[dict] = []
        self._scope = "camera"  # camera | all
        self._query = ""
        self._page = 1
        self._total = 0
        self._list_key = None  # (scope, query, camera): a new key goes back to page 1
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self.refreshList)
        playback.selectionChanged.connect(self.refresh)
        playback.viewChanged.connect(self.markersChanged)  # same data, new window
        # Other operators (web or desktop) add bookmarks too: pick them up now and then.
        self._poller = Poller(self.refresh, 30, self)
        self._poller.start(immediately=False)

    # ------------------------------------------------------------------ loading
    def _camera_id(self) -> int:
        return self._playback.cameraId

    @Slot()
    def refresh(self) -> None:
        self.refreshDay()
        self.refreshList()

    @Slot()
    def refreshDay(self) -> None:
        cid, profile, day = self._camera_id(), self._playback.profile, self._playback.day
        if not cid:
            self._day_markers = []
            self.markersChanged.emit()
            return
        key = (cid, profile, day)

        def load():
            rows, _total = self.api.bookmarks(camera_id=cid, profile=profile, start=_utc(day), end=_utc(day + DAY),
                                              limit=DAY_LIMIT)
            return [bookmark_marker(b.to_qml()) for b in rows]

        def apply(markers: list[dict]):
            if key != (self._camera_id(), self._playback.profile, self._playback.day):
                self.refreshDay()  # the selection moved while loading
                return
            self._day_markers = markers
            self.markersChanged.emit()

        self.fetch("day", load, apply, track_error=False)

    @Slot()
    def refreshList(self) -> None:
        scope, query, cid = self._scope, self._query, self._camera_id()
        if scope == "camera" and not cid:
            self._rows, self._total = [], 0
            self.rowsChanged.emit()
            return
        key = (scope, query, cid)
        if key != self._list_key:
            self._list_key, self._page = key, 1
        page = self._page

        def load():
            rows, total = self.api.bookmarks(camera_id=cid if scope == "camera" else None, q=query, order="desc",
                                             limit=PANEL_LIMIT, offset=offset_for(page, PANEL_LIMIT))
            return [self._row(b.to_qml()) for b in rows], total

        def apply(result):
            if key != (self._scope, self._query, self._camera_id()) or page != self._page:
                self.refreshList()  # filter or page changed while loading
                return
            self._rows, self._total = result
            clamped = clamp_page(page, self._total, PANEL_LIMIT)
            if clamped != page:  # deleted the last row of the last page
                self._page = clamped
                self.refreshList()
            self.rowsChanged.emit()

        self.fetch("list", load, apply)

    @staticmethod
    def _row(b: dict) -> dict:
        marker = bookmark_marker(b)
        return {**b, "startMs": marker["t"], "endMs": marker["end_t"] or 0}

    @Slot(int)
    def setPage(self, page: int) -> None:
        if page >= 1 and page != self._page:
            self._page = page
            self.rowsChanged.emit()
            self.refreshList()

    page = Property(int, lambda self: self._page, notify=rowsChanged)
    total = Property(int, lambda self: self._total, notify=rowsChanged)
    pageSize = Property(int, lambda self: PANEL_LIMIT, constant=True)

    # ------------------------------------------------------------------ filters
    @Slot(str)
    def setScope(self, scope: str) -> None:
        if scope in ("camera", "all") and scope != self._scope:
            self._scope = scope
            self.filterChanged.emit()
            self.refreshList()

    @Slot(str)
    def setQuery(self, text: str) -> None:
        if text != self._query:
            self._query = text
            self.filterChanged.emit()
            self._search_timer.start()  # debounce typing

    # ------------------------------------------------------------------ actions
    @Slot(float, int, str, str, str)
    def create(self, start_ms: float, length_s: int, note: str, label: str, color: str) -> None:
        cid = self._camera_id()
        if not cid or not note.strip() or start_ms <= 0:
            self.ctx.toasts.error("Write a note and pick a valid time")
            return
        body = {
            "camera_id": cid,
            "profile": self._playback.profile or None,
            "start_time": _utc(start_ms).isoformat(),
            "end_time": _utc(start_ms + length_s * 1000).isoformat() if length_s > 0 else None,
            "note": note.strip(),
            "label": label.strip() or None,
            "color": color or None,
        }
        self.act(lambda: self.api.create_bookmark(body), "Bookmark added", lambda _b: self.refresh())

    @Slot(int, str, str, str)
    def update(self, bookmark_id: int, note: str, label: str, color: str) -> None:
        if not note.strip():
            self.ctx.toasts.error("The note cannot be empty")
            return
        body = {"note": note.strip(), "label": label.strip() or None, "color": color or None}
        self.act(lambda: self.api.update_bookmark(bookmark_id, body), "Bookmark saved", lambda _b: self.refresh())

    @Slot(int)
    def remove(self, bookmark_id: int) -> None:
        self.act(lambda: self.api.delete_bookmark(bookmark_id), "Bookmark deleted", lambda _r: self.refresh())

    # ------------------------------------------------------------------ properties
    def _placed(self) -> list[dict]:
        return place_markers(self._day_markers, self._playback.viewStart, self._playback.viewEnd)

    markers = Property("QVariantList", _placed, notify=markersChanged)
    rows = Property("QVariantList", lambda self: self._rows, notify=rowsChanged)
    scope = Property(str, lambda self: self._scope, notify=filterChanged)
    query = Property(str, lambda self: self._query, notify=filterChanged)
