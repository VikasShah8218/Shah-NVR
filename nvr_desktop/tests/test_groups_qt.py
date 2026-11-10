"""Camera groups on the desktop (docs/GROUPING_PLAN.md): the lazy GroupTreeStore (flat rows, expand / collapse,
load more, newest answer wins, only visible lists poll, a deleted group is forgotten), DictListModel.sync_items,
Live "Play group" scope, the Groups page store and the API query parameters. No server: a fake API, and
BaseStore.fetch / act run synchronously."""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.core.api.errors import ApiError
from app.core.list_model import DictListModel
from app.core.store import BaseStore
from app.features.cameras import forms
from app.features.cameras import store as cam
from app.features.groups import tree
from app.features.groups.store import GroupsStore
from app.features.groups.tree_store import GroupTreeStore, LiveGroupsStore, ManageGroupsStore
from app.features.live import store as live

app = QCoreApplication.instance() or QCoreApplication([])


class Row(SimpleNamespace):
    def to_qml(self):
        return dict(self.__dict__)


def group(gid, name, parent=None, path=None, child_groups=0, cameras_direct=0, total=None, online=0):
    path = path or (f"/{parent}/{gid}/" if parent else f"/{gid}/")
    return {"id": gid, "name": name, "description": None, "parent_id": parent, "depth": path.count("/") - 2,
            "path": path, "path_label": name, "sort_order": 0, "child_groups": child_groups,
            "cameras_direct": cameras_direct, "cameras_total": cameras_direct if total is None else total,
            "online_total": online}


class FakeApi:
    def __init__(self):
        self.groups_by_parent = {
            None: [group(1, "Anantnag", child_groups=2, cameras_direct=1, total=3, online=2), group(2, "Jammu")],
            1: [group(3, "Bijbehara", 1, cameras_direct=2), group(4, "Pahalgam", 1)],
        }
        self.cameras_by_group = {1: [{"id": 10, "name": "HQ"}], 3: [{"id": 11, "name": "Gate"}, {"id": 12, "name": "Bus"}],
                                 "ungrouped": [{"id": 20 + i, "name": f"Loose {i:02d}"} for i in range(60)]}
        self.calls: list[tuple] = []
        self.missing: set[int] = set()

    def groups(self, parent_id=None, limit=50, offset=0):
        self.calls.append(("groups", parent_id, limit, offset))
        if parent_id in self.missing:
            raise ApiError(404, "Group not found")
        rows = self.groups_by_parent.get(parent_id, [])
        return [Row(**g) for g in rows[offset:offset + limit]], len(rows)

    def camera_options(self, *, q=None, enabled=None, node_id=None, limit=50, offset=0, group_id=None,
                       ungrouped=False, recursive=False):
        self.calls.append(("options", group_id, ungrouped, recursive, enabled, limit, offset))
        key = "ungrouped" if ungrouped else group_id
        rows = [{"enabled": True, "has_ptz": False, "profiles": ["main"], "status": "RECORDING", "node_id": None,
                 "group_id": None if ungrouped else group_id, "group_path": None, **c}
                for c in self.cameras_by_group.get(key, [] if key is not None else
                                                   [c for v in self.cameras_by_group.values() for c in v])]
        return [Row(**r) for r in rows[offset:offset + limit]], len(rows)

    def group_search(self, q, limit=20, offset=0):
        self.calls.append(("search", q, limit))
        rows = [g for v in self.groups_by_parent.values() for g in v if q.lower() in g["name"].lower()]
        return [Row(**g) for g in rows[:limit]], len(rows)

    def group(self, group_id):
        g = next(g for v in self.groups_by_parent.values() for g in v if g["id"] == group_id)
        return Row(**g, breadcrumb=[])

    def create_group(self, name, description=None, parent_id=None):
        self.calls.append(("create", name, description, parent_id))
        return Row(**group(99, name, parent_id))

    def update_group(self, group_id, body):
        self.calls.append(("update", group_id, body))
        return Row(**{**group(group_id, body.get("name", "x")), "path_label": "J › x"})

    def delete_group(self, group_id, move_children=False):
        self.calls.append(("delete", group_id, move_children))

    def assign_cameras(self, camera_ids, group_id):
        self.calls.append(("assign", sorted(camera_ids), group_id))
        return len(camera_ids)


