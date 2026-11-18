"""SchedulesStore: recording schedules (port of nvr_client features/schedules, docs/DESKTOP_RECORDING_SCHEDULES_PLAN.md).

QML singleton `Schedules`:
* the list for the Schedules page and for every "choose a schedule" dropdown (camera form, Apply dialog);
* the site clock schedules run on (SITE_TIMEZONE on central), moved forward locally between fetches;
* actions: create / update / delete a schedule, and apply a recording mode to cameras or a whole group;
* `editor` (ScheduleEditor): the draft of the schedule being edited, painted on the week grid.

The painting logic lives here (app/features/schedules/schedule.py), so QML only draws rows and reports drags.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from app.core.auth.permissions import Perm
from app.core.context import AppContext
from app.core.list_model import DictListModel
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.events import event_settings
from app.features.schedules import schedule as sch

ROLES = ["id", "name", "description", "summary", "nowText", "recordingNow", "state", "usesEvents", "cameraCount", "rows",
         "blocks"]


def _state(s: dict) -> str:
    """The schedule's mode now (an older central only says recording or not)."""
    return s.get("state_now") or sch.state_of(bool(s.get("recording_now")))


def _row(s: dict) -> dict:
    return {
        "id": s["id"], "name": s["name"], "description": s.get("description") or "",
        "summary": s.get("description") or sch.blocks_summary(s["blocks"]),
        "nowText": sch.now_text(_state(s), s.get("next_change")),
        "recordingNow": s["recording_now"], "state": _state(s), "usesEvents": sch.uses_events(s["blocks"]),
        "nextChange": s.get("next_change") or "",
        "cameraCount": s["camera_count"], "rows": sch.week_rows(s["blocks"]), "blocks": s["blocks"],
    }


