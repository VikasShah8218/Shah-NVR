"""PlaybackStore: the Playback page (port of nvr_client/src/features/playback/PlaybackPage.tsx).

State: camera, profile, day, timeline zoom/pan, the playlist being played and the playhead.
Clicking the timeline (or a chunk, or "Go") calls `seek(ms)`: it builds an HLS VOD playlist URL from
that moment to the end of the day (or now, for today) and QML's player loads it. The player reports
the real recorded time back through `setPlayhead(ms)`.

Paging (docs/PAGINATION_PLAN.md): the camera picker is a searchable server list (PlaybackCameras), only the
picked camera is loaded in full (CamerasStore.track), the chunk list is hidden until opened and then shown
50 at a time, and exports are paged by central.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from PySide6.QtCore import Property, QSettings, Signal, Slot

from app.core.context import AppContext
from app.core.downloads import download_chunk, downloads_folder
from app.core.api import node as node_api
from app.core.tasks import run_task
from app.core.format import format_bytes
from app.core.paging import clamp_page, slice_page
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.cameras.options_store import CameraOptionsStore
from app.features.cameras.store import CamerasStore
from app.features.nodes.store import NodesStore
from app.features.playback.thumbs import thumb_target, thumbnail_url
from app.features.playback.timeline import DAY, local_midnight, merge_ranges, parse_clock, ticks, to_ms


CHUNKS_PER_PAGE = 50
EXPORTS_PER_PAGE = 5
CHUNKS_OPEN_KEY = "playback/chunksOpen"


def _utc(ms: float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, timezone.utc)


class PlaybackStore(BaseStore):
    selectionChanged = Signal()
    viewChanged = Signal()
    timelineChanged = Signal()
    playChanged = Signal()
    exportsChanged = Signal()
    cameraInfoChanged = Signal()  # the picked camera's full row arrived / changed (name, profiles)
    chunksChanged = Signal()

    def __init__(self, ctx: AppContext, cameras: CamerasStore, nodes: NodesStore,
                 options: CameraOptionsStore | None = None, parent=None):
        super().__init__(ctx, parent)
        self._cameras, self._nodes, self._options = cameras, nodes, options
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
        self._backfill_ranges: list[dict] = []
        self._access = "lan"
        self._exports: list[dict] = []
        self._export_total = 0
        self._export_page = 1
        self._chunk_page = 1
        self._chunks_open = bool(QSettings().value(CHUNKS_OPEN_KEY, False, type=bool))
        self._poller = Poller(self.refresh, 20, self)
        self._export_poller = Poller(self._refresh_exports, 3, self)
        cameras.camerasChanged.connect(self._camera_arrived)
        if options is not None:
            options.changed.connect(self._ensure_camera)
        self._poller.start(immediately=False)
        self._export_poller.start(immediately=False)

    # ------------------------------------------------------------------ selection
    def _ensure_camera(self) -> None:
        """Default to the first camera of the picker list (by name)."""
        rows = self._options.rows if self._options is not None else []
        if not self._camera_id and rows:
            self.setCamera(rows[0]["id"])

    def _camera_arrived(self) -> None:
        """The picked camera's full row came in (or changed): fix the profile if it has no such stream."""
        camera = self._cameras.byId(self._camera_id) if self._camera_id else None
        if not camera:
            return
        self.cameraInfoChanged.emit()
        names = [s["profile"] for s in camera["streams"]]
        if names and self._profile not in names:
            self._profile = next((s["profile"] for s in camera["streams"] if s["record"]), names[0])
            self._stop_playback()
            self.selectionChanged.emit()
            self.refresh()

    def _camera(self) -> dict:
        return self._cameras.byId(self._camera_id) or {"streams": []}

    @Slot(int)
    def setCamera(self, camera_id: int) -> None:
        self._camera_id = camera_id
        self._cameras.track("playback", [camera_id])  # full row (streams) for this camera only
        self._chunk_page = self._export_page = 1
        self.cameraInfoChanged.emit()
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

    @Slot(int, str, float)
    def openBookmark(self, camera_id: int, profile: str, start_ms: float) -> None:
        """Bookmarks panel: switch camera / profile / day as needed and play from the bookmark."""
        self.openAt(camera_id, profile, start_ms)

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
                        notify=cameraInfoChanged)
    cameraName = Property(str, lambda self: self._camera().get("name", ""), notify=cameraInfoChanged)
    day = Property(float, lambda self: self._day, notify=selectionChanged)
    isToday = Property(bool, _is_today, notify=selectionChanged)

    # ------------------------------------------------------------------ timeline data
    @Slot()
    def refresh(self) -> None:
        cid, profile, day = self._camera_id, self._profile, self._day
        if not cid:
            return
        self._refresh_exports(cid)
        if not self._is_today() and self._timeline.get("_key") == (cid, profile, day):
            return  # past days do not change

        def load():
            timeline = self.api.timeline(cid, profile, _utc(day), _utc(day + DAY)).to_qml()
            node_ids = {s.get("node_id") for s in timeline.get("segments", []) if s.get("node_id")}
            access = "public" if any(self._nodes.access(node_id) == "public" for node_id in node_ids) else "lan"
            return timeline, access

        def apply(result):
            timeline, access = result
            if (cid, profile, day) != (self._camera_id, self._profile, self._day):
                return
            self._access = access
            timeline["_key"] = (cid, profile, day)
            self._timeline = timeline
            self._ranges = [{"a": a, "b": b} for a, b in merge_ranges(timeline["segments"])]
            backfilled = [s for s in timeline["segments"] if s.get("origin") == "CAMERA_SD"]
            self._backfill_ranges = [{"a": a, "b": b} for a, b in merge_ranges(backfilled)]
            self.timelineChanged.emit()
            self.viewChanged.emit()  # the chunk list depends on the data too

        self.fetch("timeline", load, apply)

    def _refresh_exports(self, camera_id: int | None = None) -> None:
        cid = camera_id or self._camera_id
        if not cid:
            return
        page = self._export_page

        def load():
            rows, total = self.api.exports(cid, limit=EXPORTS_PER_PAGE, offset=(page - 1) * EXPORTS_PER_PAGE)
            return [job.to_qml() for job in rows], total

        self.fetch("exports", load, lambda result: self._apply_exports(cid, page, *result), track_error=False)

    def _apply_exports(self, camera_id: int, page: int, rows: list[dict], total: int) -> None:
        if camera_id != self._camera_id or page != self._export_page:
            return
        self._exports, self._export_total = rows, total
        clamped = clamp_page(page, total, EXPORTS_PER_PAGE)
        if clamped != page:
            self._export_page = clamped
            self._refresh_exports()
        self.exportsChanged.emit()

    @Slot(int)
    def setExportPage(self, page: int) -> None:
        if page != self._export_page:
            self._export_page = max(1, page)
            self.exportsChanged.emit()
            self._refresh_exports()

    exportPage = Property(int, lambda self: self._export_page, notify=exportsChanged)
    exportTotal = Property(int, lambda self: self._export_total, notify=exportsChanged)
    exportPageSize = Property(int, lambda self: EXPORTS_PER_PAGE, constant=True)

    # ------------------------------------------------------------------ chunks in view (hidden by default, paged)
    def _all_chunks_in_view(self) -> list[dict]:
        start, end = self._view_start, self._view_start + self._zoom
        return [s for s in self._timeline.get("segments", []) if to_ms(s["end_time"]) > start and to_ms(s["start_time"]) < end]

    def _chunks_in_view(self) -> list[dict]:
        """The current page of the chunks in view, newest first (empty while the list is hidden)."""
        if not self._chunks_open:
            return []
        rows = slice_page(list(reversed(self._all_chunks_in_view())), self._chunk_page, CHUNKS_PER_PAGE)
        return [{**s, "startMs": to_ms(s["start_time"]), "endMs": to_ms(s["end_time"])} for s in rows]

    @Slot()
    def toggleChunks(self) -> None:
        self._chunks_open = not self._chunks_open
        QSettings().setValue(CHUNKS_OPEN_KEY, self._chunks_open)
        self.viewChanged.emit()

    @Slot(int)
    def setChunkPage(self, page: int) -> None:
        self._chunk_page = clamp_page(page, len(self._all_chunks_in_view()), CHUNKS_PER_PAGE)
        self.viewChanged.emit()

    chunksOpen = Property(bool, lambda self: self._chunks_open, notify=viewChanged)
    chunkTotal = Property(int, lambda self: len(self._all_chunks_in_view()), notify=viewChanged)
    chunkPage = Property(int, lambda self: clamp_page(self._chunk_page, len(self._all_chunks_in_view()), CHUNKS_PER_PAGE),
                         notify=viewChanged)
    chunkPageSize = Property(int, lambda self: CHUNKS_PER_PAGE, constant=True)

    ranges = Property("QVariantList", lambda self: self._ranges, notify=timelineChanged)
    backfillRanges = Property("QVariantList", lambda self: self._backfill_ranges, notify=timelineChanged)
    coverage = Property(float, lambda self: self._timeline.get("coverage_percent", 0.0), notify=timelineChanged)
    totalSize = Property(str, lambda self: format_bytes(self._timeline.get("total_size_bytes")), notify=timelineChanged)
    hasTimeline = Property(bool, lambda self: bool(self._timeline), notify=timelineChanged)
    chunks = Property("QVariantList", _chunks_in_view, notify=viewChanged)
    hasAudio = Property(bool, lambda self: any(bool(s.get("audio_codec")) for s in self._timeline.get("segments", [])),
                        notify=timelineChanged)

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

    @Slot(float, result="QVariant")
    def thumbAt(self, epoch_ms: float) -> dict:
        """Timeline hover preview: {url, at} for the chunk recorded at `epoch_ms`, or {} (gap / unknown node).

        The picture comes straight from the node that holds the chunk (app/features/playback/thumbs.py)."""
        target = thumb_target(self._timeline.get("segments", []), epoch_ms)
        api_url = target and self._nodes.api_url(target["node_id"])
        if not target or not api_url:
            return {}
        return {"url": thumbnail_url(api_url, target["segment_id"], target["at_ms"]), "at": target["slot_start"]}

    @Slot(float)
    def setPlayhead(self, epoch_ms: float) -> None:
        self._playhead = epoch_ms
        self.playChanged.emit()
        # keep the playhead visible while zoomed in
        if self._zoom < DAY and epoch_ms > self._view_start + self._zoom * 0.9:
            self.pan(epoch_ms - self._zoom * 0.1)

    def _stop_playback(self) -> None:
        self._play_from = self._playhead = 0.0
        self._timeline, self._ranges, self._backfill_ranges = {}, [], []
        self._exports, self._export_total = [], 0
        self.playChanged.emit()
        self.timelineChanged.emit()
        self.exportsChanged.emit()

    def _playlist_url(self) -> str:
        if not (self._camera_id and self._play_from):
            return ""
        return self.api.playlist_url(self._camera_id, self._profile, _utc(self._play_from), _utc(self._play_to), self._access)

    playlistUrl = Property(str, _playlist_url, notify=playChanged)
    playhead = Property(float, lambda self: self._playhead, notify=playChanged)
    playFrom = Property(float, lambda self: self._play_from, notify=playChanged)
    playTo = Property(float, lambda self: self._play_to, notify=playChanged)

    # ------------------------------------------------------------------ exports
    exports = Property("QVariantList", lambda self: self._exports, notify=exportsChanged)

    @Slot(float, float, str, str, str, str, int, int, bool)
    def createExport(self, start_ms: float, end_ms: float, mode: str, codec: str, quality: str,
                     processor: str, max_height: int, max_fps: int, include_audio: bool) -> None:
        if not self._camera_id:
            return
        if end_ms <= start_ms or end_ms - start_ms > 4 * 60 * 60 * 1000 or end_ms > time.time() * 1000 + 5000:
            self.ctx.toasts.error("Choose a past interval longer than zero and no more than four hours")
            return
        body = {"camera_id": self._camera_id, "profile": self._profile,
                "start_time": _utc(start_ms).isoformat(), "end_time": _utc(end_ms).isoformat(), "mode": mode,
                "video_codec": codec, "quality": quality, "processor": processor,
                "max_height": max_height, "max_fps": max_fps, "include_audio": include_audio,
                "audio_bitrate_kbps": 128}
        self.act(lambda: self.api.create_export(body), "Export queued", lambda _job: self._refresh_exports())

    @Slot(str)
    def cancelExport(self, export_id: str) -> None:
        self.act(lambda: self.api.cancel_export(export_id), "Export cancelled", lambda _job: self._refresh_exports())

    @Slot(str, str)
    def downloadExport(self, export_id: str, output_name: str) -> None:
        target = downloads_folder() / (output_name or f"export-{export_id}.mp4")
        url = self.api.export_download_url(export_id, self._access)
        self.ctx.toasts.info(f"Downloading {target.name}…")
        run_task(lambda: node_api.download(url, target),
                 lambda path: self.ctx.toasts.success(f"Saved {path}"),
                 lambda exc: self.ctx.toasts.error(str(exc)))

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
