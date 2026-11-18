"""Recording schedules on the desktop (docs/DESKTOP_RECORDING_SCHEDULES_PLAN.md): SchedulesStore (list, site clock,
permission gating, create / update / delete / apply, the 409 message) and the ScheduleEditor draft (painting,
templates, block edits, canSave). No server: a fake API, and BaseStore.fetch / act run synchronously."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.core.api.errors import ApiError
from app.core.store import BaseStore
from app.features.schedules.store import SchedulesStore

app = QCoreApplication.instance() or QCoreApplication([])

OFFICE = {"id": 1, "name": "Office", "description": None, "camera_count": 2, "recording_now": False,
          "next_change": "2026-11-17T08:00:00+05:30",
          "blocks": [{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "18:00", "mode": "continuous"}]}


class Row(SimpleNamespace):
    def to_qml(self):
        return dict(self.__dict__)


class FakeApi:
    def __init__(self):
        self.items = [dict(OFFICE)]
        self.calls: list[tuple] = []

    def schedules(self):
        self.calls.append(("list",))
        return [Row(**s) for s in self.items]

    def site_time(self):
        return Row(timezone="Asia/Kolkata", now="2026-11-16T19:12:00+05:30")

    def create_schedule(self, body):
        self.calls.append(("create", body))
        return Row(**{**OFFICE, "id": 2, **body, "camera_count": 0})

    def update_schedule(self, sid, body):
        self.calls.append(("update", sid, body))
        return Row(**{**OFFICE, **body})

    def delete_schedule(self, sid):
        self.calls.append(("delete", sid))
        raise ApiError(409, "2 camera(s) use this schedule. Move them to another schedule or mode first.")

    def apply_schedule(self, mode, schedule_id, camera_ids, group_id, include_subgroups, events=None):
        self.calls.append(("apply", mode, schedule_id, camera_ids, group_id, include_subgroups, events))
        return 3


class Prefs(QObject):
    pollSecondsChanged = Signal()
    pollSeconds = 5


class Ctx(QObject):
    centralChanged = Signal()

    def __init__(self, api, perms=None):
        super().__init__()
        self.central = api
        self.prefs = Prefs()
        self.errors: list[str] = []
        self.successes: list[str] = []
        self.toasts = SimpleNamespace(error=self.errors.append, success=self.successes.append)
        self._perms = perms

    def can(self, *perms):
        return self._perms is None or any(p in self._perms for p in perms)


@pytest.fixture
def sync(monkeypatch):
    def fetch(self, name, fn, on_ok, track_error=True, on_err=None):
        try:
            result = fn()
        except Exception as exc:
            if on_err:
                on_err(exc)
            return
        on_ok(result)
        if track_error:
            self._set_loading(False)

    def act(self, fn, success=None, after=None, on_error=None):
        try:
            result = fn()
        except Exception as exc:
            self.ctx.toasts.error(str(exc))
            if on_error:
                on_error(exc)
            return
        if success:
            self.ctx.toasts.success(success(result) if callable(success) else success)
        if after:
            after(result)

    monkeypatch.setattr(BaseStore, "fetch", fetch)
    monkeypatch.setattr(BaseStore, "act", act)
    monkeypatch.setattr("app.core.poller.Poller.start", lambda self, immediately=True: self._refresh() if immediately else None)
    return FakeApi()


def test_list_site_clock_and_texts(sync):
    store = SchedulesStore(Ctx(sync))
    store.setActive(True)
    row = store.items[0]
    assert row["name"] == "Office" and row["cameraCount"] == 2 and row["summary"] == "Mon–Fri 08:00–18:00"
    assert row["nowText"].startswith("Off now, until Tue 08:00") or "Nov" in row["nowText"]
    assert row["state"] == "off" and not row["usesEvents"]
    assert row["rows"][0] == [{"start": 480, "end": 1080, "event": False}] and row["rows"][6] == []
    assert store.siteZone == "Asia/Kolkata" and (store.siteNowDay, store.siteNowMinute) == (0, 19 * 60 + 12)
    assert store.siteText == "Site time: Asia/Kolkata, now Mon 19:12."
    assert store.byId(1)["name"] == "Office" and store.byId(9) is None


def test_no_reads_without_permission(sync):
    store = SchedulesStore(Ctx(sync, perms={1}))  # live view only
    store.setActive(True)
    store.ensureLoaded()
    assert sync.calls == [] and store.count == 0 and not store.loading


def last(api, kind):
    return next(c for c in reversed(api.calls) if c[0] == kind)


def test_actions_refresh_camera_pages_and_report_errors(sync):
    refreshed = []
    ctx = Ctx(sync)
    store = SchedulesStore(ctx, [lambda: refreshed.append("cameras")])
    saved, applied, failed = [], [], []
    store.saved.connect(saved.append)
    store.applied.connect(applied.append)
    store.failed.connect(lambda: failed.append(1))

    store.apply("schedule", 1, [5, 6], 7, False, None)
    assert last(sync, "apply") == ("apply", "schedule", 1, [5, 6], 7, False, None)
    assert applied == [3] and refreshed == ["cameras"] and ctx.successes[-1] == "Recording updated for 3 cameras"
    events = {"pre": 5, "post": 60, "marking": False}
    store.apply("event", 0, [], 7, True, events)
    assert last(sync, "apply") == ("apply", "event", None, [], 7, True, events)
    calls = len(sync.calls)
    store.apply("event", 0, [], 7, True, {"pre": 61, "post": 30, "marking": True})  # refused before the API
    assert len(sync.calls) == calls and failed == [1] and ctx.errors[-1] == "Before: 0–60 s, after: 0–600 s."
    failed.clear()

    store.remove(1)
    assert failed == [1] and "2 camera(s) use this schedule" in ctx.errors[-1]

    ed = store.editorState
    ed.open(None, False)
    ed.setName("  Night shift ")
    ed.applyTemplate("nights")
    ed.save()
    _, body = last(sync, "create")
    assert body["name"] == "Night shift" and body["blocks"][0]["start"] == "18:00"
    assert saved == [2] and not ed.busy

    ed.open(store.byId(1), False)
    ed.setDescription("weekdays")
    ed.save()
    assert last(sync, "update")[1] == 1 and last(sync, "update")[2]["description"] == "weekdays"


def test_editor_painting_and_block_edits(sync):
    store = SchedulesStore(Ctx(sync))
    ed = store.editorState
    ed.open(None, False)  # new = Office hours
    assert ed.rows[0] == [{"start": 480, "end": 1080, "event": False}] and ed.hoursText == "Records 50 h of 168 h a week (30%)."
    ed.paint(6, 5, 55, 40)  # Sat-Sun 10:00-14:00, dragged backwards
    assert [b["label"] for b in ed.blocks] == ["Mon–Fri 08:00–18:00", "Sat, Sun 10:00–14:00"]
    ed.setBrush("off")
    ed.paint(0, 4, 32, 71)
    assert [b["label"] for b in ed.blocks] == ["Sat, Sun 10:00–14:00"]

    ed.setBrush("event")  # Sat-Sun 18:00-24:00 keeps video around events
    ed.paint(5, 6, 72, 95)
    assert [b["label"] for b in ed.blocks] == ["Sat, Sun 10:00–14:00", "Sat, Sun 18:00–24:00 · event"]
    assert ed.blocks[1]["mode"] == "event" and ed.hoursText.endswith(", event recording 12 h.")
    ed.setMode(1, "continuous")
    assert ed.blocks[1]["label"] == "Sat, Sun 18:00–24:00" and ed.hoursText == "Records 20 h of 168 h a week (12%)."
    ed.removeBlock(1)

    ed.addBlock()
    ed.setTime(1, "start", "8:00")
    assert not ed.canSave  # no name and a bad time
    ed.setName("Mixed")
    assert not ed.canSave and ed.blocks[1]["startBad"] and ed.blocks[1]["error"]
    ed.setTime(1, "start", "22:00")
    ed.setTime(1, "end", "06:00")
    assert ed.canSave and ed.blocks[1]["hint"] == "next day"
    ed.toggleDay(1, 0)  # Mon off
    assert ed.blocks[1]["days"] == [1, 2, 3, 4]
    ed.removeBlock(0)
    ed.clear()
    assert ed.blocks == [] and ed.canSave and ed.hoursText == "Records 0 h of 168 h a week."

    ed.open(store.byId(1) or OFFICE, True)  # read-only: painting does nothing, no save
    before = ed.blocks
    ed.paint(5, 6, 0, 95)
    assert ed.blocks == before and not ed.canSave
