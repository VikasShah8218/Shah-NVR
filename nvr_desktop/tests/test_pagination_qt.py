"""Paged stores (docs/PAGINATION_PLAN.md): PagedStore page/search/clamp/newest-wins, the camera cache behind
Cameras.byId (track), CameraOptionsStore "Load more", Live grid pages and the dashboard's paged camera alerts.
No server: a fake API, and BaseStore.fetch / act run synchronously."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.core import paged_store
from app.core.store import BaseStore
from app.features.cameras import options_store as opt
from app.features.cameras import store as cam
from app.features.dashboard import store as dash
from app.features.live import store as live

app = QCoreApplication.instance() or QCoreApplication([])


def camera(i: int, name: str | None = None) -> dict:
    return {"id": i, "name": name or f"Cam {i:03d}", "enabled": True, "streams": [
        {"profile": "main", "record": True, "status": "RECORDING", "last_segment_at": None}], "assignment": None}


class Row(SimpleNamespace):
    def to_qml(self):
        return dict(self.__dict__)


class FakeApi:
    def __init__(self, n=120):
        self.all = [camera(i) for i in range(1, n + 1)]
        self.calls: list[tuple] = []

    def cameras(self, *, q=None, enabled=None, node_id=None, status=None, limit=50, offset=0):
        self.calls.append(("cameras", q, enabled, status, limit, offset))
        rows = [c for c in self.all if not q or q.lower() in c["name"].lower()]
        return [Row(**c) for c in rows[offset:offset + limit]], len(rows)

    def cameras_by_ids(self, ids):
        self.calls.append(("ids", tuple(ids)))
        return [Row(**c) for c in self.all if c["id"] in ids]

    def camera_options(self, *, q=None, enabled=None, node_id=None, limit=50, offset=0):
        self.calls.append(("options", q, enabled, limit, offset))
        rows = [{"id": c["id"], "name": c["name"], "enabled": True, "has_ptz": False, "profiles": ["main"],
                 "status": "RECORDING", "node_id": None} for c in self.all if not q or q.lower() in c["name"].lower()]
        return [Row(**r) for r in rows[offset:offset + limit]], len(rows)

    def alerts(self, *, level=None, limit=10, offset=0):
        rows = [{"level": "danger" if i < 3 else "warning", "kind": "stream", "title": f"A{i}", "detail": "d",
                 "since": None, "camera_id": i, "camera_name": f"c{i}", "profile": "main"} for i in range(25)]
        shown = [r for r in rows if level in (None, r["level"])]
        self.calls.append(("alerts", level, limit, offset))
        return [Row(**r) for r in shown[offset:offset + limit]], len(shown), {"danger": 3, "warning": 22}


class Prefs(QObject):
    pollSecondsChanged = Signal()
    pollSeconds = 5

    def live_layout(self):
        return 4, [None] * 16

    def save_live_layout(self, layout, tiles):
        pass


class Ctx(QObject):
    centralChanged = Signal()

    def __init__(self, api):
        super().__init__()
        self.central = api
        self.prefs = Prefs()
        self.errors: list[str] = []
        self.toasts = SimpleNamespace(error=self.errors.append, success=lambda m: None)


@pytest.fixture
def sync(monkeypatch):
    def fetch(self, name, fn, on_ok, track_error=True, on_err=None):
        try:
            result = fn()
        except Exception as exc:  # pragma: no cover - surfaced through on_err in the stores
            if on_err:
                on_err(exc)
            return
        on_ok(result)

    def act(self, fn, success=None, after=None, on_error=None):
        result = fn()
        if after:
            after(result)

    monkeypatch.setattr(BaseStore, "fetch", fetch)
    monkeypatch.setattr(BaseStore, "act", act)
    monkeypatch.setattr("app.core.poller.Poller.start", lambda self, immediately=True: self._refresh() if immediately else None)
    api = FakeApi()
    return api, Ctx(api)


def test_camera_pages_search_and_page_size(sync):
    api, ctx = sync
    s = cam.CamerasStore(ctx)
    assert s.total == 120 and s.pageCount == 3 and len(s.rows) == 50 and s.rangeLabel == "1–50 of 120"
    s.next()
    s.next()
    assert s.page == 3 and [r["id"] for r in s.rows][:2] == [101, 102] and api.calls[-1][-1] == 100
    s.setPageSize(25)
    assert s.page == 1 and s.pageCount == 5
    s.setSearch("cam 11")
    s._apply_search()  # (the debounce timer, fired by hand)
    assert s.page == 1 and s.total == 10 and api.calls[-1][1] == "cam 11"  # Cam 110..119
    s.setFilter("not_recording")
    assert api.calls[-1][3] == "NOT_RECORDING"


def test_page_steps_back_when_the_list_shrinks(sync):
    api, ctx = sync
    s = cam.CamerasStore(ctx)
    s.setPage(3)
    del api.all[60:]  # 60 cameras left: page 3 no longer exists
    s.refresh()
    assert s.page == 2 and s.total == 60 and len(s.rows) == 10


def test_only_the_newest_answer_is_applied(sync, monkeypatch):
    api, ctx = sync
    s = cam.CamerasStore(ctx)
    pending = []
    monkeypatch.setattr(BaseStore, "fetch", lambda self, name, fn, on_ok, **kw: pending.append((fn, on_ok)))
    s.setPage(2)
    s.setPage(3)
    (fn2, ok2), (fn3, ok3) = pending
    ok3(fn3())
    ok2(fn2())  # the slow page-2 answer arrives last: ignored
    assert s.page == 3 and s.rows[0]["id"] == 101


def test_tracked_cameras_are_fetched_by_id_and_kept(sync):
    api, ctx = sync
    s = cam.CamerasStore(ctx)
    s.track("live", [7, 115])  # 115 is not on page 1
    assert s.byId(115)["name"] == "Cam 115" and ("ids", (115,)) in api.calls
    before = s.revision
    api.all[114]["name"] = "Renamed"
    s._poll()  # the poll refreshes the tracked cameras too
    assert s.byId(115)["name"] == "Renamed" and s.revision > before


def test_options_load_more_and_search(sync):
    api, ctx = sync
    o = opt.CameraOptionsStore(ctx)
    assert len(o.rows) == 50 and o.total == 120 and o.hasMore and o.moreLabel == "Load more (50 of 120)"
    o.loadMore()
    o.loadMore()
    assert len(o.rows) == 120 and not o.hasMore
    o.refresh()  # a poll keeps what is shown (up to 200 rows)
    assert len(o.rows) == 120 and api.calls[-1][-2:] == (120, 0)
    o.setSearch("cam 01")
    o._apply_search()
    assert o.total == 10 and len(o.rows) == 10


def test_live_grid_pages_fill_the_grid_and_wrap(sync):
    api, ctx = sync
    cameras = cam.CamerasStore(ctx)
    nodes = SimpleNamespace(access=lambda node_id: "lan")
    api.live = lambda cid, access: Row(camera_id=cid, streams=[])
    s = live.LiveStore(ctx, cameras, nodes)
    assert s.gridTotal == 120 and s.gridPages == 30 and s.gridPage == 0
    s.nextGridPage()
    assert s.gridPage == 1 and s.tiles == [1, 2, 3, 4]
    assert cameras.byId(4) is not None  # tiles are tracked: full rows cached
    s.prevGridPage()
    assert s.gridPage == 30 and s.tiles == [117, 118, 119, 120]  # wraps around
    s.place(9, 0)
    assert s.gridPage == 0  # a manual change ends the grid page


def test_dashboard_pages_camera_alerts_under_node_alerts(sync):
    api, ctx = sync
    class Cluster(QObject):
        changed = Signal()
        camerasTotal = camerasEnabled = recording = segmentsLastHour = segmentsTotal = 0
        recordStreams = 4

    class Nodes(QObject):
        nodesChanged = Signal()
        totals = {"healthy": 1, "nodes": 1, "recordings": 0, "netRx": 0}

        def nodes(self):
            return [{"id": 1, "name": "n1", "state": "UNREACHABLE", "metrics": {}, "volumes": [],
                     "storage_quota_bytes": None, "last_heartbeat_at": None}]

    d = dash.DashboardStore(ctx, Cluster(), Nodes())
    titles = [r["title"] for r in d.alerts.items()]
    assert titles[0] == "n1 is unreachable" and titles[1:] == [f"A{i}" for i in range(10)]
    assert d.alertCounts == {"all": 26, "danger": 4, "warning": 22} and d.kpis["recordStreams"] == 4
    d.setAlertPage(3)
    assert [r["title"] for r in d.alerts.items()][1:] == ["A20", "A21", "A22", "A23", "A24"]
    d.setLevel("warning")
    assert d.alertPage == 1 and api.calls[-1] == ("alerts", "warning", 10, 0)
    assert [r["title"] for r in d.alerts.items()][0] == "A3"  # node alert is danger: hidden


def test_paged_store_debounce_constant():
    assert paged_store.SEARCH_DEBOUNCE_MS == opt.SEARCH_DEBOUNCE_MS == 300
