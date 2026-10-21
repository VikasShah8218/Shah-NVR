"""Safe single-session PTZ controller exposed to QML."""

from __future__ import annotations

from PySide6.QtCore import Property, QTimer, Signal, Slot

from app.core.api.errors import ApiError
from app.core.context import AppContext
from app.core.store import BaseStore
from app.core.tasks import run_task


class PtzStore(BaseStore):
    changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self._camera_id = 0
        self._profile = "main"
        self._state: dict = {}
        self._message = ""
        self._ptz_error = ""
        self._busy = False
        self._blocked = False
        self._held: dict | None = None
        self._sequence = 0
        self._generation = 0
        self._pulse = QTimer(self)
        self._pulse.setSingleShot(True)
        self._pulse.timeout.connect(self._send_move)
        ctx.centralChanged.connect(self.close)

    @Slot(int, str)
    def open(self, camera_id: int, profile: str) -> None:
        self.close()
        self._camera_id, self._profile = camera_id, profile or "main"
        self._busy, self._ptz_error, self._message = True, "", ""
        generation, api = self._generation, self.api
        self.changed.emit()

        def ok(state):
            if generation != self._generation:
                return
            self._state, self._busy, self._blocked = state, False, False
            self.changed.emit()

        def err(exc):
            if generation != self._generation:
                return
            self._ptz_error, self._busy, self._blocked = str(exc), False, True
            self.changed.emit()

        run_task(lambda: api.ptz_open(camera_id, self._profile).to_qml(), ok, err)

    @Slot()
    def reload(self) -> None:
        if self._camera_id:
            self.open(self._camera_id, self._profile)

    @Slot()
    def close(self) -> None:
        had_session = bool(self._state.get("session_id"))
        if had_session:
            self.stop()
        self._generation += 1
        self._pulse.stop()
        self._held = None
        self._camera_id, self._state, self._message = 0, {}, ""
        self._ptz_error, self._busy, self._blocked = "", False, False
        self.changed.emit()

    def _next(self) -> int:
        self._sequence += 1
        return self._sequence

    def _command(self, action: str, extra: dict | None = None, *, motion=False) -> None:
        session = self._state.get("session_id")
        if not session:
            return
        body = {"session_id": session, "sequence": self._next(), "action": action,
                "pan": 0, "tilt": 0, "zoom": 0, "confirm": False, **(extra or {})}
        generation, api, cid, profile = self._generation, self.api, self._camera_id, self._profile
        if not motion:
            self._busy = True
            self.changed.emit()

        def ok(result):
            if generation != self._generation:
                return
            self._busy = False
            self._message = result.get("message", "")
            if result.get("status") is not None:
                self._state["status"] = result["status"]
            if result.get("presets") is not None:
                self._state["presets"] = result["presets"]
            self.changed.emit()
            if motion and self._held:
                self._pulse.start(0)

        def err(exc):
            if generation != self._generation:
                return
            code = exc.code if isinstance(exc, ApiError) else ""
            if motion and not self._held and code == "ptz_stale_command":
                return
            self._busy = False
            self._blocked = True
            self._ptz_error = str(exc)
            self._held = None
            self.changed.emit()

        run_task(lambda: api.ptz_command(cid, profile, body).to_qml(), ok, err)

    @Slot(float, float, float)
    def start(self, pan: float, tilt: float, zoom: float) -> None:
        if self._busy or self._blocked or self._held or not self._state:
            return
        self._held = {"pan": pan, "tilt": tilt, "zoom": zoom}
        self._send_move()

    def _send_move(self) -> None:
        if self._held:
            self._command("move", self._held, motion=True)

    @Slot()
    def stop(self) -> None:
        self._held = None
        self._pulse.stop()
        if self._state.get("session_id"):
            self._command("stop", motion=True)

    @Slot(str, str, bool)
    def operate(self, action: str, value: str = "", confirm: bool = False) -> None:
        if self._held or self._busy or self._blocked:
            return
        extra = {"confirm": confirm}
        if action in ("preset_goto", "preset_remove"):
            extra["preset_token"] = value
        elif action == "preset_save":
            extra["preset_name"] = value.strip()
        self._command(action, extra)

    state = Property("QVariant", lambda self: self._state, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    blocked = Property(bool, lambda self: self._blocked, notify=changed)
    error = Property(str, lambda self: self._ptz_error, notify=changed)
    message = Property(str, lambda self: self._message, notify=changed)
    cameraId = Property(int, lambda self: self._camera_id, notify=changed)
    profile = Property(str, lambda self: self._profile, notify=changed)
