"""Qt-side parity pieces: MpvPlayer frame step / reverse play (fake mpv) and BookmarksStore (fake API)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from settings.settings import settings

if not (settings.MPV_DLL_DIR / "libmpv-2.dll").exists():
    pytest.skip("libmpv-2.dll not installed (see README)", allow_module_level=True)

from app.video.loader import prepare_libmpv  # noqa: E402

prepare_libmpv(settings.MPV_DLL_DIR)

from PySide6.QtCore import QCoreApplication, QObject, Signal  # noqa: E402

from app.core.store import BaseStore  # noqa: E402
from app.features.playback import bookmarks_store as bm  # noqa: E402
from app.video import player as player_mod  # noqa: E402
from app.video.profiles import TIMELINE_EPOCH  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication([])


class FakeMpv:
    def __init__(self):
        self.commands, self.seeks, self.props = [], [], {}

    def command(self, *args):
        self.commands.append(args)

    def seek(self, amount, reference="relative", precision="default-precise"):
        self.seeks.append((round(amount, 3), reference, precision))

    def __setitem__(self, key, value):
        self.props[key] = value

    def terminate(self):
        pass


def make_player(pos=1000.0, speed=1.0):
    p = player_mod.MpvPlayer()
    fake = FakeMpv()
    p.bridge.player = fake
    p._mode = "playback"
    p._time_pos = pos
    p._speed = speed
    return p, fake


def epoch_ms(pos: float) -> float:
    return (TIMELINE_EPOCH.timestamp() + pos) * 1000


def test_frame_steps_use_mpv_exact_stepping():
    p, fake = make_player()
    p.frameStep()
    p.frameBackStep()
    assert fake.commands == [("frame-step",), ("frame-back-step",)]


def test_reverse_pauses_seeks_back_and_waits_for_each_seek(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(player_mod.time, "monotonic", lambda: clock[0])
    p, fake = make_player(pos=1000.0, speed=2)
    p.startReverse(epoch_ms(900.0))
    assert p.reversing and fake.props["pause"] is True
    clock[0] = 11.0
    p._reverse_tick()
    assert fake.seeks[-1] == (998.0, "absolute", "exact")
    clock[0] = 11.1
    p._reverse_tick()  # previous seek not finished: no new seek
    assert len(fake.seeks) == 1
    p._handle_mpv_event("playback-restart", None)
    p._reverse_tick()
    assert fake.seeks[-1] == (997.8, "absolute", "exact")


def test_reverse_stops_at_the_start_and_on_play(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(player_mod.time, "monotonic", lambda: clock[0])
    p, fake = make_player(pos=901.0, speed=8)
    p.startReverse(epoch_ms(900.0))
    clock[0] = 1.0
    p._reverse_tick()
    assert fake.seeks[-1] == (900.0, "absolute", "keyframes") and not p.reversing
    p._time_pos = 900.0  # (the fake mpv doesn't move: put the playhead where the seek went)
    p.startReverse(epoch_ms(900.0))  # already at the start: refuses
    assert not p.reversing
    p._time_pos = 950.0
    p.startReverse(epoch_ms(900.0))
    p._handle_mpv_event("prop:pause", False)  # play pressed
    assert not p.reversing


def test_reverse_stops_on_frame_step_and_new_source():
    p, _fake = make_player()
    p.startReverse(epoch_ms(0))
    p.frameStep()
    assert not p.reversing
    p.startReverse(epoch_ms(0))
    p.source = "http://central/new.m3u8"
    assert not p.reversing


def test_reverse_only_in_playback_mode():
    p, _fake = make_player()
    p._mode = "live"
    p.startReverse(0)
    assert not p.reversing


# ---------------------------------------------------------------- BookmarksStore
class FakePlayback(QObject):
    selectionChanged = Signal()
    viewChanged = Signal()

    def __init__(self):
        super().__init__()
        self.cameraId, self.profile = 1, "main"
        self.day = datetime(2026, 11, 9, tzinfo=timezone.utc).timestamp() * 1000
        self.viewStart, self.viewEnd = self.day, self.day + 86_400_000


def _bookmark(id_, minutes, **kw):
    t = datetime.fromtimestamp((FakePlayback().day + minutes * 60_000) / 1000, timezone.utc)
    return SimpleNamespace(to_qml=lambda: {"id": id_, "camera_id": 1, "camera_name": "Gate", "profile": "main",
                                           "start_time": t.isoformat(), "end_time": None, "note": f"n{id_}",
                                           "label": None, "color": None, **kw})


class FakeApi:
    def __init__(self):
        self.calls, self.created, self.deleted = [], [], []

    def bookmarks(self, **kw):
        self.calls.append(kw)
        return [_bookmark(1, 60), _bookmark(2, 720)]

    def create_bookmark(self, body):
        self.created.append(body)
        return body

    def delete_bookmark(self, bookmark_id):
        self.deleted.append(bookmark_id)


@pytest.fixture
def store(monkeypatch):
    def sync_fetch(self, name, fn, on_ok, track_error=True, on_err=None):
        on_ok(fn())

    def sync_act(self, fn, success=None, after=None, on_error=None):
        result = fn()
        if after:
            after(result)

    monkeypatch.setattr(BaseStore, "fetch", sync_fetch)
    monkeypatch.setattr(BaseStore, "act", sync_act)
    monkeypatch.setattr(bm.Poller, "start", lambda self, **kw: None)
    api = FakeApi()
    ctx = SimpleNamespace(central=api, toasts=SimpleNamespace(error=lambda m: None, success=lambda m: None))
    playback = FakePlayback()
    return bm.BookmarksStore(ctx, playback), api, playback


def test_day_markers_follow_the_selection_and_view(store):
    s, api, playback = store
    playback.selectionChanged.emit()
    day_call = next(c for c in api.calls if "start" in c)
    assert day_call["camera_id"] == 1 and day_call["profile"] == "main" and day_call["limit"] == bm.DAY_LIMIT
    assert [round(m["x"], 3) for m in s.markers] == [round(60 / 1440, 3), 0.5]
    playback.viewStart, playback.viewEnd = playback.day, playback.day + 3_600_000 * 2  # zoom to 00:00-02:00
    assert [m["id"] for m in s.markers] == ["bookmark-1"]


def test_panel_scope_and_newest_first(store):
    s, api, _playback = store
    s.refreshList()
    assert api.calls[-1] == {"camera_id": 1, "q": "", "order": "desc", "limit": bm.PANEL_LIMIT}
    assert s.rows[0]["startMs"] > 0 and s.rows[0]["camera_name"] == "Gate"
    s.setScope("all")
    assert api.calls[-1]["camera_id"] is None


def test_create_point_and_range_then_refresh(store):
    s, api, playback = store
    start = playback.day + 3_600_000
    s.create(start, 0, "  Truck  ", "", "#ef4444")
    s.create(start, 30, "Car", "vehicle", "")
    point, ranged = api.created
    assert point["note"] == "Truck" and point["end_time"] is None and point["label"] is None
    assert point["color"] == "#ef4444" and point["camera_id"] == 1 and point["profile"] == "main"
    assert ranged["end_time"].startswith("2026-11-09T01:00:30") and ranged["color"] is None
    calls_before = len(api.calls)
    s.remove(2)
    assert api.deleted == [2] and len(api.calls) > calls_before  # refreshed after delete


def test_blank_note_is_rejected(store):
    s, api, _playback = store
    s.create(1.0, 0, "   ", "", "")
    assert api.created == []