class Prefs(QObject):
    pollSecondsChanged = Signal()
    pollSeconds = 5

    def __init__(self):
        super().__init__()
        self.saved: dict[str, str] = {}
        self.scope = None

    def live_layout(self):
        return 4, [None] * 16

    def save_live_layout(self, layout, tiles):
        pass

    def live_scope(self):
        return self.scope

    def save_live_scope(self, scope):
        self.scope = scope

    def group_tree_expanded(self, key):
        return self.saved.get(key, "")

    def save_group_tree_expanded(self, key, raw):
        self.saved[key] = raw


class Ctx(QObject):
    centralChanged = Signal()

    def __init__(self, api):
        super().__init__()
        self.central = api
        self.prefs = Prefs()
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.toasts = SimpleNamespace(error=self.errors.append, success=lambda m: None, info=self.infos.append)


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

    def act(self, fn, success=None, after=None, on_error=None):
        try:
            result = fn()
        except Exception as exc:
            self.ctx.toasts.error(str(exc))
            if on_error:
                on_error(exc)
            return
        if after:
            after(result)

    monkeypatch.setattr(BaseStore, "fetch", fetch)
    monkeypatch.setattr(BaseStore, "act", act)
    monkeypatch.setattr("app.core.poller.Poller.start", lambda self, immediately=True: self._refresh() if immediately else None)
    api = FakeApi()
    return api, Ctx(api)


def keys(store):
    return [r["key"] for r in store.listModel.items()]


# ---------------------------------------------------------------- pure helpers + model
def test_tree_helpers():
    assert tree.path_ids("/3/17/42/") == [3, 17, 42] and tree.reveal_keys("/3/17/42/") == ["3", "17"]
    assert tree.is_in_subtree("/3/17/", "/3/") and not tree.is_in_subtree("/31/", "/3/")
    assert tree.count_label({"online_total": 2, "cameras_total": 3}, "online") == "2/3"
    assert tree.count_label({"online_total": 0, "cameras_total": 0}, "online") == ""
    assert tree.parse_expanded('["1","ungrouped",3]') == ["1", "ungrouped"] and tree.parse_expanded("{bad") == []
    assert tree.toggle_key(["1"], "1") == [] and tree.add_keys(["1"], ["1", "2"]) == ["1", "2"]


def test_sync_items_inserts_and_removes_in_place():
    model = DictListModel(["key", "v"], key="key")
    model.set_items([{"key": k, "v": 0} for k in "abc"])
    events = []
    model.rowsInserted.connect(lambda _p, first, last: events.append(("ins", first, last)))
    model.rowsRemoved.connect(lambda _p, first, last: events.append(("rm", first, last)))
    model.modelReset.connect(lambda: events.append("reset"))
    model.sync_items([{"key": k, "v": 1 if k == "c" else 0} for k in "abxyc"])
    assert [r["key"] for r in model.items()] == list("abxyc") and model.items()[-1]["v"] == 1
    assert events == [("ins", 2, 3)]  # no reset: the list keeps its scroll position
    model.sync_items([{"key": k, "v": 0} for k in "ac"])
    assert [r["key"] for r in model.items()] == ["a", "c"] and "reset" not in events


# ---------------------------------------------------------------- the lazy tree
def test_tree_loads_one_level_per_expand(sync):
    api, ctx = sync
    t = LiveGroupsStore(ctx)
    t.refresh()
    assert keys(t) == ["g:1", "g:2", "u"] and [c[0:2] for c in api.calls] == [("groups", None)]
    first = t.listModel.items()[0]
    assert first["expandable"] and first["countLabel"] == "2/3" and not t.listModel.items()[1]["expandable"]
    t.toggle("1")
    assert keys(t) == ["g:1", "g:3", "g:4", "c:1:10", "g:2", "u"]
    assert [r["depth"] for r in t.listModel.items()][:4] == [0, 1, 1, 1]
    t.toggle("3")
    assert keys(t)[2:5] == ["c:3:11", "c:3:12", "g:4"]
    assert json.loads(ctx.prefs.saved["live"]) == ["1", "3"]  # remembered
    t.toggle("1")  # collapse: children hidden, cache kept
    assert keys(t) == ["g:1", "g:2", "u"]
    n = len(api.calls)
    t.refresh()  # only what is on screen polls
    assert [c[:2] for c in api.calls[n:]] == [("groups", None)]


