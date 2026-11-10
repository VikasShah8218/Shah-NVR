"""GroupTreeStore: the lazy camera-group tree (docs/GROUPING_PLAN.md; port of nvr_client GroupTree.tsx).

Each expanded group asks central for its own direct sub-groups (`GET /groups?parent_id=`) and, in the live tree, its
cameras (`/cameras/options?group_id=`), 50 at a time with "Load more". Collapsed groups cost nothing and are not
polled; the client never downloads the whole tree or camera list.

QML has no tree model here, so the visible tree is a FLAT list model (one row per visible group / camera / "more" /
"loading" line, with `depth` for the indent). It is updated with `DictListModel.sync_items`, so expanding a group
inserts rows in place (the ListView keeps its scroll position).

Lists are cached per "list key": `g:<parent>` (sub-groups of a group, `g:root` = top level) and `c:<parent>`
(cameras of a group, `c:ungrouped` = cameras in no group). Polling reloads only the lists that are on screen, and
only while the page using the tree is active (`setActive`).
"""

from __future__ import annotations

import json

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from app.core.api.errors import ApiError
from app.core.context import AppContext
from app.core.list_model import DictListModel
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.groups.tree import UNGROUPED, add_keys, count_label, parse_expanded, reveal_keys, toggle_key

ROOT = "root"
PAGE = 50
MAX_RELOAD = 200  # a poll reloads what is shown, up to this many rows per list
SEARCH_DEBOUNCE_MS = 300

TREE_ROLES = [
    "key", "kind", "id", "depth", "name", "expanded", "expandable", "childGroups", "camerasDirect", "camerasTotal",
    "onlineTotal", "status", "enabled", "pathLabel", "path", "listKey", "countLabel", "busy", "description", "parentId",
]
SEARCH_ROLES = ["id", "name", "pathLabel", "path", "camerasTotal", "onlineTotal", "childGroups", "countLabel"]


def _row(key: str, kind: str, depth: int, **values) -> dict:
    row = {"key": key, "kind": kind, "id": 0, "depth": depth, "name": "", "expanded": False, "expandable": False,
           "childGroups": 0, "camerasDirect": 0, "camerasTotal": 0, "onlineTotal": 0, "status": "", "enabled": True,
           "pathLabel": "", "path": "", "listKey": "", "countLabel": "", "busy": False, "description": "", "parentId": 0}
    row.update(values)
    return row


