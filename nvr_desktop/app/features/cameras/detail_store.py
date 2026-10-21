"""CameraDetailStore: one camera's detail page (overview, last 24 h of recordings, assignment).

QML sets `cameraId` when the page opens (and 0 when it closes, which stops polling).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from PySide6.QtCore import Property, Signal, Slot

from app.core.context import AppContext
from app.core.poller import Poller
from app.core.store import BaseStore
from app.core.tasks import run_task
from app.features.live.sources import pick_sources, streams_by_profile
from app.features.onvif.helpers import format_offset, onvif_error_text, service_names
from app.features.playback.timeline import DAY, merge_ranges, ticks
from app.features.nodes.store import NodesStore


class CameraDetailStore(BaseStore):
    cameraIdChanged = Signal()
    cameraChanged = Signal()
    liveChanged = Signal()
    historyChanged = Signal()
    recordingsChanged = Signal()
    deviceChanged = Signal()
    ntpSaved = Signal()

    def __init__(self, ctx: AppContext, nodes: NodesStore | None = None, parent=None):
        super().__init__(ctx, parent)
        self._nodes = nodes
        self._camera_id = 0
        self._camera: dict = {}
        self._live: dict = {}
        self._live_error = ""
        self._history: list[dict] = []
        self._recordings: dict = {}
        self._recordings_profile = ""
        self._device: dict = {}
        self._device_error = ""
        self._device_busy = False
        self._device_generation = 0
        self._poller = Poller(self.refresh, ctx.prefs.pollSeconds, self)
        self._slow_poller = Poller(self._refresh_slow, 60, self)
        ctx.centralChanged.connect(self._reset_server)

    def _reset_server(self):
        cid = self._camera_id
        self._set_camera_id(0)
        self._set_camera_id(cid)

    # ------------------------------------------------------------------ selection
    def _get_camera_id(self) -> int:
        return self._camera_id

    def _set_camera_id(self, value: int) -> None:
        if value == self._camera_id:
            return
        self._camera_id = value
        self._device_generation += 1
        self._camera, self._live, self._history, self._recordings = {}, {}, [], {}
        self._recordings_profile, self._live_error = "", ""
        self._device, self._device_error, self._device_busy = {}, "", False
        self._set_loading(True)
        self._set_error("")
        self.cameraIdChanged.emit()
        self.cameraChanged.emit()
        self.deviceChanged.emit()
        self.liveChanged.emit()
        self.historyChanged.emit()
        self.recordingsChanged.emit()
        if value:
            self._poller.start()
            self._slow_poller.start()
        else:
            self._poller.stop()
            self._slow_poller.stop()

    cameraId = Property(int, _get_camera_id, _set_camera_id, notify=cameraIdChanged)

    # ------------------------------------------------------------------ data
    @Slot()
    def refresh(self) -> None:
        cid = self._camera_id
        if not cid:
            return
        self.fetch("camera", lambda: self.api.camera(cid).to_qml(), lambda c: self._apply_camera(cid, c))
        self.fetch("history", lambda: [h.to_qml() for h in self.api.assignment_history(cid)],
                   lambda h: self._apply_history(cid, h), track_error=False)

    def _refresh_slow(self) -> None:
        cid = self._camera_id
        if not cid:
            return
        def load_live():
            node_id = (self._camera.get("assignment") or {}).get("node_id")
            access = self._nodes.access(node_id) if self._nodes is not None and node_id else "lan"
            return self.api.live(cid, access).to_qml()
        self.fetch("live", load_live, lambda live: self._apply_live(cid, live, ""),
                   track_error=False, on_err=lambda exc: self._apply_live(cid, {}, str(exc)))
        self.loadRecordings(self._recordings_profile)

    def _apply_camera(self, cid: int, camera: dict) -> None:
        if cid != self._camera_id:
            return
        self._camera = camera
        self._camera["onvifServiceNames"] = service_names(camera.get("onvif_services"))
        self._camera["onvifOffsetText"] = format_offset(camera.get("clock_offset_seconds"))
        if not self._recordings_profile:
            record = next((s for s in camera["streams"] if s["record"]), None)
            self._recordings_profile = (record or (camera["streams"] or [{"profile": "main"}])[0])["profile"]
            self.loadRecordings(self._recordings_profile)
        self.cameraChanged.emit()

    def _apply_live(self, cid: int, live: dict, error: str) -> None:
        if cid == self._camera_id:
            self._live, self._live_error = live, error
            self.liveChanged.emit()

    def _apply_history(self, cid: int, history: list[dict]) -> None:
        if cid == self._camera_id:
            self._history = history
            self.historyChanged.emit()

    @Slot(str)
    def loadRecordings(self, profile: str) -> None:
        cid = self._camera_id
        if not cid or not profile:
            return
        self._recordings_profile = profile
        end_ms = int(time.time() // 60 * 60 * 1000)
        start_ms = end_ms - DAY
        start = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
        end = datetime.fromtimestamp(end_ms / 1000, timezone.utc)

        def apply(timeline: dict) -> None:
            if cid != self._camera_id:
                return
            timeline["ranges"] = [{"a": a, "b": b} for a, b in merge_ranges(timeline["segments"])]
            timeline["viewStart"], timeline["viewEnd"] = start_ms, end_ms
            timeline["ticks"] = ticks(start_ms, end_ms)
            self._recordings = timeline
            self.recordingsChanged.emit()

        self.fetch("recordings", lambda: self.api.timeline(cid, profile, start, end).to_qml(), apply, track_error=False)

    @Slot(str, str, result="QVariant")
    def previewSources(self, profile: str, protocol: str):
        """URLs for the Overview live preview. QML re-evaluates on liveChanged."""
        return pick_sources(streams_by_profile(self._live), profile, protocol, self._live_error)

    # ------------------------------------------------------------------ ONVIF device
    @Slot()
    def loadDevice(self) -> None:
        cid = self._camera_id
        generation = self._device_generation
        api = self.api
        if not cid or self._device_busy:
            return
        self._device_busy = True
        self._device_error = ""
        self.deviceChanged.emit()

        def ok(device: dict) -> None:
            if generation != self._device_generation:
                return
            device["serviceNames"] = service_names(device.get("services"))
            device["offsetText"] = format_offset(device.get("clock", {}).get("offset_seconds"))
            self._device = device
            self._device_error = ""
            self._device_busy = False
            self.deviceChanged.emit()
            self.refresh()  # refresh the saved identity/reachability fields too

        def err(exc: Exception) -> None:
            if generation != self._device_generation:
                return
            self._device_error = onvif_error_text(exc)
            self._device_busy = False
            self.deviceChanged.emit()

        self.fetch(f"device:{generation}", lambda: api.onvif_device(cid).to_qml(), ok, track_error=False, on_err=err)

    def _device_action(self, fn, success, *, ntp=False, refresh=True) -> None:
        if self._device_busy:
            return
        generation = self._device_generation
        self._device_busy = True
        self.deviceChanged.emit()

        def ok(result) -> None:
            if generation != self._device_generation:
                return
            self._device_busy = False
            self.ctx.toasts.success(success(result) if callable(success) else success)
            self.deviceChanged.emit()
            if ntp:
                self.ntpSaved.emit()
            if refresh:
                self.loadDevice()

        def err(exc: Exception) -> None:
            if generation != self._device_generation:
                return
            self._device_busy = False
            self.ctx.toasts.error(onvif_error_text(exc))
            self.deviceChanged.emit()

        run_task(fn, ok, err)

    @Slot()
    def syncTime(self) -> None:
        cid = self._camera_id
        api = self.api
        if cid:
            self._device_action(lambda: api.onvif_time_sync(cid).to_qml(),
                                "Camera clock set to the node's time")

    @Slot(bool, str)
    def setNtp(self, from_dhcp: bool, servers: str) -> None:
        cid = self._camera_id
        api = self.api
        values = [value for value in servers.replace(",", " ").split() if value]
        if not from_dhcp and not values:
            self.ctx.toasts.error("Give at least one NTP server or choose DHCP")
            return
        if cid:
            self._device_action(lambda: api.onvif_set_ntp(cid, from_dhcp, [] if from_dhcp else values),
                                "NTP settings saved on the camera", ntp=True)

    @Slot()
    def reboot(self) -> None:
        cid = self._camera_id
        api = self.api
        if cid:
            self._device_action(lambda: api.onvif_reboot(cid),
                                lambda result: f'Camera: {result.get("message", "reboot requested")}', refresh=False)

    # ------------------------------------------------------------------ actions
    @Slot(int)
    def moveTo(self, node_id: int) -> None:
        cid = self._camera_id
        self.act(lambda: self.api.move_camera(cid, node_id).to_qml(),
                 success=lambda a: f"{a['camera_name']} moved to {a['node_name']}",
                 after=lambda _a: self.refresh())

    # ------------------------------------------------------------------ properties
    camera = Property("QVariant", lambda self: self._camera, notify=cameraChanged)
    live = Property("QVariant", lambda self: self._live, notify=liveChanged)
    liveError = Property(str, lambda self: self._live_error, notify=liveChanged)
    history = Property("QVariantList", lambda self: self._history, notify=historyChanged)
    recordings = Property("QVariant", lambda self: self._recordings, notify=recordingsChanged)
    recordingsProfile = Property(str, lambda self: self._recordings_profile, notify=recordingsChanged)
    device = Property("QVariant", lambda self: self._device, notify=deviceChanged)
    deviceError = Property(str, lambda self: self._device_error, notify=deviceChanged)
    deviceBusy = Property(bool, lambda self: self._device_busy, notify=deviceChanged)
