"""DashboardStore: KPIs (from the cluster and node stores) and alerts.

Alerts = node alerts (built here from the node list: tens of nodes) on top of one page of camera alerts built by
central (GET /api/v1/cluster/alerts), so the dashboard never downloads the camera list (docs/PAGINATION_PLAN.md).
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from app.core.context import AppContext
from app.core.list_model import DictListModel
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.dashboard.alerts import build_node_alerts, camera_alert
from app.features.dashboard.cluster_store import ClusterStore
from app.features.nodes.store import NodesStore

ALERT_ROLES = ["key", "level", "title", "detail", "page", "id", "tab"]
ALERTS_PER_PAGE = 10
LEVELS = ("all", "danger", "warning")


class DashboardStore(BaseStore):
    changed = Signal()

    def __init__(self, ctx: AppContext, cluster: ClusterStore, nodes: NodesStore, parent=None):
        super().__init__(ctx, parent)
        self._cluster, self._nodes = cluster, nodes
        self.alerts_model = DictListModel(ALERT_ROLES, key="key", parent=self)
        self._kpis: dict = {}
        self._level = "all"
        self._page = 1
        self._cam_rows: list[dict] = []
        self._cam_total = 0
        self._cam_counts = {"danger": 0, "warning": 0}
        self._counts = {"all": 0, "danger": 0, "warning": 0}  # node + camera alerts by level
        self._seq = 0
        for signal in (cluster.changed, nodes.nodesChanged):
            signal.connect(self._recompute)
        ctx.centralChanged.connect(self.refreshAlerts)
        self._poller = Poller(self.refreshAlerts, ctx.prefs.pollSeconds, self)
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
        self._poller.start()

    # ------------------------------------------------------------------ camera alerts (paged by central)
    @Slot()
    def refreshAlerts(self) -> None:
        if not self.allowed(40):  # Perm.DASHBOARD; polls in the background, so never ask without permission
            return
        self._seq += 1
        seq, level, page = self._seq, self._level, self._page

        def load():
            rows, total, counts = self.api.alerts(level=None if level == "all" else level, limit=ALERTS_PER_PAGE,
                                                  offset=(page - 1) * ALERTS_PER_PAGE)
            return [r.to_qml() for r in rows], total, counts

        def ok(result):
            if seq != self._seq:
                return
            self._cam_rows, self._cam_total, self._cam_counts = result
            pages = max(1, -(-self._cam_total // ALERTS_PER_PAGE))
            if self._page > pages:  # fewer alerts now: show the last page
                self._page = pages
                self.refreshAlerts()
            self._recompute()

        self.fetch(f"alerts-{seq}", load, ok)

    @Slot(str)
    def setLevel(self, level: str) -> None:
        if level in LEVELS and level != self._level:
            self._level, self._page = level, 1
            self._recompute()
            self.refreshAlerts()

    @Slot(int)
    def setAlertPage(self, page: int) -> None:
        if page >= 1 and page != self._page:
            self._page = page
            self.changed.emit()
            self.refreshAlerts()

    # ------------------------------------------------------------------ rows + KPIs
    def _recompute(self) -> None:
        node_alerts = build_node_alerts(self._nodes.nodes())
        shown = [a for a in node_alerts if self._level == "all" or a["level"] == self._level]
        rows = shown + [camera_alert(a, len(shown) + i) for i, a in enumerate(self._cam_rows)]
        for i, row in enumerate(rows):
            row["key"] = i
        self.alerts_model.set_items(rows)
        node_danger = sum(1 for a in node_alerts if a["level"] == "danger")
        self._counts = {
            "all": len(node_alerts) + self._cam_counts["danger"] + self._cam_counts["warning"],
            "danger": node_danger + self._cam_counts["danger"],
            "warning": len(node_alerts) - node_danger + self._cam_counts["warning"],
        }
        totals = self._nodes.totals
        self._kpis = {
            "camerasTotal": self._cluster.camerasTotal,
            "camerasEnabled": self._cluster.camerasEnabled,
            "recording": self._cluster.recording,
            "recordStreams": self._cluster.recordStreams,
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
    alertCounts = Property("QVariant", lambda self: self._counts, notify=changed)
    level = Property(str, lambda self: self._level, notify=changed)
    alertPage = Property(int, lambda self: self._page, notify=changed)
    alertPageSize = Property(int, lambda self: ALERTS_PER_PAGE, constant=True)
    cameraAlertTotal = Property(int, lambda self: self._cam_total, notify=changed)
