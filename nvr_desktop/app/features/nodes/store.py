"""NodesStore: media node list with computed resources and cluster totals, plus node actions
(edit limits, drain / cordon / activate, delete). Used by the Media Nodes page and the Dashboard.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from app.core.context import AppContext
from app.core.list_model import DictListModel
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.nodes.resources import cluster_totals, node_resources

GB = 1024**3
NODE_ROLES = [
    "id", "name", "api_url", "media_host", "state", "capacity_cameras", "storage_quota_bytes", "version",
    "mediamtx_version", "last_heartbeat_at", "assigned_cameras", "metrics", "res",
]


class NodesStore(BaseStore):
    nodesChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.model = DictListModel(NODE_ROLES, parent=self)
        self._nodes: list[dict] = []
        self._totals: dict = cluster_totals([])
        self._poller = Poller(self.refresh, ctx.prefs.pollSeconds, self)
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
        ctx.centralChanged.connect(self.refresh)
        self._poller.start()

    @Slot()
    def refresh(self) -> None:
        self.fetch("nodes", lambda: [n.to_qml() for n in self.api.nodes()], self._apply)

    def _apply(self, nodes: list[dict]) -> None:
        for n in nodes:
            n["res"] = node_resources(n)
        self._nodes = nodes
        self._totals = cluster_totals(nodes)
        self.model.set_items(nodes)
        self.nodesChanged.emit()

    def nodes(self) -> list[dict]:
        return self._nodes

    def api_url(self, node_id: int) -> str | None:
        return next((n["api_url"] for n in self._nodes if n["id"] == node_id), None)

    @Slot(int, result="QVariant")
    def byId(self, node_id: int):
        return next((n for n in self._nodes if n["id"] == node_id), None)

    all = Property("QVariantList", lambda self: self._nodes, notify=nodesChanged)
    totals = Property("QVariant", lambda self: self._totals, notify=nodesChanged)
    listModel = Property(QObject, lambda self: self.model, constant=True)

    # ------------------------------------------------------------------ actions
    @Slot(int, int)
    def updateLimits(self, node_id: int, capacity: int) -> None:
        """Camera capacity. (Storage caps are set per volume: NodeDetail.updateVolumeCap.)"""
        body = {"capacity_cameras": int(capacity)}
        self.act(lambda: self.api.update_node(node_id, body).to_qml(),
                 success=lambda n: f"Limits saved for {n['name']}", after=lambda _n: self.refresh())

    @Slot(int, str)
    def action(self, node_id: int, action: str) -> None:
        self.act(lambda: self.api.node_action(node_id, action).to_qml(),
                 success=lambda n: f"{n['name']} is now {n['state']}", after=lambda _n: self.refresh())

    @Slot(int, bool)
    def remove(self, node_id: int, force: bool) -> None:
        self.act(lambda: self.api.delete_node(node_id, force), success="Node removed", after=lambda _r: self.refresh())

    @Slot(float, result=str)
    def quotaGb(self, quota_bytes: float) -> str:
        return f"{quota_bytes / GB:.2f}".rstrip("0").rstrip(".") if quota_bytes else ""