class ScheduleEditor(QObject):
    """The draft behind the editor dialog: name, description and blocks (with a per-block error)."""

    changed = Signal()

    def __init__(self, store: SchedulesStore):
        super().__init__(store)
        self._store = store
        self._id = 0
        self._name = ""
        self._description = ""
        self._blocks: list[dict] = []
        self._brush = "on"
        self._read_only = False
        self._busy = False

    # ------------------------------------------------------------------ open
    @Slot("QVariant", bool)
    def open(self, schedule, read_only: bool = False) -> None:
        """Start editing `schedule` (a list row), or a new one (null) starting from Office hours."""
        s = dict(schedule) if schedule else None
        self._id = int(s["id"]) if s else 0
        self._name = s["name"] if s else ""
        self._description = (s or {}).get("description") or ""
        self._blocks = [dict(b, days=list(b["days"])) for b in (s["blocks"] if s else sch.TEMPLATES[1]["blocks"])]
        self._brush, self._read_only, self._busy = "on", read_only, False
        self.changed.emit()

    # ------------------------------------------------------------------ edits
    def _set_blocks(self, blocks: list[dict]) -> None:
        self._blocks = blocks
        self.changed.emit()

    @Slot(str)
    def setName(self, value: str) -> None:
        self._name = value
        self.changed.emit()

    @Slot(str)
    def setDescription(self, value: str) -> None:
        self._description = value
        self.changed.emit()

    @Slot(str)
    def setBrush(self, value: str) -> None:
        self._brush = value if value in ("off", "event") else "on"
        self.changed.emit()

    @Slot(int, int, int, int)
    def paint(self, d0: int, d1: int, q0: int, q1: int) -> None:
        """A drag on the grid: days d0..d1 x 15-min slots q0..q1 become Record, Event or Off (the brush)."""
        if not self._read_only:
            self._set_blocks(sch.paint(self._valid(), d0, d1, q0, q1, self._brush) + self._invalid())

    @Slot(str)
    def applyTemplate(self, key: str) -> None:
        t = next((t for t in sch.TEMPLATES if t["key"] == key), None)
        if t:
            self._set_blocks([dict(b, days=list(b["days"])) for b in t["blocks"]])

    @Slot()
    def clear(self) -> None:
        self._set_blocks([])

    @Slot()
    def addBlock(self) -> None:
        if len(self._blocks) < sch.MAX_BLOCKS:
            self._set_blocks(self._blocks + [sch.block([0, 1, 2, 3, 4], "08:00", "18:00")])

    @Slot(int)
    def removeBlock(self, index: int) -> None:
        self._set_blocks([b for i, b in enumerate(self._blocks) if i != index])

    @Slot(int, int)
    def toggleDay(self, index: int, day: int) -> None:
        def flip(b):
            days = set(b["days"]) ^ {day}
            return dict(b, days=sorted(days))
        self._set_blocks([flip(b) if i == index else b for i, b in enumerate(self._blocks)])

    @Slot(int, str, str)
    def setTime(self, index: int, which: str, value: str) -> None:
        key = "end" if which == "end" else "start"
        self._set_blocks([dict(b, **{key: value.strip()}) if i == index else b for i, b in enumerate(self._blocks)])

    @Slot(int, str)
    def setMode(self, index: int, mode: str) -> None:
        """A block's mode: continuous (record) / event / off."""
        if mode in sch.MODE_VALUE:
            self._set_blocks([dict(b, mode=mode) if i == index else b for i, b in enumerate(self._blocks)])

    @Slot()
    def save(self) -> None:
        if not self._can_save():
            return
        self._busy = True
        self.changed.emit()
        body = {"name": self._name.strip(), "description": self._description.strip() or None,
                "blocks": [dict(b, mode=b.get("mode", "continuous")) for b in self._blocks]}
        self._store.save_schedule(self._id, body, self._done)

    def _done(self) -> None:
        self._busy = False
        self.changed.emit()

    # ------------------------------------------------------------------ derived
    def _valid(self) -> list[dict]:
        return [b for b in self._blocks if not sch.block_error(b)]

    def _invalid(self) -> list[dict]:
        return [b for b in self._blocks if sch.block_error(b)]

    def _can_save(self) -> bool:
        return (not self._read_only and not self._busy and bool(self._name.strip())
                and len(self._blocks) <= sch.MAX_BLOCKS and all(not sch.block_error(b) for b in self._blocks))

    def _block_rows(self) -> list[dict]:
        out = []
        for i, b in enumerate(self._blocks):
            err = sch.block_error(b) or ""
            hint = ""
            if not err and b["end"] != "00:00" and sch.parse_hhmm(b["end"]) <= sch.parse_hhmm(b["start"]):
                hint = "24 h" if b["start"] == b["end"] else "next day"
            out.append({"index": i, "days": b["days"], "start": b["start"], "end": b["end"], "error": err,
                        "mode": b.get("mode") or "continuous",
                        "startBad": not sch.TIME_RE.match(b["start"]), "endBad": not sch.TIME_RE.match(b["end"]),
                        "hint": hint, "label": sch.block_label(b) if not err else ""})
        return out

    def _hours_text(self) -> str:
        hours = sch.recorded_hours(self._valid())
        events = sch.event_hours(self._valid())
        pct = f" ({round(hours / 168 * 100)}%)" if 0 < hours < 168 else ""
        ev = f", event recording {round(events * 10) / 10:g} h" if events else ""
        return f"Records {round(hours * 10) / 10:g} h of 168 h a week{pct}{ev}."

    scheduleId = Property(int, lambda self: self._id, notify=changed)
    name = Property(str, lambda self: self._name, notify=changed)
    description = Property(str, lambda self: self._description, notify=changed)
    brush = Property(str, lambda self: self._brush, notify=changed)
    readOnly = Property(bool, lambda self: self._read_only, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    canSave = Property(bool, _can_save, notify=changed)
    blocks = Property("QVariantList", _block_rows, notify=changed)
    rows = Property("QVariantList", lambda self: sch.week_rows(self._valid()), notify=changed)
    hoursText = Property(str, _hours_text, notify=changed)
    canAddBlock = Property(bool, lambda self: len(self._blocks) < sch.MAX_BLOCKS, notify=changed)


class SchedulesStore(BaseStore):
    changed = Signal()
    siteChanged = Signal()
    saved = Signal(int)  # schedule id after a create / update (closes the editor)
    applied = Signal(int)  # cameras changed by apply (closes the Apply dialog)
    failed = Signal()  # an action failed (the toast says why): dialogs re-enable their buttons

    def __init__(self, ctx: AppContext, after_change: list[Callable[[], None]] = (), parent=None):
        super().__init__(ctx, parent)
        self.model = DictListModel(ROLES)
        self._items: list[dict] = []
        self._after_change = list(after_change)  # refresh camera pages after an apply / a camera's schedule change
        self._active = False
        self._zone = ""
        self._site_minute = -1  # minute of the week (Mon 00:00 = 0) at `_site_at`
        self._site_at = 0.0
        self.editor = ScheduleEditor(self)
        self._poller = Poller(self.refresh, ctx.prefs.pollSeconds * 3, self)
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds * 3))
        ctx.centralChanged.connect(self.refresh)
        self._clock = QTimer(self)  # moves the "now" line between site-time fetches
        self._clock.setInterval(30_000)
        self._clock.timeout.connect(self.siteChanged.emit)

    def _may_read(self) -> bool:
        return self.allowed(Perm.CAMERAS_MANAGE, Perm.DASHBOARD)

    # ------------------------------------------------------------------ reads
    @Slot()
    def refresh(self) -> None:
        self._load("list")

    def _load(self, name: str) -> None:
        if not self._may_read():
            self._set_loading(False)
            return
        self.fetch(name, lambda: [s.to_qml() for s in self.api.schedules()], self._apply)
        self.fetch("site", lambda: self.api.site_time().to_qml(), self._apply_site, track_error=False)

    @Slot()
    def ensureLoaded(self) -> None:
        """For dropdowns outside the page: load once if nothing is loaded yet (no polling)."""
        if not self._items:
            self.refresh()

    def _apply(self, items: list[dict]) -> None:
        self._items = [_row(s) for s in items]
        self.model.set_items(self._items)
        self.changed.emit()

    def _apply_site(self, site: dict) -> None:
        day, minute, _ = sch.site_wall(site["now"])
        self._zone = site["timezone"]
        self._site_minute = day * sch.DAY_MIN + minute
        self._site_at = time.monotonic()
        self.siteChanged.emit()

    @Slot(bool)
    def setActive(self, active: bool) -> None:
        """Poll only while the Schedules page is open."""
        if active == self._active:
            return
        self._active = active
        if active:
            self._poller.start()
            self._clock.start()
        else:
            self._poller.stop()
            self._clock.stop()

    def _site_now(self) -> int:
        if self._site_minute < 0:
            return -1
        passed = int((time.monotonic() - self._site_at) // 60)
        return (self._site_minute + passed) % sch.WEEK_MIN

    def _site_text(self) -> str:
        if not self._zone:
            return ""
        now = self._site_now()
        return f"Site time: {self._zone}, now {sch.DAYS[now // sch.DAY_MIN]} {sch.fmt_hhmm(now % sch.DAY_MIN)}."

    # ------------------------------------------------------------------ helpers for QML
    @Slot(int, result="QVariant")
    def byId(self, schedule_id: int):
        return next((s for s in self._items if s["id"] == schedule_id), None)

    @Slot("QVariant", str, result=str)
    def nowText(self, state, next_change: str) -> str:
        """`state`: "continuous" / "event" / "off", or a bool (recording now) from an older central."""
        return sch.now_text(state, next_change or None)

    @Slot("QVariant", result=bool)
    def eventSettingsValid(self, events) -> bool:
        return event_settings.valid(dict(events or {}))

    @Slot("QVariant", result="QVariant")
    def eventSettingsOf(self, camera):
        """The event settings of a camera (API dict), or the defaults for a new one."""
        return event_settings.of_camera(dict(camera) if camera else None)

    @Slot("QVariant", result=str)
    def cameraState(self, camera) -> str:
        """A camera's recording mode now: continuous / event / off."""
        c = dict(camera or {})
        return c.get("recording_state") or sch.state_of(c.get("recording_now") is not False)

    @Slot(str, result=str)
    def lowerFirst(self, text: str) -> str:
        return sch.lower_first(text)

    # ------------------------------------------------------------------ actions
    def _changed(self) -> None:
        self._load("after-change")  # own name: not skipped while a poll of the list is still running
        for fn in self._after_change:
            fn()

    def save_schedule(self, schedule_id: int, body: dict, done: Callable[[], None]) -> None:
        def after(s):
            done()
            self._changed()
            self.saved.emit(s["id"])

        def error(_e):
            done()
            self.failed.emit()

        if schedule_id:
            fn = lambda: self.api.update_schedule(schedule_id, body).to_qml()  # noqa: E731
            success = lambda s: f'Schedule "{s["name"]}" saved'  # noqa: E731
        else:
            fn = lambda: self.api.create_schedule(body).to_qml()  # noqa: E731
            success = lambda s: f'Schedule "{s["name"]}" created'  # noqa: E731
        self.act(fn, success=success, after=after, on_error=error)

    @Slot(int)
    def remove(self, schedule_id: int) -> None:
        self.act(lambda: self.api.delete_schedule(schedule_id), success="Schedule deleted",
                 after=lambda _r: self._changed(), on_error=lambda _e: self.failed.emit())

    @Slot(str, int, "QVariantList", int, bool, "QVariant")
    def apply(self, mode: str, schedule_id: int, camera_ids, group_id: int, include_subgroups: bool,
              events=None) -> None:
        """Set the recording mode of listed cameras and/or a whole group (ids: 0 = none), and the event settings
        (`events` {pre, post, marking}; null = unchanged)."""
        ids = [int(x) for x in camera_ids or []]
        events = dict(events) if events else None
        if events and not event_settings.valid(events):
            self.ctx.toasts.error(event_settings.INVALID_TEXT)
            self.failed.emit()
            return

        def after(n):
            self._changed()
            self.applied.emit(n)

        self.act(lambda: self.api.apply_schedule(mode, schedule_id or None, ids, group_id or None, include_subgroups,
                                                 events),
                 success=lambda n: f"Recording updated for {n} camera{'' if n == 1 else 's'}",
                 after=after, on_error=lambda _e: self.failed.emit())

    def notify_camera_changed(self) -> None:
        """A camera's schedule changed elsewhere (camera form): the camera counts change."""
        if self._items:
            self.refresh()

    # ------------------------------------------------------------------ properties
    items = Property("QVariantList", lambda self: self._items, notify=changed)
    count = Property(int, lambda self: len(self._items), notify=changed)
    listModel = Property(QObject, lambda self: self.model, constant=True)
    editorState = Property(QObject, lambda self: self.editor, constant=True)
    templates = Property("QVariantList", lambda self: [{k: t[k] for k in ("key", "label", "hint")} for t in sch.TEMPLATES],
                         constant=True)
    siteZone = Property(str, lambda self: self._zone, notify=siteChanged)
    siteNowDay = Property(int, lambda self: self._site_now() // sch.DAY_MIN if self._site_now() >= 0 else -1, notify=siteChanged)
    siteNowMinute = Property(int, lambda self: self._site_now() % sch.DAY_MIN if self._site_now() >= 0 else -1, notify=siteChanged)
    siteText = Property(str, _site_text, notify=siteChanged)
