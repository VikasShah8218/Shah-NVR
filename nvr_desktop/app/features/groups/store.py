"""GroupsStore: the Groups management page (port of nvr_client GroupsPage.tsx + GroupDialogs.tsx).

Selection: the top level ("root"), the cameras in no group ("ungrouped") or one group. For a group it shows the
detail (breadcrumb, counts), a paged sub-groups table and a paged cameras table with checkboxes (bulk move / remove).
"Add cameras" is a paged, searchable picker that keeps a selection across pages (at most 500).
Group ids in slots: 0 = none (top level / no group).
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from app.core.api.errors import ApiError
from app.core.context import AppContext
from app.core.paged_store import PagedStore
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.groups.tree import count_label

GROUP_ROLES = ["id", "name", "description", "parent_id", "depth", "path", "path_label", "child_groups",
               "cameras_direct", "cameras_total", "online_total", "countLabel"]
CAMERA_ROLES = ["id", "name", "status", "enabled", "group_id", "group_path", "selected"]
MAX_PICK = 500


def _gid(value: int) -> int | None:
    return int(value) if value and int(value) > 0 else None


class SubGroupsStore(PagedStore):
    """Sub-groups of the selected group (or the top-level groups), one page at a time."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, GROUP_ROLES, page_size=25, poll_seconds=ctx.prefs.pollSeconds, parent=parent)
        self.parent_id: int | None = None
        self.enabled = False

    def _can_load(self) -> bool:
        return self.enabled

    def _load(self, limit: int, offset: int):
        rows, total = self.api.groups(parent_id=self.parent_id, limit=limit, offset=offset)
        return [{**g.to_qml(), "countLabel": count_label(g.to_qml(), "online")} for g in rows], total


class CameraSelectStore(PagedStore):
    """A paged camera list (picker rows) with a selection that survives paging."""

    selectionChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, CAMERA_ROLES, page_size=25, poll_seconds=ctx.prefs.pollSeconds, parent=parent)
        self.scope: dict | None = None  # None = nothing to show
        self._picked: dict[int, str] = {}

    def _can_load(self) -> bool:
        return self.scope is not None

    def _load(self, limit: int, offset: int):
        rows, total = self.api.camera_options(q=self._query, limit=limit, offset=offset, **(self.scope or {}))
        return [r.to_qml() for r in rows], total

    def _apply(self, rows: list[dict], total: int) -> None:
        super()._apply([{**r, "selected": r["id"] in self._picked} for r in rows], total)

    def _selection_changed(self) -> None:
        self.model.set_items([{**r, "selected": r["id"] in self._picked} for r in self._rows])
        self._rows = self.model.items()
        self.selectionChanged.emit()

    def _selectable(self, row: dict) -> bool:
        return True

    @Slot(int)
    def toggleSelected(self, camera_id: int) -> None:
        row = next((r for r in self._rows if r["id"] == camera_id), None)
        if camera_id in self._picked:
            del self._picked[camera_id]
        elif row and self._selectable(row) and len(self._picked) < MAX_PICK:
            self._picked[camera_id] = row["name"]
        self._selection_changed()

    @Slot()
    def togglePage(self) -> None:
        rows = [r for r in self._rows if self._selectable(r)]
        if rows and all(r["id"] in self._picked for r in rows):
            for r in rows:
                self._picked.pop(r["id"], None)
        else:
            for r in rows:
                if len(self._picked) < MAX_PICK:
                    self._picked.setdefault(r["id"], r["name"])
        self._selection_changed()

    @Slot()
    def clearSelection(self) -> None:
        self._picked.clear()
        self._selection_changed()

    def picked_ids(self) -> list[int]:
        return list(self._picked)

    def _page_all_selected(self) -> bool:
        rows = [r for r in self._rows if self._selectable(r)]
        return bool(rows) and all(r["id"] in self._picked for r in rows)

    selectedCount = Property(int, lambda self: len(self._picked), notify=selectionChanged)
    pageAllSelected = Property(bool, _page_all_selected, notify=selectionChanged)
    maxPick = Property(int, lambda self: MAX_PICK, constant=True)


