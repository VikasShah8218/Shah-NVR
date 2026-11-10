"""PtzWs: low-latency PTZ control over a direct WebSocket to the media node.

Mirrors the web client's ptzSocket: central mints a session ticket (over REST, holding the
camera credentials node-side), then this store opens one QWebSocket straight to the node and
exchanges JSON frames. Holding a button sends `move`/`focus` and re-sends it every KEEPALIVE_MS
(the node watchdog auto-stops if the keepalives stop); release/close sends the matching stop.
Pan/tilt speed is chosen by the node from the live zoom and pushed back as `pose` telemetry.

The legacy REST PtzStore stays as a fallback; this is the control path used in the big view.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Property, QTimer, QUrl, Signal, Slot
from PySide6.QtWebSockets import QWebSocket

from app.core.context import AppContext
from app.core.store import BaseStore
from app.core.tasks import run_task
from app.features.cameras.store import CamerasStore
from app.features.nodes.store import NodesStore

KEEPALIVE_MS = 300
MAX_RECONNECTS = 4
SPEED_MAX = 0.5  # mirrors node ptz_ws.SPEED_MAX, for the speed-meter scale only


def _sign(value: float) -> int:
    return 1 if value > 0 else (-1 if value < 0 else 0)


class PtzWsStore(BaseStore):
    changed = Signal()

    def __init__(self, ctx: AppContext, cameras: CamerasStore, nodes: NodesStore, parent=None):
        super().__init__(ctx, parent)
        self._cameras, self._nodes = cameras, nodes
        self._camera_id = 0
        self._profile = "main"
        self._phase = "idle"        # idle | connecting | reconnecting | ready | error
        self._caps: dict = {}
        self._status: dict = {}
        self._warnings: list = []
        self._speed = SPEED_MAX
        self._zoom_pct = -1         # -1 = unknown
        self._ptz_error = ""
        self._ws: QWebSocket | None = None
        self._connected = False
        self._held: dict | None = None
        self._held_stop: str | None = None
        self._generation = 0        # guards stale ticket/socket callbacks across open/close/reconnect
        self._attempts = 0
        self._keepalive = QTimer(self)
        self._keepalive.setInterval(KEEPALIVE_MS)
        self._keepalive.timeout.connect(self._resend)
        ctx.centralChanged.connect(self.close)

    # ------------------------------------------------------------------ lifecycle
    @Slot(int, str)
    def open(self, camera_id: int, profile: str) -> None:
        self.close()
        self._camera_id, self._profile = camera_id, profile or "main"
        self._attempts = 0
        self._connect()

    def _connect(self) -> None:
        self._discard_socket()
        self._generation += 1
        generation = self._generation
        self._phase = "reconnecting" if self._attempts else "connecting"
        self._ptz_error = ""
        self.changed.emit()
        camera = self._cameras.byId(self._camera_id) or {}
        node_id = (camera.get("assignment") or {}).get("node_id")
        access = self._nodes.access(node_id) if node_id else "lan"
        api, cid, profile = self.api, self._camera_id, self._profile
        run_task(lambda: api.ptz_session(cid, profile, access),
                 lambda ticket: self._on_ticket(generation, ticket),
                 lambda exc: self._fail(generation, str(exc)))

    def _on_ticket(self, generation: int, ticket: dict) -> None:
        if generation != self._generation:
            return
        self._warnings = ticket.get("warnings") or []
        ws = QWebSocket()
        ws.textMessageReceived.connect(self._on_message)
        ws.connected.connect(lambda: self._on_connected(generation))
        ws.disconnected.connect(lambda: self._on_disconnected(generation))
        self._ws = ws
        ws.open(QUrl(ticket["ws_url"]))

    def _on_connected(self, generation: int) -> None:
        if generation == self._generation:
            self._connected = True  # phase becomes "ready" on the node's ready frame

    def _on_disconnected(self, generation: int) -> None:
        if generation != self._generation:
            return  # superseded by close()/open()
        self._connected = False
        self._keepalive.stop()
        self._held = None
        if self._attempts >= MAX_RECONNECTS:
            self._phase, self._ptz_error = "error", "PTZ connection lost. Close and reopen to retry."
            self.changed.emit()
            return
        self._attempts += 1
        self._phase = "reconnecting"
        self.changed.emit()
        QTimer.singleShot(1000, lambda: self._connect() if generation == self._generation else None)

    def _fail(self, generation: int, message: str) -> None:
        if generation == self._generation:
            self._phase, self._ptz_error = "error", message
            self.changed.emit()

    @Slot()
    def close(self) -> None:
        self._generation += 1  # ignore any in-flight ticket/socket callbacks
        self._keepalive.stop()
        self._held = self._held_stop = None
        self._connected = False
        if self._ws is not None:
            try:
                self._ws.sendTextMessage('{"t":"stop"}')
                self._ws.sendTextMessage('{"t":"focus_stop"}')
            except Exception:
                pass
        self._discard_socket()
        self._phase, self._attempts = "idle", 0
        self._caps, self._status, self._warnings = {}, {}, []
        self._speed, self._zoom_pct, self._ptz_error = SPEED_MAX, -1, ""
        self.changed.emit()

    def _discard_socket(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws.deleteLater()
            self._ws = None

    # ------------------------------------------------------------------ messages
    def _on_message(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            return
        kind = msg.get("t")
        if kind == "ready":
            self._caps = msg.get("capabilities") or {}
            self._status = msg.get("status") or {}
            self._apply_telemetry(msg)
            self._attempts = 0
            self._phase = "ready"
            self.changed.emit()
        elif kind in ("pose", "status"):
            if msg.get("status") is not None:
                self._status = msg["status"]
            self._apply_telemetry(msg)
            self.changed.emit()
        elif kind == "error":
            self._ptz_error = msg.get("message", "PTZ error")
            self.changed.emit()
        # "stopped" acknowledgements need no action.

    def _apply_telemetry(self, msg: dict) -> None:
        if "speed" in msg:
            self._speed = msg["speed"]
        if "zoom_pct" in msg:
            self._zoom_pct = -1 if msg["zoom_pct"] is None else int(msg["zoom_pct"])

    def _send(self, text: str) -> None:
        if self._ws is not None and self._connected:
            self._ws.sendTextMessage(text)

    def _begin(self, move: dict, stop: str) -> None:
        if self._phase != "ready":
            return
        self._held, self._held_stop = move, stop
        self._send(json.dumps(move))
        self._keepalive.start()

    def _resend(self) -> None:
        if self._held is not None:
            self._send(json.dumps(self._held))

    # ------------------------------------------------------------------ QML slots
    @Slot(float, float, float)
    def hold(self, pan: float, tilt: float, zoom: float) -> None:
        self._begin({"t": "move", "pan": _sign(pan), "tilt": _sign(tilt), "zoom": _sign(zoom)}, '{"t":"stop"}')

    @Slot(int)
    def holdFocus(self, direction: int) -> None:
        self._begin({"t": "focus", "dir": _sign(direction)}, '{"t":"focus_stop"}')

    @Slot()
    def release(self) -> None:
        self._keepalive.stop()
        stop, self._held, self._held_stop = self._held_stop, None, None
        if stop:
            self._send(stop)

    @Slot()
    def stop(self) -> None:
        self._keepalive.stop()
        self._held = self._held_stop = None
        self._send('{"t":"stop"}')
        self._send('{"t":"focus_stop"}')

    @Slot()
    def refresh(self) -> None:
        self._send('{"t":"refresh"}')

    # ------------------------------------------------------------------ properties
    phase = Property(str, lambda self: self._phase, notify=changed)
    ready = Property(bool, lambda self: self._phase == "ready", notify=changed)
    caps = Property("QVariant", lambda self: self._caps, notify=changed)
    status = Property("QVariant", lambda self: self._status, notify=changed)
    warnings = Property("QVariantList", lambda self: self._warnings, notify=changed)
    speed = Property(float, lambda self: self._speed, notify=changed)
    zoomPct = Property(int, lambda self: self._zoom_pct, notify=changed)
    error = Property(str, lambda self: self._ptz_error, notify=changed)
