"""EventsStore: event marks on the Playback timeline, the Events panel / page, and "Mark event"
(port of nvr_client features/events + the PlaybackPage marker wiring; docs/DESKTOP_EVENT_RECORDING_PLAN.md).

QML singleton `Events`. Two views of central's `/api/v1/events` (read = PLAYBACK per camera):
* `markers`: the playback camera's events of the selected day, placed on the visible timeline window
  (app/features/playback/markers.py). A click plays from the camera's pre-event seconds.
* `rows`: the list (this camera or all cameras, one type or all), newest first, 25 per page.
Both refresh every 15 s while Playback or the Events page is open (an ongoing event grows; nodes add video loss).
Actions: mark (perm 4), end (perm 4), save as bookmark (perm 4), delete (perm 20); each refreshes both views.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from PySide6.QtCore import Property, QTimer, Signal, Slot

from app.core.auth.permissions import Perm
from app.core.context import AppContext
from app.core.paging import clamp_page, offset_for
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.playback.markers import (EVENT_TYPE_GROUPS, event_color, event_marker, event_text,
                                           event_type_label, place_markers)
from app.features.playback.timeline import DAY

PANEL_LIMIT = 25
DAY_LIMIT = 1000
POLL_SECONDS = 15


def _utc(ms: float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


def duration_text(e: dict) -> str:
    """'ongoing', '12 s', '3 min 5 s', '1.5 h'; '' for a moment."""
    if not e.get("end_time"):
        return "ongoing"
    s = round((_ms(e["end_time"]) - _ms(e["start_time"])) / 1000)
    if s <= 0:
        return ""
    return f"{s} s" if s < 60 else f"{s // 60} min {s % 60} s" if s < 3600 else f"{s / 3600:.1f} h"


def _ms(value) -> float:
    if isinstance(value, datetime):
        return value.timestamp() * 1000
    from app.features.playback.timeline import to_ms
    return to_ms(value)


def event_details(e: dict) -> str:
    """What the label does not show (analytics direction). Camera text: shown as plain text only."""
    d = e.get("data") or {}
    return f"Direction: {str(d['direction'])[:64]}" if isinstance(d, dict) and isinstance(d.get("direction"), str) else ""


def type_options() -> list[dict]:
    """The type filter: all, then per group "All <group>" and its types (value "group:<name>" or a type)."""
    out = [{"value": "", "label": "All types"}]
    for group, title, types in EVENT_TYPE_GROUPS:
        out.append({"value": f"group:{group}", "label": f"All {title.lower()}"})
        out += [{"value": t, "label": "    " + event_type_label(t)} for t in types]
    return out


def filter_params(value: str) -> dict:
    """Filter value -> events() keywords."""
    if value.startswith("group:"):
        return {"group": value[6:]}
    return {"types": [value]} if value else {}


def event_row(e: dict, now_ms: float | None = None) -> dict:
    m = event_marker(e, now_ms if now_ms is not None else time.time() * 1000)
    return {**e, "startMs": m["t"], "seekMs": m["seek_t"], "color": m["color"], "typeLabel": event_type_label(e["type"]),
            "title": event_text(e), "details": event_details(e),
            "duration": duration_text(e), "ongoing": not e.get("end_time")}


def bookmark_body(e: dict) -> dict:
    """"Save as bookmark": the event's time and a note from its type and label (same as the web)."""
    start, end = e["start_time"], e.get("end_time")
    return {"camera_id": e["camera_id"], "start_time": start, "end_time": end if end and end != start else None,
            "note": event_text(e)[:500],
            "label": "event", "color": event_color(e["type"])}