class AddCamerasStore(CameraSelectStore):
    """"Add cameras to <group>" dialog: ungrouped cameras by default, or all cameras."""

    modeChanged = Signal()  # own signal: a subclass Property must not notify on a base-class Signal (crash)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.target: int | None = None
        self._only_ungrouped = True

    def _selectable(self, row: dict) -> bool:
        return row.get("group_id") != self.target

    @Slot(int)
    def start(self, group_id: int) -> None:
        self.target = group_id
        self._only_ungrouped = True
        self._picked.clear()
        self._search = self._query = ""
        self.searchChanged.emit()
        self.scope = {"ungrouped": True}
        self.selectionChanged.emit()
        self.modeChanged.emit()
        self.reset()

    @Slot(bool)
    def setOnlyUngrouped(self, value: bool) -> None:
        if value != self._only_ungrouped:
            self._only_ungrouped = value
            self.scope = {"ungrouped": True} if value else {}
            self.selectionChanged.emit()
            self.modeChanged.emit()
            self.reset()

    onlyUngrouped = Property(bool, lambda self: self._only_ungrouped, notify=modeChanged)


class GroupsStore(BaseStore):
    changed = Signal()
    saved = Signal(int)  # group id after a successful create / edit / move (closes dialogs)
    deleted = Signal(int)  # parent id (0 = top level) after a delete
    failed = Signal()  # an action failed (the toast shows why): dialogs re-enable their buttons

    def __init__(self, ctx: AppContext, trees: list = (), parent=None):
        super().__init__(ctx, parent)
        self._trees = list(trees)  # tree stores to refresh after a change
        self.sub_groups = SubGroupsStore(ctx, self)
        self.cameras = CameraSelectStore(ctx, self)
        self.add_picker = AddCamerasStore(ctx, self)
        self._kind = "root"
        self._group_id = 0
        self._detail: dict = {}
        self._missing = False
        self._active = False
        self._seq = 0
        self._poller = Poller(self._load_detail, ctx.prefs.pollSeconds, self)
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
        ctx.centralChanged.connect(self.refreshAll)
        self._set_loading(False)

    # ------------------------------------------------------------------ selection
    @Slot()
    def selectRoot(self) -> None:
        self._select("root", 0)

    @Slot()
    def selectUngrouped(self) -> None:
        self._select("ungrouped", 0)

    @Slot(int)
    def selectGroup(self, group_id: int) -> None:
        if group_id > 0:
            self._select("group", group_id)
        else:
            self._select("root", 0)

    def _select(self, kind: str, group_id: int) -> None:
        if (kind, group_id) == (self._kind, self._group_id) and self._detail:
            return
        self._kind, self._group_id = kind, group_id
        self._detail, self._missing = {}, False
        self.sub_groups.parent_id = group_id or None
        self.sub_groups.enabled = kind != "ungrouped"
        self.cameras.scope = {"group_id": group_id} if kind == "group" else {"ungrouped": True} if kind == "ungrouped" else None
        self.cameras._picked.clear()
        self.cameras._search = self.cameras._query = ""
        self.cameras.searchChanged.emit()
        self.cameras.selectionChanged.emit()
        self.changed.emit()
        self.sub_groups.reset()
        self.cameras.reset()
        self._load_detail()

    def _load_detail(self) -> None:
        if self._kind != "group":
            return
        self._seq += 1
        seq, group_id = self._seq, self._group_id

        def ok(detail):
            if seq == self._seq:
                self._detail, self._missing = detail, False
                self.changed.emit()

        def err(exc):
            if seq == self._seq and isinstance(exc, ApiError) and exc.status == 404:
                self._detail, self._missing = {}, True
                self.changed.emit()

        self.fetch(f"detail-{seq}", lambda: self.api.group(group_id).to_qml(), ok, on_err=err)

    @Slot(bool)
    def setActive(self, active: bool) -> None:
        """Poll only while the Groups page is open."""
        if active == self._active:
            return
        self._active = active
        for poller in (self._poller, self.sub_groups._poller, self.cameras._poller):
            if active:
                poller.start(immediately=False)
            else:
                poller.stop()
        if active:
            self.refreshAll()

    @Slot()
    def refreshAll(self) -> None:
        self._load_detail()
        self.sub_groups.refresh()
        self.cameras.refresh()

    def _changed(self) -> None:
        self.refreshAll()
        for tree in self._trees:
            tree.invalidate()

    # ------------------------------------------------------------------ actions (group ids: 0 = none)
    @Slot(int, str, str)
    def createGroup(self, parent_id: int, name: str, description: str) -> None:
        def after(g):
            self._changed()
            self.saved.emit(g["id"])

        self.act(lambda: self.api.create_group(name.strip(), description.strip() or None, _gid(parent_id)).to_qml(),
                 success=lambda g: f'Group "{g["name"]}" created', after=after, on_error=lambda _e: self.failed.emit())

    @Slot(int, str, str)
    def updateGroup(self, group_id: int, name: str, description: str) -> None:
        body = {"name": name.strip(), "description": description.strip() or None}
        self.act(lambda: self.api.update_group(group_id, body).to_qml(), success="Group updated",
                 after=lambda g: (self._changed(), self.saved.emit(g["id"])), on_error=lambda _e: self.failed.emit())

    @Slot(int, int)
    def moveGroup(self, group_id: int, parent_id: int) -> None:
        self.act(lambda: self.api.update_group(group_id, {"parent_id": _gid(parent_id)}).to_qml(),
                 success=lambda g: f'Moved to {g["path_label"]}', after=lambda g: (self._changed(), self.saved.emit(g["id"])), on_error=lambda _e: self.failed.emit())

    @Slot(int, int, bool)
    def deleteGroup(self, group_id: int, parent_id: int, move_children: bool) -> None:
        def after(_r):
            if self._kind == "group" and self._group_id == group_id:
                self.selectGroup(parent_id)
            self._changed()
            self.deleted.emit(parent_id)

        self.act(lambda: self.api.delete_group(group_id, move_children), success="Group deleted", after=after, on_error=lambda _e: self.failed.emit())

    @Slot(int)
    def moveSelectedCameras(self, group_id: int) -> None:
        """Move the cameras ticked in the cameras table into `group_id` (0 = out of every group)."""
        ids = self.cameras.picked_ids()
        if not ids:
            return
        target = _gid(group_id)

        def after(_n):
            self.cameras.clearSelection()
            self._changed()

        self.act(lambda: self.api.assign_cameras(ids, target),
                 success=lambda n: f"{n} camera{'' if n == 1 else 's'} {'removed from group' if target is None else 'moved'}",
                 after=after, on_error=lambda _e: self.failed.emit())

    @Slot()
    def addPickedCameras(self) -> None:
        ids, target = self.add_picker.picked_ids(), self.add_picker.target
        if not ids or not target:
            return

        def after(_n):
            self.add_picker.clearSelection()
            self._changed()
            self.saved.emit(target)

        self.act(lambda: self.api.assign_cameras(ids, target),
                 success=lambda n: f"{n} camera{'' if n == 1 else 's'} added", after=after, on_error=lambda _e: self.failed.emit())

    # ------------------------------------------------------------------ properties
    kind = Property(str, lambda self: self._kind, notify=changed)
    groupId = Property(int, lambda self: self._group_id, notify=changed)
    detail = Property("QVariant", lambda self: self._detail, notify=changed)
    missing = Property(bool, lambda self: self._missing, notify=changed)
    subGroups = Property(QObject, lambda self: self.sub_groups, constant=True)
    groupCameras = Property(QObject, lambda self: self.cameras, constant=True)
    addPicker = Property(QObject, lambda self: self.add_picker, constant=True)