def test_manage_tree_has_no_cameras_and_ungrouped_is_a_leaf(sync):
    api, ctx = sync
    t = ManageGroupsStore(ctx)
    t.refresh()
    t.toggle("1")
    assert keys(t) == ["g:1", "g:3", "g:4", "g:2", "u"]
    assert not t.listModel.items()[1]["expandable"]  # Bijbehara has cameras but no sub-groups
    assert not any(c[0] == "options" for c in api.calls)


def test_ungrouped_cameras_load_more(sync):
    api, ctx = sync
    t = LiveGroupsStore(ctx)
    t.refresh()
    t.toggle("ungrouped")
    rows = t.listModel.items()
    assert sum(r["kind"] == "camera" for r in rows) == 50 and rows[-1]["name"] == "More cameras (50 of 60)"
    t.loadMore(rows[-1]["listKey"])
    assert sum(r["kind"] == "camera" for r in t.listModel.items()) == 60 and t.listModel.items()[-1]["kind"] == "camera"
    t.refresh()  # a poll reloads what is shown (60 rows)
    assert api.calls[-1][-2:] == (60, 0)


def test_deleted_group_is_forgotten_and_newest_answer_wins(sync, monkeypatch):
    api, ctx = sync
    ctx.prefs.saved["live"] = '["1"]'
    t = LiveGroupsStore(ctx)
    t.refresh()
    assert "g:3" in keys(t)
    api.missing.add(1)
    t.refresh()
    assert keys(t) == ["g:1", "g:2", "u"] and json.loads(ctx.prefs.saved["live"]) == []
    api.missing.clear()
    pending = []
    monkeypatch.setattr(BaseStore, "fetch", lambda self, name, fn, on_ok, **kw: pending.append((fn, on_ok)))
    t.invalidate()
    t._pending.clear()
    t.refresh()  # a second reload of the top level while the first is still out
    (fn1, ok1), (fn2, ok2) = pending[-2:]
    api.groups_by_parent[None] = [group(2, "Jammu")]
    ok2(fn2())
    ok1(([{**group(5, "Old")}], 1))  # the older answer arrives last: ignored
    assert keys(t) == ["g:2", "u"]


def test_tree_search_and_reveal(sync):
    api, ctx = sync
    t = LiveGroupsStore(ctx)
    t.refresh()
    t.setSearch("gam")
    t._apply_search()
    assert t.searchTotal == 1 and t.searchModel.items()[0]["name"] == "Pahalgam"
    t.reveal("/1/4/", True)
    assert "g:4" in keys(t) and json.loads(ctx.prefs.saved["live"]) == ["1", "4"]
    t.resetSearch()
    assert t.query == "" and t.searchModel.count == 0


# ---------------------------------------------------------------- live: play group
def test_live_play_group_pages_inside_the_group(sync):
    api, ctx = sync
    cameras = cam.CamerasStore(ctx)
    nodes = SimpleNamespace(access=lambda node_id: "lan")
    api.cameras = lambda **kw: ([], 0)
    api.cameras_by_ids = lambda ids: []
    api.live = lambda cid, access: Row(camera_id=cid, streams=[])
    api.cameras_by_group[3] = [{"id": 30 + i, "name": f"Site cam {i}"} for i in range(6)]
    s = live.LiveStore(ctx, cameras, nodes)
    s.playGroup(3, "Bijbehara")
    assert s.scopeId == 3 and s.scopeName == "Bijbehara" and s.tiles == [30, 31, 32, 33]
    assert api.calls[-1][1:4] == (3, False, True) and ctx.prefs.scope == {"groupId": 3, "name": "Bijbehara"}
    s._grid_total = 6
    s.nextGridPage()
    assert s.gridPage == 2 and s.tiles[:2] == [34, 35] and api.calls[-1][-1] == 4
    s.playGroup(2, "Jammu")  # empty group: nothing changes
    assert s.scopeId == 3 and ctx.infos[-1] == "No enabled cameras in Jammu"
    api.missing.add(3)
    api.camera_options = lambda **kw: (_ for _ in ()).throw(ApiError(404, "Group not found"))
    s.refresh()  # the played group was deleted
    assert s.scopeId == 0 and ctx.prefs.scope is None and "no longer exists" in ctx.infos[-1]


