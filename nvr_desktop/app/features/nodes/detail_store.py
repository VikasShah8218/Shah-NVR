"""NodeDetailStore: one media node's page.

* From central (every 3 s): node state, metrics and resources; a rolling history for the charts.
* Straight from the node's own API: agent status, its cameras, MediaMTX paths, recorded chunks, logs.
  Only the active tab is polled (`activeTab`), like the web client.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Property, Signal, Slot

from app.core.api import node as node_api
from app.core.context import AppContext
from app.core.downloads import download_chunk
from app.core.format import parse_iso
from app.core.poller import Poller
from app.core.store import BaseStore
from app.core.tasks import run_task
from app.features.nodes.resources import node_resources
from app.features.nodes.store import NodesStore
from app.features.cameras.store import CamerasStore

HISTORY_POINTS = 240  # ~12 minutes at 3 s
_history: dict[int, list[dict]] = {}  # kept per node across page visits (like the web client)

LOG_ERROR_WORDS = ("ERROR", "CRITICAL", "ERR ", "Traceback")
LOG_WARN_WORDS = ("WARNING", "WAR ")


def log_level(line: str) -> str:
    if any(w in line for w in LOG_ERROR_WORDS):
        return "error"
    if any(w in line for w in LOG_WARN_WORDS):
        return "warn"
    return "info"


class NodeDetailStore(BaseStore):
    nodeIdChanged = Signal()
    nodeChanged = Signal()
    statusChanged = Signal()
    tabDataChanged = Signal()
    logsChanged = Signal()
    onvifChanged = Signal()

    def __init__(self, ctx: AppContext, cameras: CamerasStore, nodes: NodesStore, parent=None):
        super().__init__(ctx, parent)
        self._cameras, self._nodes = cameras, nodes
        self._node_id = 0
        self._node: dict = {}
        self._status: dict = {}
        self._status_error = ""
        self._active_tab = "cameras"
        self._tab_data: list = []
        self._tab_error = ""
        self._log_source = "agent"
        self._logs: list[dict] = []
        self._logs_paused = False
        self._onvif: dict = {}
        self._route, self._resolved_url = "lan", ""
        self._poller = Poller(self.refresh, 3, self)
        cameras.camerasChanged.connect(self.onvifChanged)
        ctx.prefs.nodeAccessChanged.connect(self.nodeChanged)

    # ------------------------------------------------------------------ selection
    def _set_node_id(self, value: int) -> None:
        if value == self._node_id:
            return
        self._node_id = value
        self._node, self._status, self._tab_data, self._logs, self._onvif = {}, {}, [], [], {}
        self._route, self._resolved_url = "lan", ""
        self._set_loading(True)
        self._set_error("")
        self.nodeIdChanged.emit()
        self.nodeChanged.emit()
        self._refresh_tab()
        self.statusChanged.emit()
        self.tabDataChanged.emit()
        self.logsChanged.emit()
        self.onvifChanged.emit()
        if value:
            self._poller.start()
        else:
            self._poller.stop()

    def _set_active_tab(self, tab: str) -> None:
        if tab != self._active_tab:
            self._active_tab = tab
            self._tab_data, self._tab_error = [], ""
            self.tabDataChanged.emit()
            self._refresh_tab()

    def _set_log_source(self, source: str) -> None:
        if source in ("agent", "mediamtx") and source != self._log_source:
            self._log_source = source
            self._logs = []
            self.logsChanged.emit()
            self._refresh_tab()

    def _set_logs_paused(self, paused: bool) -> None:
        self._logs_paused = bool(paused)
        self.logsChanged.emit()

    nodeId = Property(int, lambda self: self._node_id, _set_node_id, notify=nodeIdChanged)
    activeTab = Property(str, lambda self: self._active_tab, _set_active_tab, notify=tabDataChanged)
    logSource = Property(str, lambda self: self._log_source, _set_log_source, notify=logsChanged)
    logsPaused = Property(bool, lambda self: self._logs_paused, _set_logs_paused, notify=logsChanged)

    # ------------------------------------------------------------------ data
    @Slot()
    def refresh(self) -> None:
        nid = self._node_id
        if not nid:
            return
        self.fetch("node", lambda: self.api.node(nid).to_qml(), lambda n: self._apply_node(nid, n))
        if self._node:
            self.fetch("status", self._load_status,
                       lambda payload: self._apply_status(nid, payload[0], "", payload[1], payload[2]), track_error=False)
        self._refresh_tab()

    def _apply_node(self, nid: int, node: dict) -> None:
        if nid != self._node_id:
            return
        node["res"] = node_resources(node)
        self._node = node
        points = _history.setdefault(nid, [])
        stamp = node.get("last_heartbeat_at")
        if not points or points[-1]["stamp"] != stamp:
            r = node["res"]
            points.append({"stamp": stamp, "t": time.time() * 1000, "cpu": r["cpuPercent"], "mem": r["memPercent"],
                           "rx": r["netRx"], "tx": r["netTx"]})
            del points[:-HISTORY_POINTS]
        self.nodeChanged.emit()
        self.fetch("status", self._load_status,
                   lambda payload: self._apply_status(nid, payload[0], "", payload[1], payload[2]), track_error=False,
                   on_err=lambda exc: self._apply_status(nid, {}, str(exc)))
        self._refresh_tab()

    def _resolved_api_url(self) -> str:
        return self.ctx.node_access.api_url(self._node, self.ctx.prefs.nodeAccess)

    def _load_status(self):
        route = self.ctx.node_access.resolve(self._node, self.ctx.prefs.nodeAccess)
        url = str(self._node.get("public_api_url") if route == "public" else self._node.get("api_url") or "")
        return node_api.status(url).to_qml(), route, url

    def _apply_status(self, nid: int, status: dict, error: str, route: str | None = None,
                      resolved_url: str | None = None) -> None:
        if nid == self._node_id:
            self._status, self._status_error = status, error
            if route:
                self._route, self._resolved_url = route, resolved_url or ""
            self.statusChanged.emit()
            self.nodeChanged.emit()

    def _refresh_tab(self) -> None:
        nid, tab = self._node_id, self._active_tab
        if not nid or not self._node:
            return

        def ok(rows):
            if nid == self._node_id and tab == self._active_tab:
                self._tab_data, self._tab_error = rows, ""
                self.tabDataChanged.emit()

        def fail(exc):
            if nid == self._node_id and tab == self._active_tab:
                self._tab_error = str(exc)
                self.tabDataChanged.emit()

        if tab == "cameras":
            run_task(lambda: node_api.assignments(self._resolved_api_url()), ok, fail)
        elif tab == "paths":
            run_task(lambda: [_path_row(p) for p in node_api.mediamtx_paths(self._resolved_api_url())], ok, fail)
        elif tab == "chunks":
            run_task(lambda: [s.to_qml() for s in node_api.segments(self._resolved_api_url(), 100)], ok, fail)
        elif tab == "logs" and not self._logs_paused:
            source = self._log_source
            run_task(lambda: node_api.logs(self._resolved_api_url(), source), lambda lines: self._apply_logs(nid, source, lines), fail)
        elif tab == "onvif":
            self.fetch("onvif-server", lambda: self.api.onvif_server(nid).to_qml(),
                       lambda value: self._apply_onvif(nid, value), track_error=False, on_err=fail)

    def _apply_onvif(self, nid: int, value: dict) -> None:
        if nid == self._node_id:
            self._onvif = value
            self.onvifChanged.emit()

    @Slot("QVariant")
    def saveConnectivity(self, body) -> None:
        nid = self._node_id
        clean = dict(body)
        for key in ("public_api_url", "public_media_host"):
            clean[key] = str(clean.get(key) or "").strip() or None
        for key in ("public_rtsp_port", "public_hls_port", "public_webrtc_port"):
            value = clean.get(key)
            clean[key] = int(value) if value not in (None, "") else None
        self.act(lambda: self.api.update_node(nid, clean).to_qml(), success="Public node address saved",
                 after=lambda _value: (self.ctx.node_access.clear(), self.refresh(), self._nodes.refresh()))

    @Slot(bool, str, str)
    def saveOnvifServer(self, enabled: bool, name: str, location: str) -> None:
        nid = self._node_id
        body = {"enabled": enabled, "discovery_name": name.strip(), "location": location.strip() or None}
        self.act(lambda: self.api.update_onvif_server(nid, body).to_qml(),
                 success="Virtual ONVIF device settings saved", after=lambda value: self._apply_onvif(nid, value))

    @Slot(int, bool)
    def setCameraExposure(self, camera_id: int, exposed: bool) -> None:
        self.act(lambda: self.api.update_camera(camera_id, {"expose_via_onvif": exposed}).to_qml(),
                 success="ONVIF exposure updated", after=lambda _value: (self._cameras.refresh(), self._refresh_tab()))

    def _apply_logs(self, nid: int, source: str, lines: list[str]) -> None:
        if nid == self._node_id and source == self._log_source:
            self._logs = [{"text": line, "level": log_level(line)} for line in lines]
            self._tab_error = ""
            self.logsChanged.emit()

    # ------------------------------------------------------------------ storage volumes (Storage tab)
    def _volume_act(self, fn, success) -> None:
        self.act(fn, success=success, after=lambda _r: self.refresh())

    @Slot(str, "QVariant")
    def addVolume(self, path: str, quota_gb) -> None:
        """quota_gb: GB, or null for "use the whole disk". The node checks the folder on its next heartbeat."""
        nid = self._node_id
        self._volume_act(lambda: self.api.add_volume(nid, path.strip(), _gb(quota_gb)).to_qml(),
                         lambda v: f"Storage added: {v['path']}")

    @Slot(int, "QVariant")
    def updateVolumeCap(self, volume_id: int, quota_gb) -> None:
        nid = self._node_id
        self._volume_act(lambda: self.api.update_volume(nid, volume_id, {"quota_gb": _gb(quota_gb)}), "Storage updated")

    @Slot(int, bool)
    def setVolumeAccepting(self, volume_id: int, accepting: bool) -> None:
        nid = self._node_id
        self._volume_act(lambda: self.api.update_volume(nid, volume_id, {"accepting": accepting}),
                         "New recordings resumed" if accepting else "New recordings stopped on this storage")

    @Slot(int, int)
    def moveVolume(self, index: int, delta: int) -> None:
        """Move the volume at `index` (fill order) up (-1) or down (+1)."""
        nid = self._node_id
        ids = [v["id"] for v in self._node.get("volumes") or []]
        target = index + delta
        if not 0 <= index < len(ids) or not 0 <= target < len(ids):
            return
        ids.insert(target, ids.pop(index))
        self._volume_act(lambda: self.api.reorder_volumes(nid, ids), "Fill order saved")

    @Slot(int, bool)
    def removeVolume(self, volume_id: int, force: bool) -> None:
        nid = self._node_id
        self._volume_act(lambda: self.api.delete_volume(nid, volume_id, force), "Storage removed")

    @Slot("QVariant")
    def download(self, chunk) -> None:
        """chunk: a row of the Recorded chunks tab."""
        start = parse_iso(chunk["start_time"]).astimezone()
        download_chunk(self.ctx.toasts, self._resolved_api_url(), chunk["id"], chunk["camera_id"],
                       chunk["profile"], start)

    node = Property("QVariant", lambda self: self._node, notify=nodeChanged)
    history = Property("QVariantList", lambda self: list(_history.get(self._node_id, [])), notify=nodeChanged)
    status = Property("QVariant", lambda self: self._status, notify=statusChanged)
    statusError = Property(str, lambda self: self._status_error, notify=statusChanged)
    tabData = Property("QVariantList", lambda self: self._tab_data, notify=tabDataChanged)
    tabError = Property(str, lambda self: self._tab_error, notify=tabDataChanged)
    logs = Property("QVariantList", lambda self: self._logs, notify=logsChanged)
    onvif = Property("QVariant", lambda self: self._onvif, notify=onvifChanged)
    assignedCameras = Property("QVariantList", lambda self: [c for c in self._cameras.cameras()
                                                              if (c.get("assignment") or {}).get("node_id") == self._node_id],
                               notify=onvifChanged)
    route = Property(str, lambda self: self._route, notify=nodeChanged)
    resolvedApiUrl = Property(str, lambda self: self._resolved_url or self._node.get("api_url", ""), notify=nodeChanged)


def _path_row(path: dict) -> dict:
    tracks = path.get("tracks") or []
    return {
        "name": path.get("name"),
        "ready": bool(path.get("ready")),
        "readyTime": path.get("readyTime"),
        "tracks": ", ".join(t if isinstance(t, str) else str(t.get("codec", "")) for t in tracks) or "—",
        "readers": len(path.get("readers") or []),
        "bytesReceived": path.get("bytesReceived") or 0,
        "bytesSent": path.get("bytesSent") or 0,
    }


def _gb(value) -> float | None:
    """QML number/null -> GB for the API (None = whole disk)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
