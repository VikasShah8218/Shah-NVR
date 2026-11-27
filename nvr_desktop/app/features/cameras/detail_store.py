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
from app.core.format import time_ago
from app.core.tasks import run_task
from app.features.cameras import camera_events as ce
from app.features.live.sources import pick_sources, streams_by_profile
from app.features.onvif.helpers import format_offset, onvif_error_text, service_names
from app.features.playback.timeline import DAY, merge_ranges, ticks
from app.features.nodes.store import NodesStore


HISTORY_PER_PAGE = 10

class CameraDetailStore(BaseStore):
    cameraIdChanged = Signal()
    cameraChanged = Signal()
    liveChanged = Signal()
    historyChanged = Signal()
    recordingsChanged = Signal()
    deviceChanged = Signal()
    eventsChanged = Signal()
    ntpSaved = Signal()

    def __init__(self, ctx: AppContext, nodes: NodesStore | None = None, parent=None):
        super().__init__(ctx, parent)
        self._nodes = nodes
        self._camera_id = 0
        self._camera: dict = {}
        self._live: dict = {}
        self._live_error = ""
        self._history: list[dict] = []
        self._history_page = 1
        self._history_total = 0
        self._recordings: dict = {}
        self._recordings_profile = ""
        self._device: dict = {}
        self._device_error = ""
        self._device_busy = False
        self._device_generation = 0
        self._reset_events()
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
        self._history_page, self._history_total = 1, 0
        self._recordings_profile, self._live_error = "", ""
        self._device, self._device_error, self._device_busy = {}, "", False
        self._reset_events()
        self._set_loading(True)
        self._set_error("")
        self.cameraIdChanged.emit()
        self.cameraChanged.emit()
        self.deviceChanged.emit()
        self.eventsChanged.emit()
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
        self._refresh_history()

    def _refresh_history(self) -> None:
        cid, page = self._camera_id, self._history_page
        if not self.allowed(24, 20):  # ASSIGNMENTS or CAMERAS_MANAGE (central's rule for the history)
            return

        def load():
            rows, total = self.api.assignment_history(cid, limit=HISTORY_PER_PAGE, offset=(page - 1) * HISTORY_PER_PAGE)
            return [h.to_qml() for h in rows], total

        self.fetch("history", load, lambda result: self._apply_history(cid, page, *result), track_error=False)

    @Slot(int)
    def setHistoryPage(self, page: int) -> None:
        if page >= 1 and page != self._history_page:
            self._history_page = page
            self.historyChanged.emit()
            self._refresh_history()

    def _refresh_slow(self) -> None:
        cid = self._camera_id
        if not cid:
            return
        if not self.allowed(1):  # Perm.LIVE: no live URLs (and no audited "live.open") without it
            self.loadRecordings(self._recordings_profile)
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
        key = ce.form_key(camera)
        if key != self._events_key:  # first load, a save, or another client's change: the draft starts again
            self._events_key, self._events_form = key, ce.form_from_camera(camera)
        self.cameraChanged.emit()
        self.eventsChanged.emit()  # the status line follows every poll

    def _apply_live(self, cid: int, live: dict, error: str) -> None:
        if cid == self._camera_id:
            self._live, self._live_error = live, error
            self.liveChanged.emit()

    def _apply_history(self, cid: int, page: int, history: list[dict], total: int) -> None:
        if page != self._history_page:
            return
        self._history_total = total
        if cid == self._camera_id:
            self._history = history
            self.historyChanged.emit()

    @Slot(str)
    def loadRecordings(self, profile: str) -> None:
        cid = self._camera_id
        if not cid or not profile:
            return
        self._recordings_profile = profile
        if not self.allowed(2):  # Perm.PLAYBACK
            return
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

    # ------------------------------------------------------------------ camera events (ONVIF)
    # The Camera events tab (docs/DESKTOP_ONVIF_EVENTS_PLAN.md): a draft of the switches, Save, Detect, status line.
    def _reset_events(self) -> None:
        self._events_key = None
        self._events_form = {"enabled": False, "kinds": list(ce.KINDS), "storeOther": False}
        self._events_saving = False
        self._events_detecting = False
        self._events_all_topics: list[str] = []
        self._events_analytics: list[dict] | None = None  # from the last Detect (else the saved status)

    def _events_view(self) -> dict:
        cam, form = self._camera, self._events_form
        status = cam.get("onvif_events_status") or {}
        offered = status.get("offered")
        line = ce.status_line(bool(cam.get("onvif_events_enabled")), form["kinds"], status, time_ago)
        analytics = self._events_analytics if self._events_analytics is not None else (status.get("analytics") or [])

        def row(k: str) -> dict:
            rules = next((a.get("rules") or [] for a in analytics if a.get("kind") == k), [])
            return {"kind": k, "title": ce.LABELS[k]["title"], "on": k in form["kinds"],
                    "hint": "Not offered by this camera" if offered is not None and k not in offered
                    else ce.LABELS[k]["hint"],
                    "rules": ("Rules: " + ", ".join(str(r.get("name"))[:64] for r in rules[:12])) if rules else ""}

        shown = [k for k in ce.ANALYTICS_KINDS if (offered is not None and k in offered) or k in form["kinds"]]
        return {
            **form,
            "hasHost": bool(cam.get("onvif_host")),
            "canSave": bool(cam) and ce.can_save(form, cam) and not self._events_saving,
            "saving": self._events_saving,
            "detecting": self._events_detecting,
            "tone": line["tone"],
            "text": line["text"],
            "rows": [row(k) for k in ce.KINDS],
            "analyticsRows": [row(k) for k in shown],
            "otherAnalyticsRows": [row(k) for k in ce.ANALYTICS_KINDS if k not in shown],
            "otherAnalyticsTitle": "Not offered by this camera" if offered is not None else "All analytics kinds",
            "analyticsNote": "" if shown else ("This camera offers no analytics." if offered is not None
                                               else "Press Detect to see which analytics the camera offers."),
            "offeredText": (", ".join(ce.kind_title(k) for k in offered) or "None of these events")
            if offered is not None else "Not detected yet",
            "topics": [{"kind": k, "title": ce.kind_title(k), "topic": t}
                       for k, t in (status.get("topics") or {}).items()],
            "since": time_ago(status["since"]) if status.get("since") and cam.get("onvif_events_enabled") else "",
            "allTopics": self._events_all_topics,
        }

    def _edit_events(self, **change) -> None:
        self._events_form = {**self._events_form, **change}
        self.eventsChanged.emit()

    @Slot(bool)
    def setEventsEnabled(self, on: bool) -> None:
        self._edit_events(enabled=on)

    @Slot(str, bool)
    def setEventKind(self, kind: str, on: bool) -> None:
        self._edit_events(kinds=ce.with_kind(self._events_form["kinds"], kind, on))

    @Slot(bool)
    def setEventsStoreOther(self, on: bool) -> None:
        self._edit_events(storeOther=on)

    @Slot()
    def saveEvents(self) -> None:
        cid, cam = self._camera_id, self._camera
        if not cid or self._events_saving or not self.allowed(20) or not ce.can_save(self._events_form, cam):
            return
        body = ce.body_from_form(self._events_form)
        api = self.api
        self._events_saving = True
        self.eventsChanged.emit()

        def done(camera: dict | None) -> None:
            self._events_saving = False
            if camera is not None:
                self._apply_camera(cid, camera)
            self.eventsChanged.emit()

        self.act(lambda: api.update_camera(cid, body).to_qml(), success="Camera events saved",
                 after=done, on_error=lambda _e: done(None))

    @Slot()
    def detectEvents(self) -> None:
        cid = self._camera_id
        if not cid or self._events_detecting or not self.allowed(20):
            return
        api = self.api
        self._events_detecting = True
        self.eventsChanged.emit()

        def ok(probe: dict) -> None:
            if cid != self._camera_id:
                return
            self._events_detecting = False
            self._events_all_topics = sorted(probe.get("all_topics") or [])
            self._events_analytics = probe.get("analytics") or []
            self.eventsChanged.emit()
            self.refresh()  # central saved what the camera offers into the status

        def err(exc: Exception) -> None:
            if cid != self._camera_id:
                return
            self._events_detecting = False
            self.ctx.toasts.error(onvif_error_text(exc))
            self.eventsChanged.emit()

        run_task(lambda: api.probe_camera_events(cid).to_qml(), ok, err)

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
    historyPage = Property(int, lambda self: self._history_page, notify=historyChanged)
    historyTotal = Property(int, lambda self: self._history_total, notify=historyChanged)
    historyPageSize = Property(int, lambda self: HISTORY_PER_PAGE, constant=True)
    recordings = Property("QVariant", lambda self: self._recordings, notify=recordingsChanged)
    recordingsProfile = Property(str, lambda self: self._recordings_profile, notify=recordingsChanged)
    device = Property("QVariant", lambda self: self._device, notify=deviceChanged)
    deviceError = Property(str, lambda self: self._device_error, notify=deviceChanged)
    deviceBusy = Property(bool, lambda self: self._device_busy, notify=deviceChanged)
    events = Property("QVariant", lambda self: self._events_view(), notify=eventsChanged)