# ---------------------------------------------------------------- the Groups page
def test_groups_store_selection_actions_and_tree_refresh(sync):
    api, ctx = sync
    t = ManageGroupsStore(ctx)
    t.refresh()
    g = GroupsStore(ctx, [t])
    g.selectGroup(3)
    assert g.kind == "group" and g.detail["name"] == "Bijbehara"
    assert [r["name"] for r in g.groupCameras.rows] == ["Gate", "Bus"]
    g.groupCameras.toggleSelected(11)
    g.groupCameras.togglePage()
    assert g.groupCameras.selectedCount == 2 and g.groupCameras.pageAllSelected
    n = len(api.calls)
    g.moveSelectedCameras(0)  # remove from group
    assert ("assign", [11, 12], None) in api.calls[n:] and g.groupCameras.selectedCount == 0
    assert any(c[:2] == ("groups", None) for c in api.calls[n:])  # trees reload
    saved = []
    g.saved.connect(saved.append)
    g.createGroup(1, " Kokernag ", "")
    assert ("create", "Kokernag", None, 1) in api.calls and saved == [99]
    g.moveGroup(4, 0)
    assert ("update", 4, {"parent_id": None}) in api.calls
    g.deleteGroup(3, 1, True)
    assert ("delete", 3, True) in api.calls and g.groupId == 1  # the parent is shown
    failed = []
    g.failed.connect(lambda: failed.append(1))
    api.delete_group = lambda *a: (_ for _ in ()).throw(ApiError(409, "Group is not empty"))
    g.deleteGroup(1, 0, False)
    assert failed and ctx.errors[-1] == "Group is not empty"


def test_add_cameras_picker_keeps_selection_across_pages(sync):
    api, ctx = sync
    g = GroupsStore(ctx)
    p = g.addPicker
    p.start(3)
    assert p.onlyUngrouped and p.total == 60 and len(p.rows) == 25
    p.togglePage()
    p.next()
    p.toggleSelected(p.rows[0]["id"])
    assert p.selectedCount == 26 and p.page == 2
    p.setOnlyUngrouped(False)
    assert api.calls[-1][2] is False and p.selectedCount == 26
    g.addPickedCameras()
    assert api.calls[-1][0] == "assign" and len(api.calls[-1][1]) == 26 and api.calls[-1][2] == 3
    assert p.selectedCount == 0


# ---------------------------------------------------------------- camera form + cameras filter + API
def test_camera_form_and_filter_send_the_group():
    form = {"name": "Gate", "streams": [], "group_id": 7, "retention_days": "7"}
    assert forms.create_body(form)["group_id"] == 7
    assert forms.update_body({**form, "group_id": 0})["group_id"] is None  # taken out of its group
    assert "group_id" not in forms.update_body({"name": "Gate", "retention_days": "7"})


def test_cameras_store_group_filter(sync):
    api, ctx = sync
    seen = []
    api.cameras = lambda **kw: (seen.append(kw), ([], 0))[1]
    s = cam.CamerasStore(ctx)
    s.setGroupFilter(5)
    assert seen[-1]["group_id"] == 5 and seen[-1]["recursive"] is True
    s.setFilter("ungrouped")
    assert seen[-1]["ungrouped"] is True and "group_id" not in seen[-1]


def test_api_group_params(monkeypatch):
    from app.core.api.central import CentralApi

    api = CentralApi("http://central")
    sent = []

    def request(method, path, **kw):
        sent.append((method, path, kw))
        if path.endswith("/assign"):
            return {"updated": 2}
        return {"items": [], "total": 0, "limit": 50, "offset": 0} if method == "GET" else group(1, "A")

    monkeypatch.setattr(api, "_request", request)
    api.camera_options(group_id=3, recursive=True)
    assert sent[-1][2]["params"] == {"limit": 50, "offset": 0, "group_id": 3, "recursive": True}
    api.camera_options(ungrouped=True)
    assert sent[-1][2]["params"]["ungrouped"] is True and "group_id" not in sent[-1][2]["params"]
    api.groups()
    assert "parent_id" not in sent[-1][2]["params"]
    api.update_group(4, {"parent_id": None})
    assert sent[-1][2]["json"] == {"parent_id": None}  # explicit null = move to the top level
    api.delete_group(4, True)
    assert sent[-1][2]["params"] == {"move_children": "parent"}
    assert api.assign_cameras([2, 1, 2], None) == 2 and sent[-1][2]["json"] == {"camera_ids": [1, 2], "group_id": None}
    api.close()


def test_tree_store_subclasses_have_distinct_settings():
    assert LiveGroupsStore.__mro__[1] is GroupTreeStore and ManageGroupsStore.__mro__[1] is GroupTreeStore