class EventsStore(BaseStore):
    markersChanged = Signal()
    rowsChanged = Signal()
    filterChanged = Signal()

    def __init__(self, ctx: AppContext, playback, bookmarks=None, parent=None):
        super().__init__(ctx, parent)
        self._playback = playback
        self._bookmarks = bookmarks  # refreshed after "save as bookmark"
        self._day_events: list[dict] = []
        self._rows: list[dict] = []
        self._scope = "camera"  # camera | all
        self._type = ""
        self._search = ""
        self._query = ""  # the search, debounced
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_search)
        self._page = 1
        self._total = 0
        self._list_key = None
        self._active = 0  # pages open that show events (Playback, Events)
        playback.selectionChanged.connect(self.refresh)
        playback.viewChanged.connect(self.markersChanged)  # same data, new window
        self._poller = Poller(self.refresh, POLL_SECONDS, self)

    def _may_read(self) -> bool:
        return self.allowed(Perm.PLAYBACK)

    def _camera_id(self) -> int:
        return self._playback.cameraId

    # ------------------------------------------------------------------ activity
    @Slot(bool)
    def setActive(self, active: bool) -> None:
        """Playback and the Events page call this on open / close: poll only while one is open."""
        self._active = max(0, self._active + (1 if active else -1))
        if self._active and not self._poller.active:
            self._poller.start()
        elif not self._active:
            self._poller.stop()

    # ------------------------------------------------------------------ loading
    @Slot()
    def refresh(self) -> None:
        self.refreshDay()
        self.refreshList()

    @Slot()
    def refreshDay(self) -> None:
        cid, day = self._camera_id(), self._playback.day
        if not cid or not self._may_read():
            if self._day_events:
                self._day_events = []
                self.markersChanged.emit()
            return
        key = (cid, day)

        def load():
            rows, _total = self.api.events(camera_id=cid, start=_utc(day), end=_utc(day + DAY), order="asc",
                                           limit=DAY_LIMIT)
            return [e.to_qml() for e in rows]

        def apply(events: list[dict]):
            if key != (self._camera_id(), self._playback.day):
                self.refreshDay()  # the selection moved while loading
                return
            self._day_events = events
            self.markersChanged.emit()

        self.fetch("day", load, apply, track_error=False)

    @Slot()
    def refreshList(self) -> None:
        if not self._may_read():
            self._set_loading(False)
            return
        scope, type_, cid, query = self._scope, self._type, self._camera_id(), self._query
        if scope == "camera" and not cid:
            self._rows, self._total = [], 0
            self.rowsChanged.emit()
            self._set_loading(False)
            return
        key = (scope, type_, cid, query)
        if key != self._list_key:
            self._list_key, self._page = key, 1
        page = self._page

        def load():
            rows, total = self.api.events(camera_id=cid if scope == "camera" else None, **filter_params(type_),
                                          q=query or None, order="desc", limit=PANEL_LIMIT,
                                          offset=offset_for(page, PANEL_LIMIT))
            return [event_row(e.to_qml()) for e in rows], total

        def apply(result):
            if key != (self._scope, self._type, self._camera_id(), self._query) or page != self._page:
                self.refreshList()  # filter or page changed while loading
                return
            self._rows, self._total = result
            clamped = clamp_page(page, self._total, PANEL_LIMIT)
            if clamped != page:  # deleted the last row of the last page
                self._page = clamped
                self.refreshList()
            self.rowsChanged.emit()

        self.fetch("list", load, apply)

    @Slot(int)
    def setPage(self, page: int) -> None:
        if page >= 1 and page != self._page:
            self._page = page
            self.rowsChanged.emit()
            self.refreshList()

    # ------------------------------------------------------------------ filters
    @Slot(str)
    def setScope(self, scope: str) -> None:
        if scope in ("camera", "all") and scope != self._scope:
            self._scope = scope
            self.filterChanged.emit()
            self.refreshList()

    @Slot(str)
    def setType(self, type_: str) -> None:
        if type_ != self._type:
            self._type = type_
            self.filterChanged.emit()
            self.refreshList()

    @Slot(str)
    def setSearch(self, text: str) -> None:
        """Search box (rule name, object…): applied 300 ms after the last key."""
        if text != self._search:
            self._search = text[:64]
            self.filterChanged.emit()
            self._search_timer.start()

    def _apply_search(self) -> None:
        if self._search.strip() != self._query:
            self._query = self._search.strip()
            self.refreshList()

    # ------------------------------------------------------------------ actions
    @Slot(int, float)
    def mark(self, camera_id: int, at_ms: float = 0) -> None:
        """'Mark event': a moment on a camera, at `at_ms` (a playback moment) or now (0). In event recording mode
        the node keeps the video around it."""
        if not camera_id:
            return
        body: dict = {"type": "manual", "duration_seconds": 0, "ongoing": False}
        if at_ms > 0:
            body["start_time"] = _utc(at_ms).isoformat()
        self.act(lambda: self.api.create_event(camera_id, body).to_qml(),
                 success=lambda e: "Added to the last event" if e.get("merged") else "Event marked",
                 after=lambda _e: self.refresh())

    @Slot(int)
    def end(self, event_id: int) -> None:
        self.act(lambda: self.api.end_event(event_id), "Event ended", lambda _e: self.refresh())

    @Slot(int)
    def remove(self, event_id: int) -> None:
        self.act(lambda: self.api.delete_event(event_id), "Event mark deleted", lambda _r: self.refresh())

    @Slot("QVariant")
    def saveAsBookmark(self, row) -> None:
        e = dict(row)
        body = bookmark_body(e)

        def after(_b):
            if self._bookmarks is not None:
                self._bookmarks.refresh()

        self.act(lambda: self.api.create_bookmark(body), "Saved as bookmark", after)

    # ------------------------------------------------------------------ properties
    def _placed(self) -> list[dict]:
        now = time.time() * 1000
        markers = [event_marker(e, now) for e in self._day_events]
        return place_markers(markers, self._playback.viewStart, self._playback.viewEnd)

    markers = Property("QVariantList", _placed, notify=markersChanged)
    rows = Property("QVariantList", lambda self: self._rows, notify=rowsChanged)
    page = Property(int, lambda self: self._page, notify=rowsChanged)
    total = Property(int, lambda self: self._total, notify=rowsChanged)
    pageSize = Property(int, lambda self: PANEL_LIMIT, constant=True)
    scope = Property(str, lambda self: self._scope, notify=filterChanged)
    type = Property(str, lambda self: self._type, notify=filterChanged)
    search = Property(str, lambda self: self._search, notify=filterChanged)
    typeOptions = Property("QVariantList", lambda self: type_options(), constant=True)
