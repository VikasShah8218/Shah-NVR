"""PlaybackStore: the Playback page (port of nvr_client/src/features/playback/PlaybackPage.tsx).

State: camera, profile, day, timeline zoom/pan, the playlist being played and the playhead.
Clicking the timeline (or a chunk, or "Go") calls `seek(ms)`: it builds an HLS VOD playlist URL from
that moment to the end of the day (or now, for today) and QML's player loads it. The player reports
the real recorded time back through `setPlayhead(ms)`.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from PySide6.QtCore import Property, Signal, Slot

from app.core.context import AppContext
from app.core.downloads import download_chunk
from app.core.format import format_bytes
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.cameras.store import CamerasStore
from app.features.nodes.store import NodesStore
from app.features.playback.timeline import DAY, local_midnight, merge_ranges, parse_clock, ticks, to_ms


def _utc(ms: float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


class PlaybackStore(BaseStore):
    selectionChanged = Signal()
    viewChanged = Signal()
    timelineChanged = Signal()
    playChanged = Signal()

    def __init__(self, ctx: AppContext, cameras: CamerasStore, nodes: NodesStore, parent=None):
        super().__init__(ctx, parent)
        self._cameras, self._nodes = cameras, nodes
        self._camera_id = 0
        self._profile = "main"
        self._day = local_midnight(time.time() * 1000)
        self._zoom = DAY
        self._view_start = self._day
        self._play_from = 0.0
        self._play_to = 0.0
        self._playhead = 0.0
        self._timeline: dict = {}
        self._ranges: list[dict] = []
        self._poller = Poller(self.refresh, 20, self)
        cameras.camerasChanged.connect(self._ensure_camera)
        self._poller.start(immediately=False)

    # ------------------------------------------------------------------ selection
    def _ensure_camera(self) -> None:
        """Default to the first camera, and a recorded profile of the selected camera."""
        cameras = self._cameras.cameras()
        if not self._camera_id and cameras:
            self.setCamera(cameras[0]["id"])

    def _camera(self) -> dict:
        return self._cameras.byId(self._camera_id) or {"streams": []}

    @Slot(int)
    def setCamera(self, camera_id: int) -> None:
        self._camera_id = camera_id
        streams = self._camera()["streams"]
        if streams and self._profile not in [s["profile"] for s in streams]:
            self._profile = next((s["profile"] for s in streams if s["record"]), streams[0]["profile"])
        self._stop_playback()
        self.selectionChanged.emit()
        self.refresh()

    @Slot(int, str, float)
    def openAt(self, camera_id: int, profile: str, epoch_ms: float) -> None:
        """Open from another page (camera detail, cameras menu): camera, optional profile and moment."""
        if profile:
            self._profile = profile
        if epoch_ms > 0:
            self._day = local_midnight(epoch_ms)
            self._zoom = DAY
            self._view_start = self._day
            self.viewChanged.emit()
        self.setCamera(camera_id)
        if epoch_ms > 0:
            self.seek(epoch_ms)

    @Slot(str)
    def setProfile(self, profile: str) -> None:
        self._profile = profile
        self._stop_playback()
        self.selectionChanged.emit()
        self.refresh()

    @Slot(float)
    def setDay(self, epoch_ms: float) -> None:
        self._day = local_midnight(epoch_ms)
        self._zoom = DAY
        self._view_start = self._day
        self._stop_playback()
        self.selectionChanged.emit()
        self.viewChanged.emit()
        self.refresh()

    @Slot()
    def previousDay(self) -> None:
        self.setDay(self._day - DAY / 2)

    @Slot()
    def nextDay(self) -> None:
        if not self.isToday:
            self.setDay(self._day + DAY * 1.5)

    def _is_today(self) -> bool:
        return local_midnight(time.time() * 1000) == self._day

    cameraId = Property(int, lambda self: self._camera_id, notify=selectionChanged)
    profile = Property(str, lambda self: self._profile, notify=selectionChanged)
    profiles = Property("QVariantList", lambda self: [s["profile"] for s in self._camera()["streams"]],
                        notify=selectionChanged)
    day = Property(float, lambda self: self._day, notify=selectionChanged)
    isToday = Property(bool, _is_today, notify=selectionChanged)

    # ------------------------------------------------------------------ timeline data
    @Slot()
    def refresh(self) -> None:
        cid, profile, day = self._camera_id, self._profile, self._day
        if not cid:
            return
        if not self._is_today() and self._timeline.get("_key") == (cid, profile, day):
            return  # past days do not change

        def apply(timeline: dict):
            if (cid, profile, day) != (self._camera_id, self._profile, self._day):
                return
            timeline["_key"] = (cid, profile, day)
            self._timeline = timeline
            self._ranges = [{"a": a, "b": b} for a, b in merge_ranges(timeline["segments"])]
            self.timelineChanged.emit()
            self.viewChanged.emit()  # the chunk list depends on the data too

        self.fetch("timeline", lambda: self.api.timeline(cid, profile, _utc(day), _utc(day + DAY)).to_qml(), apply)

    def _chunks_in_view(self) -> list[dict]:
        start, end = self._view_start, self._view_start + self._zoom
        rows = [s for s in self._timeline.get("segments", []) if to_ms(s["end_time"]) > start and to_ms(s["start_time"]) < end]
        return [{**s, "startMs": to_ms(s["start_time"]), "endMs": to_ms(s["end_time"])} for s in reversed(rows)]

    ranges = Property("QVariantList", lambda self: self._ranges, notify=timelineChanged)
    coverage = Property(float, lambda self: self._timeline.get("coverage_percent", 0.0), notify=timelineChanged)
    totalSize = Property(str, lambda self: format_bytes(self._timeline.get("total_size_bytes")), notify=timelineChanged)
    hasTimeline = Property(bool, lambda self: bool(self._timeline), notify=timelineChanged)
    chunks = Property("QVariantList", _chunks_in_view, notify=viewChanged)

    # ------------------------------------------------------------------ view (zoom / pan)
    @Slot(float)
    def setZoom(self, zoom_ms: float) -> None:
        center = self._playhead or (self._view_start + self._zoom / 2)
        self._zoom = zoom_ms
        self._view_start = max(self._day, min(self._day + DAY - zoom_ms, center - zoom_ms / 2))
        self.viewChanged.emit()

    @Slot(float)
    def pan(self, view_start: float) -> None:
        self._view_start = max(self._day, min(self._day + DAY - self._zoom, view_start))
        self.viewChanged.emit()

    @Slot()
    def jumpToNow(self) -> None:
        self.pan(time.time() * 1000 - self._zoom * 0.8)

    viewStart = Property(float, lambda self: self._view_start, notify=viewChanged)
    viewEnd = Property(float, lambda self: self._view_start + self._zoom, notify=viewChanged)
    zoom = Property(float, lambda self: self._zoom, notify=viewChanged)
    ticks = Property("QVariantList", lambda self: ticks(self._view_start, self._view_start + self._zoom), notify=viewChanged)

    # ------------------------------------------------------------------ playback
    @Slot(float)
    def seek(self, epoch_ms: float) -> None:
        self._play_from = max(self._day, min(self._day + DAY, epoch_ms))
        self._play_to = min(self._day + DAY, time.time() * 1000)  # fixed now: the playlist URL stays stable
        self._playhead = self._play_from
        self.playChanged.emit()

    @Slot(str, result=bool)
    def goTo(self, text: str) -> bool:
        offset = parse_clock(text)
        if offset is None:
            self.ctx.toasts.error("Use HH:MM or HH:MM:SS")
            return False
        self.seek(self._day + offset)
        return True

    @Slot(float)
    def setPlayhead(self, epoch_ms: float) -> None:
        self._playhead = epoch_ms
        self.playChanged.emit()
        # keep the playhead visible while zoomed in
        if self._zoom < DAY and epoch_ms > self._view_start + self._zoom * 0.9:
            self.pan(epoch_ms - self._zoom * 0.1)

    def _stop_playback(self) -> None:
        self._play_from = self._playhead = 0.0
        self._timeline, self._ranges = {}, []
        self.playChanged.emit()
        self.timelineChanged.emit()

    def _playlist_url(self) -> str:
        if not (self._camera_id and self._play_from):
            return ""
        return self.api.playlist_url(self._camera_id, self._profile, _utc(self._play_from), _utc(self._play_to))

    playlistUrl = Property(str, _playlist_url, notify=playChanged)
    playhead = Property(float, lambda self: self._playhead, notify=playChanged)

    # ------------------------------------------------------------------ downloads
    @Slot(str, int)
    def download(self, segment_id: str, node_id: int) -> None:
        api_url = self._nodes.api_url(node_id)
        if not api_url:
            self.ctx.toasts.error("The node holding this chunk is unknown")
            return
        segment = next((s for s in self._timeline.get("segments", []) if s["id"] == segment_id), None)
        start = datetime.fromtimestamp(to_ms(segment["start_time"]) / 1000) if segment else datetime.now()
        download_chunk(self.ctx.toasts, api_url, segment_id, self._camera_id, self._profile, start)

    @Slot(result=float)
    def nowMs(self) -> float:
        return time.time() * 1000
