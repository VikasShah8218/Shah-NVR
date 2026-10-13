"""DashboardStore: KPIs and alerts, derived from the cluster, camera and node stores (no extra requests)."""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal

from app.core.context import AppContext
from app.core.list_model import DictListModel
from app.features.cameras.store import CamerasStore
from app.features.dashboard.alerts import build_alerts
from app.features.dashboard.cluster_store import ClusterStore
from app.features.nodes.store import NodesStore

ALERT_ROLES = ["key", "level", "title", "detail", "page", "id"]


class DashboardStore(QObject):
    changed = Signal()

    def __init__(self, ctx: AppContext, cluster: ClusterStore, cameras: CamerasStore, nodes: NodesStore, parent=None):
        super().__init__(parent)
        self._cluster, self._cameras, self._nodes = cluster, cameras, nodes
        self.alerts_model = DictListModel(ALERT_ROLES, key="title", parent=self)
        self._kpis: dict = {}
        for signal in (cluster.changed, cameras.camerasChanged, nodes.nodesChanged):
            signal.connect(self._recompute)

    def _recompute(self) -> None:
        cameras, nodes = self._cameras.cameras(), self._nodes.nodes()
        self.alerts_model.set_items(build_alerts(cameras, nodes))
        record_streams = sum(1 for c in cameras if c["enabled"] for s in c["streams"] if s["record"])
        totals = self._nodes.totals
        self._kpis = {
            "camerasTotal": self._cluster.camerasTotal,
            "camerasEnabled": self._cluster.camerasEnabled,
            "recording": self._cluster.recording,
            "recordStreams": record_streams,
            "nodesHealthy": totals["healthy"],
            "nodesTotal": totals["nodes"],
            "segmentsLastHour": self._cluster.segmentsLastHour,
            "segmentsTotal": self._cluster.segmentsTotal,
            "storage": totals["recordings"],
            "ingress": totals["netRx"],
        }
        self.changed.emit()

    kpis = Property("QVariant", lambda self: self._kpis, notify=changed)
    alerts = Property(QObject, lambda self: self.alerts_model, constant=True)