class GroupTreeStore(BaseStore):
    changed = Signal()
    searchChanged = Signal()

    def __init__(self, ctx: AppContext, *, show_cameras: bool, show_ungrouped: bool, persist_key: str | None,
                 count_mode: str = "total", search_limit: int = 20, parent=None):
        super().__init__(ctx, parent)
        self._show_cameras, self._show_ungrouped = show_cameras, show_ungrouped
        self._persist_key, self._count_mode, self._search_limit = persist_key, count_mode, search_limit
        self.model = DictListModel(TREE_ROLES, key="key", parent=self)
        self.search_model = DictListModel(SEARCH_ROLES, parent=self)
        self._lists: dict[str, list[dict]] = {}
        self._totals: dict[str, int] = {}
        self._errors: dict[str, str] = {}
        self._seq: dict[str, int] = {}
        self._pending: set[str] = set()
        self._more_busy: set[str] = set()
        self._generation = 0  # bumped when the server changes: every answer in flight is dropped
        self._visible_lists: list[str] = []
        self._expanded: list[str] = self._read_expanded()
        self._active = False
        self._search = ""
        self._query = ""
        self._search_total = 0
        self._search_seq = 0
        self._debounce = QTimer(self, singleShot=True, interval=SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._apply_search)
        self._poller = Poller(self.refresh, ctx.prefs.pollSeconds, self)
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
        ctx.centralChanged.connect(self._central_changed)

    # ------------------------------------------------------------------ expanded keys (remembered)
    def _read_expanded(self) -> list[str]:
        return parse_expanded(self.ctx.prefs.group_tree_expanded(self._persist_key)) if self._persist_key else []

    def _save_expanded(self) -> None:
        if self._persist_key:
            self.ctx.prefs.save_group_tree_expanded(self._persist_key, json.dumps(self._expanded))

    # ------------------------------------------------------------------ loading
    def _request(self, list_key: str, limit: int, offset: int):
        kind, parent = list_key.split(":", 1)
        if kind == "g":
            rows, total = self.api.groups(parent_id=None if parent == ROOT else int(parent), limit=limit, offset=offset)
        else:
            scope = {"ungrouped": True} if parent == UNGROUPED else {"group_id": int(parent)}
            rows, total = self.api.camera_options(limit=limit, offset=offset, **scope)
        return [r.to_qml() for r in rows], total

    def _load(self, list_key: str) -> None:
        """(Re)load one list from the top, keeping as many rows as are shown (so "Load more" survives a poll)."""
        if list_key in self._pending:
            return
        self._pending.add(list_key)
        seq = self._seq[list_key] = self._seq.get(list_key, 0) + 1
        generation = self._generation
        limit = min(MAX_RELOAD, max(PAGE, len(self._lists.get(list_key, []))))

        def current() -> bool:
            return generation == self._generation and seq == self._seq.get(list_key)

        def ok(result):
            if not current():
                return
            self._pending.discard(list_key)
            self._lists[list_key], self._totals[list_key] = result
            self._errors.pop(list_key, None)
            self._rebuild()

        def err(exc: Exception):
            if not current():
                return
            self._pending.discard(list_key)
            self._failed(list_key, exc)

        self.fetch(f"{list_key}#{generation}.{seq}", lambda: self._request(list_key, limit, 0), ok,
                   track_error=list_key == f"g:{ROOT}", on_err=err)

    def _failed(self, list_key: str, exc: Exception) -> None:
        parent = list_key.split(":", 1)[1]
        if isinstance(exc, ApiError) and exc.status == 404 and parent not in (ROOT, UNGROUPED):
            # the group was deleted elsewhere: forget it
            self._expanded = [k for k in self._expanded if k != parent]
            self._save_expanded()
            for key in (f"g:{parent}", f"c:{parent}"):
                self._lists.pop(key, None)
                self._totals.pop(key, None)
        elif list_key not in self._lists:
            self._errors[list_key] = str(exc)  # loaded lists keep their rows when a poll fails
        self._rebuild()

    @Slot(str)
    def loadMore(self, list_key: str) -> None:
        shown = self._lists.get(list_key, [])
        if list_key in self._more_busy or len(shown) >= self._totals.get(list_key, 0):
            return
        self._more_busy.add(list_key)
        seq, generation, offset = self._seq.get(list_key, 0), self._generation, len(shown)
        self._rebuild()

        def ok(result):
            self._more_busy.discard(list_key)
            if generation == self._generation and seq == self._seq.get(list_key):
                rows, total = result
                known = {r["id"] for r in self._lists.get(list_key, [])}
                self._lists[list_key] = self._lists.get(list_key, []) + [r for r in rows if r["id"] not in known]
                self._totals[list_key] = total
            self._rebuild()

        def err(exc: Exception):
            self._more_busy.discard(list_key)
            self.ctx.toasts.error(str(exc))
            self._rebuild()

        self.fetch(f"more-{list_key}-{offset}", lambda: self._request(list_key, PAGE, offset), ok,
                   track_error=False, on_err=err)

    @Slot()
    def refresh(self) -> None:
        """Reload every list on screen (the top level, expanded groups)."""
        if not self._visible_lists:
            self._rebuild()  # first time: the walk asks for the top level
            return
        for list_key in self._visible_lists:
            self._load(list_key)

    @Slot()
    def invalidate(self) -> None:
        """Something changed (group created / moved / deleted, cameras moved): forget hidden lists, reload shown ones."""
        for key in list(self._lists):
            if key not in self._visible_lists:
                self._lists.pop(key)
                self._totals.pop(key, None)
        self._errors.clear()
        self.refresh()

    def _central_changed(self) -> None:
        self._generation += 1
        self._lists.clear()
        self._totals.clear()
        self._errors.clear()
        self._pending.clear()
        self._more_busy.clear()
        self._visible_lists = []
        self._rebuild()
        if self._query:
            self._run_search()

    # ------------------------------------------------------------------ the flat rows
    def _rebuild(self) -> None:
        rows: list[dict] = []
        need: list[str] = []
        self._walk_groups(ROOT, 0, rows, need)
        if self._show_ungrouped and f"g:{ROOT}" in self._lists:
            is_open = self._show_cameras and UNGROUPED in self._expanded
            rows.append(_row("u", "ungrouped", 0, name="Ungrouped", expandable=self._show_cameras, expanded=is_open))
            if is_open:
                self._walk_cameras(UNGROUPED, 1, rows, need)
        self._visible_lists = need
        self.model.sync_items(rows)
        self.changed.emit()
        for list_key in need:
            if list_key not in self._lists and list_key not in self._errors:
                self._load(list_key)

    def _placeholder(self, list_key: str, depth: int, rows: list[dict]) -> None:
        if list_key in self._errors:
            rows.append(_row(f"err:{list_key}", "error", depth, name=self._errors[list_key], listKey=list_key))
        else:
            rows.append(_row(f"loading:{list_key}", "loading", depth, name="Loading…", listKey=list_key))

    def _more(self, list_key: str, depth: int, what: str, rows: list[dict]) -> None:
        shown, total = len(self._lists[list_key]), self._totals.get(list_key, 0)
        if shown < total:
            busy = list_key in self._more_busy
            rows.append(_row(f"more:{list_key}", "more", depth, listKey=list_key, busy=busy,
                             name="Loading…" if busy else f"More {what} ({shown} of {total})"))

    def _walk_groups(self, parent: str, depth: int, rows: list[dict], need: list[str]) -> None:
        list_key = f"g:{parent}"
        need.append(list_key)
        if list_key not in self._lists:
            self._placeholder(list_key, depth, rows)
            return
        for g in self._lists[list_key]:
            key = str(g["id"])
            has_cameras = self._show_cameras and g["cameras_direct"] > 0
            expandable = g["child_groups"] > 0 or has_cameras
            is_open = expandable and key in self._expanded
            rows.append(_row(
                f"g:{key}", "group", depth, id=g["id"], name=g["name"], expanded=is_open, expandable=expandable,
                childGroups=g["child_groups"], camerasDirect=g["cameras_direct"], camerasTotal=g["cameras_total"],
                onlineTotal=g["online_total"], pathLabel=g["path_label"], path=g["path"],
                countLabel=count_label(g, self._count_mode), description=g.get("description") or "",
                parentId=g.get("parent_id") or 0,
            ))
            if is_open:
                if g["child_groups"] > 0:
                    self._walk_groups(key, depth + 1, rows, need)
                if has_cameras:
                    self._walk_cameras(key, depth + 1, rows, need)
        self._more(list_key, depth, "groups", rows)

    def _walk_cameras(self, parent: str, depth: int, rows: list[dict], need: list[str]) -> None:
        list_key = f"c:{parent}"
        need.append(list_key)
        if list_key not in self._lists:
            self._placeholder(list_key, depth, rows)
            return
        for c in self._lists[list_key]:
            rows.append(_row(f"c:{parent}:{c['id']}", "camera", depth, id=c["id"], name=c["name"],
                             status=c.get("status", "UNKNOWN"), enabled=c.get("enabled", True),
                             pathLabel=c.get("group_path") or ""))
        if not self._lists[list_key]:
            rows.append(_row(f"empty:{list_key}", "empty", depth, name="No cameras", listKey=list_key))
        self._more(list_key, depth, "cameras", rows)

    # ------------------------------------------------------------------ expand / collapse
    def _lists_of(self, key: str) -> list[str]:
        return [f"c:{UNGROUPED}"] if key == UNGROUPED else [f"g:{key}", f"c:{key}"]

    @Slot(str)
    def toggle(self, key: str) -> None:
        """Expand / collapse a group (key = its id as text) or the Ungrouped node ("ungrouped")."""
        opening = key not in self._expanded
        self._expanded = toggle_key(self._expanded, key)
        self._save_expanded()
        self._rebuild()
        if opening:  # cached children show at once, then refresh in the background
            for list_key in self._lists_of(key):
                if list_key in self._lists:
                    self._load(list_key)

    @Slot(str)
    @Slot(str, bool)
    def reveal(self, path: str, include_self: bool = False) -> None:
        """Expand the ancestors of the group at `path` (and the group itself) so it is visible."""
        keys = reveal_keys(path)
        if include_self and path:
            keys.append(path.strip("/").split("/")[-1])
        self._expanded = add_keys(self._expanded, keys)
        self._save_expanded()
        self._rebuild()

    @Slot()
    def collapseAll(self) -> None:
        self._expanded = []
        self._save_expanded()
        self._rebuild()

    @Slot(bool)
    def setActive(self, active: bool) -> None:
        """Poll only while the page / popup showing this tree is open."""
        if active == self._active:
            return
        self._active = active
        if active:
            self._poller.start()
        else:
            self._poller.stop()

    # ------------------------------------------------------------------ search (groups by name, anywhere)
    @Slot(str)
    def setSearch(self, text: str) -> None:
        if text != self._search:
            self._search = text
            self.searchChanged.emit()
            self._debounce.start()

    @Slot()
    def resetSearch(self) -> None:
        """Clear the search at once (no debounce), e.g. when a picker opens."""
        self._debounce.stop()
        self._search = self._query = ""
        self._run_search()

    def _apply_search(self) -> None:
        query = self._search.strip()
        if query != self._query:
            self._query = query
            self.searchChanged.emit()
            self._run_search()

    def _run_search(self) -> None:
        self._search_seq += 1
        seq, query = self._search_seq, self._query
        if not query:
            self._search_total = 0
            self.search_model.set_items([])
            self.searchChanged.emit()
            return

        def load():
            rows, total = self.api.group_search(query, limit=self._search_limit)
            return [{"id": g.id, "name": g.name, "pathLabel": g.path_label, "path": g.path,
                     "camerasTotal": g.cameras_total, "onlineTotal": g.online_total, "childGroups": g.child_groups,
                     "countLabel": count_label(g.to_qml(), self._count_mode)} for g in rows], total

        def ok(result):
            if seq == self._search_seq:
                rows, self._search_total = result
                self.search_model.set_items(rows)
                self.searchChanged.emit()

        self.fetch(f"search-{seq}", load, ok, track_error=False, on_err=lambda exc: self.ctx.toasts.error(str(exc)))

    # ------------------------------------------------------------------ properties
    listModel = Property(QObject, lambda self: self.model, constant=True)
    searchModel = Property(QObject, lambda self: self.search_model, constant=True)
    searchTotal = Property(int, lambda self: self._search_total, notify=searchChanged)
    search = Property(str, lambda self: self._search, notify=searchChanged)
    query = Property(str, lambda self: self._query, notify=searchChanged)
    empty = Property(bool, lambda self: f"g:{ROOT}" in self._lists and not self._lists[f"g:{ROOT}"], notify=changed)


# One QML singleton per use (distinct types keep the QML registration simple; each keeps its own expanded state).
class LiveGroupsStore(GroupTreeStore):
    """Live View sidebar: groups and their cameras, "online/total" counts."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, show_cameras=True, show_ungrouped=True, persist_key="live",
                         count_mode="online", search_limit=8, parent=parent)


class ManageGroupsStore(GroupTreeStore):
    """Groups page tree: groups only."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, show_cameras=False, show_ungrouped=True, persist_key="manage", parent=parent)


class PickerGroupsStore(GroupTreeStore):
    """GroupPicker popups (one open at a time): groups only, nothing remembered."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, show_cameras=False, show_ungrouped=False, persist_key=None, parent=parent)
