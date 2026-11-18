"""EventsStore (docs/DESKTOP_EVENT_RECORDING_PLAN.md): timeline marks per camera / day, the list (scope, type,
paging), permission gating and the actions (mark, end, delete, save as bookmark)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.core.store import BaseStore
from app.features.events import store as es

app = QCoreApplication.instance() or QCoreApplication([])
DAY = datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp() * 1000


class FakePlayback(QObject):
    selectionChanged = Signal()
    viewChanged = Signal()

    def __init__(self):
        super().__init__()
        self.cameraId, self.profile, self.day = 1, "main", DAY
        self.viewStart, self.viewEnd = DAY, DAY + 86_400_000


def _event(id_, minutes, **kw):
    t = datetime.fromtimestamp((DAY + minutes * 60_000) / 1000, timezone.utc).isoformat()
    data = {"id": id_, "camera_id": 1, "camera_name": "Gate", "type": "manual", "source": "user:admin",
            "start_time": t, "end_time": t, "label": None, "data": None, "pre_seconds": 10, "post_seconds": 30,
            "merged": False, **kw}
    return SimpleNamespace(to_qml=lambda: data)


class FakeApi:
    def __init__(self):
        self.calls, self.created, self.ended, self.deleted, self.bookmarks = [], [], [], [], []

    def events(self, **kw):
        self.calls.append(kw)
        return [_event(1, 60), _event(2, 720, type="video_loss", end_time=None)], 2

    def create_event(self, camera_id, body):
        self.created.append((camera_id, body))
        return _event(9, 0, merged=len(self.created) > 1)

    def end_event(self, event_id):
        self.ended.append(event_id)

    def delete_event(self, event_id):
        self.deleted.append(event_id)

    def create_bookmark(self, body):
        self.bookmarks.append(body)


@pytest.fixture
def make(monkeypatch):
    def sync_fetch(self, name, fn, on_ok, track_error=True, on_err=None):
        on_ok(fn())

    def sync_act(self, fn, success=None, after=None, on_error=None):
        result = fn()
        if success:
            self.ctx.toasts.success(success(result) if callable(success) else success)
        if after:
            after(result)

    monkeypatch.setattr(BaseStore, "fetch", sync_fetch)
    monkeypatch.setattr(BaseStore, "act", sync_act)

    def build(perms=None):
        api, toasts = FakeApi(), []
        ctx = SimpleNamespace(central=api, toasts=SimpleNamespace(error=toasts.append, success=toasts.append))
        if perms is not None:
            ctx.can = lambda *p: any(x in perms for x in p)
        bookmarks = SimpleNamespace(refreshed=0)
        bookmarks.refresh = lambda: setattr(bookmarks, "refreshed", bookmarks.refreshed + 1)
        playback = FakePlayback()
        return es.EventsStore(ctx, playback, bookmarks), api, playback, toasts, bookmarks

    return build


def test_markers_follow_camera_day_and_view(make):
    s, api, playback, _t, _b = make()
    playback.selectionChanged.emit()
    day_call = next(c for c in api.calls if c.get("start"))
    assert day_call["camera_id"] == 1 and day_call["order"] == "asc" and day_call["limit"] == es.DAY_LIMIT
    assert day_call["start"].timestamp() * 1000 == DAY and day_call["end"].timestamp() * 1000 == DAY + 86_400_000
    marks = s.markers
    assert [mk["id"] for mk in marks] == ["event-1", "event-2"] and marks[0]["width"] is None
    assert marks[1]["width"] is not None  # the open video loss runs to now
    playback.viewStart, playback.viewEnd = DAY, DAY + 2 * 3_600_000  # zoom to 00:00-02:00
    assert [mk["id"] for mk in s.markers] == ["event-1"]


def test_list_scope_type_and_paging(make):
    s, api, _p, _t, _b = make()
    s.refreshList()
    assert api.calls[-1] == {"camera_id": 1, "types": None, "order": "desc", "limit": es.PANEL_LIMIT, "offset": 0}
    assert s.total == 2 and s.rows[0]["title"] == "Marked" and s.rows[1]["duration"] == "ongoing"
    s.setScope("all")
    assert api.calls[-1]["camera_id"] is None
    s.setType("video_loss")
    assert api.calls[-1]["types"] == ["video_loss"]
    assert s.typeOptions[0] == {"value": "", "label": "All types"} and {"value": "video_loss", "label": "Video loss"} in s.typeOptions


def test_no_reads_without_playback_permission(make):
    s, api, playback, _t, _b = make(perms={1})  # live view only
    playback.selectionChanged.emit()
    s.refreshList()
    assert api.calls == [] and s.markers == [] and s.rows == []


def test_actions(make):
    s, api, _p, toasts, bookmarks = make()
    s.mark(1, 0)  # now
    s.mark(1, DAY + 3_600_000)  # at the playhead; the server merges it into the last mark
    (cid, now_body), (_, at_body) = api.created
    assert cid == 1 and now_body == {"type": "manual", "duration_seconds": 0, "ongoing": False}
    assert at_body["start_time"].startswith("2026-11-18T01:00:00")
    assert toasts[:2] == ["Event marked", "Added to the last event"]
    s.end(2)
    s.remove(1)
    assert api.ended == [2] and api.deleted == [1]
    s.saveAsBookmark(s.rows[0])
    assert api.bookmarks[0]["note"] == "Marked" and api.bookmarks[0]["label"] == "event" and bookmarks.refreshed == 1


def test_polls_only_while_a_page_is_open(make, monkeypatch):
    s, *_ = make()
    started = []
    monkeypatch.setattr(es.Poller, "start", lambda self, **kw: started.append(1))
    s.setActive(True)
    assert started == [1]
    s.setActive(False)
    assert not s._poller.active
