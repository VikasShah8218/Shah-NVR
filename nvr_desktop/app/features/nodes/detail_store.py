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

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
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
        self._poller = Poller(self.refresh, 3, self)

    # ------------------------------------------------------------------ selection
    def _set_node_id(self, value: int) -> None:
        if value == self._node_id:
            return
        self._node_id = value
        self._node, self._status, self._tab_data, self._logs = {}, {}, [], []
        self._set_loading(True)
        self._set_error("")
        self.nodeIdChanged.emit()
        self.nodeChanged.emit()
        self.statusChanged.emit()
        self.tabDataChanged.emit()
        self.logsChanged.emit()
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
        api_url = self._node.get("api_url")
        if api_url:
            self.fetch("status", lambda: node_api.status(api_url).to_qml(),
                       lambda s: self._apply_status(nid, s, ""), track_error=False)
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

    def _apply_status(self, nid: int, status: dict, error: str) -> None:
        if nid == self._node_id:
            self._status, self._status_error = status, error
            self.statusChanged.emit()

    def _refresh_tab(self) -> None:
        nid, api_url, tab = self._node_id, self._node.get("api_url"), self._active_tab
        if not nid or not api_url:
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
            run_task(lambda: node_api.assignments(api_url), ok, fail)
        elif tab == "paths":
            run_task(lambda: [_path_row(p) for p in node_api.mediamtx_paths(api_url)], ok, fail)
        elif tab == "chunks":
            run_task(lambda: [s.to_qml() for s in node_api.segments(api_url, 100)], ok, fail)
        elif tab == "logs" and not self._logs_paused:
            source = self._log_source
            run_task(lambda: node_api.logs(api_url, source), lambda lines: self._apply_logs(nid, source, lines), fail)

    def _apply_logs(self, nid: int, source: str, lines: list[str]) -> None:
        if nid == self._node_id and source == self._log_source:
            self._logs = [{"text": line, "level": log_level(line)} for line in lines]
            self._tab_error = ""
            self.logsChanged.emit()

    @Slot("QVariant")
    def download(self, chunk) -> None:
        """chunk: a row of the Recorded chunks tab."""
        start = parse_iso(chunk["start_time"]).astimezone()
        download_chunk(self.ctx.toasts, self._node.get("api_url", ""), chunk["id"], chunk["camera_id"],
                       chunk["profile"], start)

    node = Property("QVariant", lambda self: self._node, notify=nodeChanged)
    history = Property("QVariantList", lambda self: list(_history.get(self._node_id, [])), notify=nodeChanged)
    status = Property("QVariant", lambda self: self._status, notify=statusChanged)
    statusError = Property(str, lambda self: self._status_error, notify=statusChanged)
    tabData = Property("QVariantList", lambda self: self._tab_data, notify=tabDataChanged)
    tabError = Property(str, lambda self: self._tab_error, notify=tabDataChanged)
    logs = Property("QVariantList", lambda self: self._logs, notify=logsChanged)


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
