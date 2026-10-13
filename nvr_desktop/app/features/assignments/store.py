"""AssignmentsStore: which media node records each camera; move, history, run scheduler."""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from app.core.context import AppContext
from app.core.list_model import DictListModel
from app.core.poller import Poller
from app.core.store import BaseStore

ASSIGNMENT_ROLES = ["camera_id", "camera_name", "node_id", "node_name", "generation", "lease_expires_at",
                    "reason", "updated_at"]


class AssignmentsStore(BaseStore):
    historyChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.model = DictListModel(ASSIGNMENT_ROLES, key="camera_id", parent=self)
        self._history: list[dict] = []
        self._history_camera = 0
        self._poller = Poller(self.refresh, ctx.prefs.pollSeconds, self)
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
        ctx.centralChanged.connect(self.refresh)
        self._poller.start()

    @Slot()
    def refresh(self) -> None:
        self.fetch("assignments", lambda: [a.to_qml() for a in self.api.assignments()], self.model.set_items)

    listModel = Property(QObject, lambda self: self.model, constant=True)

    # ------------------------------------------------------------------ history
    @Slot(int)
    def loadHistory(self, camera_id: int) -> None:
        self._history_camera, self._history = camera_id, []
        self.historyChanged.emit()

        def apply(rows):
            if camera_id == self._history_camera:
                self._history = rows
                self.historyChanged.emit()

        self.fetch("history", lambda: [h.to_qml() for h in self.api.assignment_history(camera_id)], apply,
                   track_error=False)

    history = Property("QVariantList", lambda self: self._history, notify=historyChanged)

    # ------------------------------------------------------------------ actions
    @Slot(int, int)
    def move(self, camera_id: int, node_id: int) -> None:
        self.act(lambda: self.api.move_camera(camera_id, node_id).to_qml(),
                 success=lambda a: f"{a['camera_name']} moved to {a['node_name']}", after=lambda _a: self.refresh())

    @Slot()
    def runScheduler(self) -> None:
        self.act(self.api.run_scheduler, success="Scheduler cycle finished", after=lambda _r: self.refresh())
