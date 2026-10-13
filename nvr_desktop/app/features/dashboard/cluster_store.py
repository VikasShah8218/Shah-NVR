"""ClusterStore: cluster health for the top bar and the dashboard (polls every `Prefs.pollSeconds`)."""

from __future__ import annotations

from PySide6.QtCore import Property, Signal

from app.core.context import AppContext
from app.core.poller import Poller
from app.core.store import BaseStore


class ClusterStore(BaseStore):
    changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self._health: dict = {}
        self._online = False
        self._poller = Poller(self.refresh, ctx.prefs.pollSeconds, self)
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
        ctx.centralChanged.connect(self.refresh)
        self._poller.start()

    def refresh(self) -> None:
        self.fetch("health", lambda: self.api.cluster_health().to_qml(), self._apply)

    def _apply(self, health: dict) -> None:
        self._health = health
        self._online = True
        self.changed.emit()

    def _set_error(self, message: str) -> None:  # an error means central is unreachable
        super()._set_error(message)
        if message and self._online:
            self._online = False
            self.changed.emit()

    def _count(self, group: str, *keys: str) -> int:
        values = self._health.get(group) or {}
        return sum(values.get(k, 0) for k in keys) if keys else sum(values.values())

    online = Property(bool, lambda self: self._online, notify=changed)
    health = Property("QVariant", lambda self: self._health, notify=changed)
    nodesTotal = Property(int, lambda self: self._count("nodes_by_state"), notify=changed)
    nodesHealthy = Property(int, lambda self: self._count("nodes_by_state", "ACTIVE", "READY"), notify=changed)
    recording = Property(int, lambda self: self._count("streams_by_status", "RECORDING"), notify=changed)
    camerasEnabled = Property(int, lambda self: self._health.get("cameras_enabled", 0), notify=changed)
    camerasTotal = Property(int, lambda self: self._health.get("cameras_total", 0), notify=changed)
    segmentsLastHour = Property(int, lambda self: self._health.get("segments_last_hour", 0), notify=changed)
    segmentsTotal = Property(int, lambda self: self._health.get("segments_total", 0), notify=changed)
    streamsByStatus = Property(
        "QVariantList",
        lambda self: [{"status": k, "count": v} for k, v in
                      sorted((self._health.get("streams_by_status") or {}).items(), key=lambda kv: -kv[1])],
        notify=changed,
    )
