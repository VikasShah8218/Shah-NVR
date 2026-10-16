"""CamerasStore: the camera list (Cameras page, Live camera list, Playback camera picker, Dashboard)
and every camera action: create, update (+ stream changes), enable/disable, delete.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from app.core.context import AppContext
from app.core.list_model import DictListModel
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.cameras import forms

CAMERA_ROLES = [
    "id", "name", "description", "username", "has_password", "enabled", "retention_days",
    "created_at", "updated_at", "streams", "assignment", "lastSegment", "recordStatus",
    "onvif_host", "onvif_port", "manufacturer", "model", "firmware", "serial", "mac",
    "onvif_services", "onvif_reachable", "clock_offset_seconds", "onvif_checked_at",
]


def _decorate(camera: dict) -> dict:
    """Add the computed fields the camera table and live list show."""
    segments = sorted(s["last_segment_at"] for s in camera["streams"] if s.get("last_segment_at"))
    record_stream = next((s for s in camera["streams"] if s["record"]), camera["streams"][0] if camera["streams"] else None)
    camera["lastSegment"] = segments[-1] if segments else None
    camera["recordStatus"] = (record_stream or {}).get("status", "UNKNOWN") if camera["enabled"] else "DISABLED"
    return camera


class CamerasStore(BaseStore):
    camerasChanged = Signal()
    saved = Signal(int)  # camera id, after a successful create/update (closes the form sheet)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.model = DictListModel(CAMERA_ROLES, parent=self)
        self._cameras: list[dict] = []
        self._poller = Poller(self.refresh, ctx.prefs.pollSeconds, self)
        ctx.prefs.pollSecondsChanged.connect(lambda: self._poller.set_interval(ctx.prefs.pollSeconds))
        ctx.centralChanged.connect(self.refresh)
        self._poller.start()

    # ------------------------------------------------------------------ data
    @Slot()
    def refresh(self) -> None:
        self.fetch("cameras", lambda: [_decorate(c.to_qml()) for c in self.api.cameras()], self._apply)

    def _apply(self, cameras: list[dict]) -> None:
        self._cameras = cameras
        self.model.set_items(cameras)
        self.camerasChanged.emit()

    def cameras(self) -> list[dict]:
        return self._cameras

    @Slot(int, result="QVariant")
    def byId(self, camera_id: int):
        return next((c for c in self._cameras if c["id"] == camera_id), None)

    all = Property("QVariantList", lambda self: self._cameras, notify=camerasChanged)
    listModel = Property(QObject, lambda self: self.model, constant=True)

    # ------------------------------------------------------------------ form helpers
    @Slot("QVariant", result="QVariantList")
    def validate(self, form) -> list[str]:
        return forms.validate(form)

    @Slot(result="QVariantList")
    def brandExamples(self) -> list[dict]:
        return forms.BRAND_EXAMPLES

    # ------------------------------------------------------------------ actions
    @Slot("QVariant")
    def create(self, form) -> None:
        body = forms.create_body(form)
        self.act(
            lambda: self.api.create_camera(body).to_qml(),
            success=lambda c: f'Camera "{c["name"]}" added',
            after=lambda c: (self.saved.emit(c["id"]), self.refresh()),
        )

    @Slot(int, "QVariant")
    def update(self, camera_id: int, form) -> None:
        original = self.byId(camera_id) or {"streams": []}
        body = forms.update_body(form)
        diff = forms.stream_diff(original["streams"], form)

        def run():
            self.api.update_camera(camera_id, body)
            for stream in diff["add"]:
                self.api.add_stream(camera_id, stream)
            for change in diff["update"]:
                self.api.update_stream(camera_id, change["profile"], change["body"])
            for profile in diff["remove"]:
                self.api.delete_stream(camera_id, profile)

        self.act(run, success="Camera updated", after=lambda _r: (self.saved.emit(camera_id), self.refresh()))

    @Slot(int, bool)
    def setEnabled(self, camera_id: int, enabled: bool) -> None:
        self.act(lambda: self.api.update_camera(camera_id, {"enabled": enabled}),
                 success="Camera updated", after=lambda _r: self.refresh())

    @Slot(int)
    def remove(self, camera_id: int) -> None:
        self.act(lambda: self.api.delete_camera(camera_id), success="Camera deleted", after=lambda _r: self.refresh())
