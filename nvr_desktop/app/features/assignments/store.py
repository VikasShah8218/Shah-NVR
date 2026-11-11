"""AssignmentsStore: which media node records each camera (one page at a time, searchable by camera name);
move, history (latest 50 moves), run scheduler."""

from __future__ import annotations

from PySide6.QtCore import Property, Signal, Slot

from app.core.context import AppContext
from app.core.auth.permissions import Perm
from app.core.paged_store import PagedStore

ASSIGNMENT_ROLES = ["camera_id", "camera_name", "node_id", "node_name", "generation", "lease_expires_at",
                    "reason", "updated_at"]


HISTORY_LIMIT = 50


class AssignmentsStore(PagedStore):
    PERMS = (Perm.ASSIGNMENTS,)
    historyChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, ASSIGNMENT_ROLES, key="camera_id", poll_seconds=ctx.prefs.pollSeconds, parent=parent)
        self._history: list[dict] = []
        self._history_camera = 0
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
        ctx.centralChanged.connect(self.refresh)
        self.start_polling()

    def _load(self, limit: int, offset: int):
        rows, total = self.api.assignments(q=self._query, limit=limit, offset=offset)
        return [a.to_qml() for a in rows], total

    # ------------------------------------------------------------------ history
    @Slot(int)
    def loadHistory(self, camera_id: int) -> None:
        self._history_camera, self._history = camera_id, []
        self.historyChanged.emit()

        def apply(rows):
            if camera_id == self._history_camera:
                self._history = rows
                self.historyChanged.emit()

        self.fetch("history", lambda: [h.to_qml() for h in self.api.assignment_history(camera_id, HISTORY_LIMIT)[0]],
                   apply, track_error=False)

    history = Property("QVariantList", lambda self: self._history, notify=historyChanged)

    # ------------------------------------------------------------------ actions
    @Slot(int, int)
    def move(self, camera_id: int, node_id: int) -> None:
        self.act(lambda: self.api.move_camera(camera_id, node_id).to_qml(),
                 success=lambda a: f"{a['camera_name']} moved to {a['node_name']}", after=lambda _a: self.refresh())

    @Slot()
    def runScheduler(self) -> None:
        self.act(self.api.run_scheduler, success="Scheduler cycle finished", after=lambda _r: self.refresh())
