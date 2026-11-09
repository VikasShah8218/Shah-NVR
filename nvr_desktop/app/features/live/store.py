"""LiveStore: the Live View grid (layout + which camera is in which tile, remembered between runs)
and the live stream URLs for each camera on view (refreshed every 15 s so a camera that moves to
another media node reconnects to the new node). URL choice per protocol: features/live/sources.py.

Grid pages (docs/PAGINATION_PLAN.md): ‹ › fill the grid with the next 4 / 9 / 16 enabled cameras (by name).
Only the cameras on view are loaded in full (CamerasStore.track), never the whole camera list.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Property, QStandardPaths, Signal, Slot

from app.core.context import AppContext
from app.core.paging import page_count
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.live.sources import pick_sources, streams_by_profile
from app.features.cameras.store import CamerasStore
from app.features.nodes.store import NodesStore

LAYOUTS = (1, 4, 9, 16)


class LiveStore(BaseStore):
    gridChanged = Signal()
    urlsChanged = Signal()
    audioChanged = Signal()
    pagesChanged = Signal()

    def __init__(self, ctx: AppContext, cameras: CamerasStore, nodes: NodesStore, parent=None):
        super().__init__(ctx, parent)
        self._cameras, self._nodes = cameras, nodes
        self._layout, self._tiles = ctx.prefs.live_layout()
        self._selected = 0
        self._urls: dict[int, dict] = {}  # camera id -> {profile: {"rtsp": ..., "hls": ...}}
        self._url_errors: dict[int, str] = {}
        self._urls_revision = 0  # bumped on every URL change so QML bindings calling sources() re-run
        self._active_audio_camera_id = 0
        self._grid_total: int | None = None  # enabled cameras (for "Page 2 / 63")
        self._grid_page = 0  # 0 = the grid was filled by hand
        self._paging = False
        self.urlsChanged.connect(self._bump_revision)
        self.gridChanged.connect(self._track_tiles)
        self._poller = Poller(self.refresh, 15, self)
        ctx.centralChanged.connect(self.refresh)
        self._track_tiles()
        self._poller.start()

    def _track_tiles(self) -> None:
        self._cameras.track("live", [t for t in self._tiles[: self._layout] if t])

    # ------------------------------------------------------------------ live URLs
    @Slot()
    def refresh(self) -> None:
        for camera_id in {t for t in self._tiles if t}:
            self.ensureUrls(camera_id, force=True)
        self.fetch("grid-total", lambda: self.api.camera_options(enabled=True, limit=1)[1], self._set_grid_total,
                   track_error=False)

    def _set_grid_total(self, total: int) -> None:
        if total != self._grid_total:
            self._grid_total = total
            self.pagesChanged.emit()

    @Slot(int)
    @Slot(int, bool)
    def ensureUrls(self, camera_id: int, force: bool = False) -> None:
        if not camera_id or (camera_id in self._urls and not force):
            return

        def ok(live: dict):
            self._urls[camera_id] = streams_by_profile(live)
            self._url_errors.pop(camera_id, None)
            self.urlsChanged.emit()

        def err(exc: Exception):
            self._url_errors[camera_id] = str(exc)
            self.urlsChanged.emit()

        def load():
            camera = self._cameras.byId(camera_id) or self.api.camera(camera_id).to_qml()
            node_id = (camera.get("assignment") or {}).get("node_id")
            access = self._nodes.access(node_id) if node_id else "lan"
            return self.api.live(camera_id, access).to_qml()

        self.fetch(f"live-{camera_id}", load, ok, track_error=False, on_err=err)

    def _bump_revision(self) -> None:
        self._urls_revision += 1

    urlsRevision = Property(int, lambda self: self._urls_revision, notify=urlsChanged)

    @Slot(int, str, str, result="QVariant")
    def sources(self, camera_id: int, profile: str, protocol: str):
        """{source, fallback, protocol, rtsp, error} for one tile. Bind on `urlsRevision` to re-evaluate."""
        return pick_sources(self._urls.get(camera_id), profile, protocol, self._url_errors.get(camera_id, ""))

    # ------------------------------------------------------------------ grid
    def _save(self) -> None:
        self.ctx.prefs.save_live_layout(self._layout, self._tiles)
        self.gridChanged.emit()
        self.pagesChanged.emit()  # a manual change ends the grid page

    @Slot(int)
    def setLayout(self, layout: int) -> None:
        if layout in LAYOUTS:
            self._layout = layout
            self._grid_page = 0
            self._selected = min(self._selected, layout - 1)
            self._save()

    @Slot(int)
    def select(self, index: int) -> None:
        self._selected = index
        self.gridChanged.emit()

    @Slot(int)
    @Slot(int, int)
    def place(self, camera_id: int, index: int = -1) -> None:
        """Put a camera in a tile: the given one, else the selected one if empty, else the first empty one."""
        visible = self._tiles[: self._layout]
        if index < 0:
            index = self._selected if visible[self._selected] is None else next(
                (i for i, t in enumerate(visible) if t is None), self._selected)
        self._tiles[index] = camera_id
        self._selected = min(self._layout - 1, index + 1)
        self._grid_page = 0
        self.ensureUrls(camera_id)
        self._save()

    @Slot(int)
    def clearTile(self, index: int) -> None:
        if self._tiles[index] == self._active_audio_camera_id:
            self.muteAll()
        self._tiles[index] = None
        self._save()

    @Slot()
    def clearAll(self) -> None:
        self.muteAll()
        self._tiles = [None] * 16
        self._grid_page = 0
        self._save()

    # ------------------------------------------------------------------ grid pages
    def _grid_pages(self) -> int:
        return page_count(self._grid_total or 0, self._layout)

    @Slot(int)
    def showGridPage(self, page: int) -> None:
        """Fill the grid with page `page` of the enabled cameras (wraps around at both ends)."""
        if self._paging or not self._grid_total:
            return
        pages = self._grid_pages()
        target = (page - 1) % pages + 1
        layout = self._layout
        self._paging = True
        self.pagesChanged.emit()

        def ok(result):
            rows, total = result
            self._paging = False
            self._grid_total = total
            if layout == self._layout:
                self.muteAll()
                self._tiles = [r["id"] for r in rows][:16] + [None] * (16 - min(16, len(rows)))
                self._selected = 0
                self._grid_page = target
                for camera_id in self._tiles[:layout]:
                    self.ensureUrls(camera_id)
                self._save()
            self.pagesChanged.emit()

        def err(exc):
            self._paging = False
            self.pagesChanged.emit()
            self.ctx.toasts.error(str(exc))

        def load():
            rows, total = self.api.camera_options(enabled=True, limit=layout, offset=(target - 1) * layout)
            return [r.to_qml() for r in rows], total

        self.fetch(f"grid-page-{target}-{layout}", load, ok, track_error=False, on_err=err)

    @Slot()
    def nextGridPage(self) -> None:
        self.showGridPage(self._grid_page + 1 if self._grid_page else 1)

    @Slot()
    def prevGridPage(self) -> None:
        self.showGridPage(self._grid_page - 1 if self._grid_page else self._grid_pages())

    gridTotal = Property(int, lambda self: self._grid_total if self._grid_total is not None else -1, notify=pagesChanged)
    gridPage = Property(int, lambda self: self._grid_page, notify=pagesChanged)
    gridPages = Property(int, lambda self: self._grid_pages(), notify=pagesChanged)
    gridPaging = Property(bool, lambda self: self._paging, notify=pagesChanged)

    layout = Property(int, lambda self: self._layout, notify=gridChanged)
    selected = Property(int, lambda self: self._selected, notify=gridChanged)
    tiles = Property("QVariantList", lambda self: self._tiles[: self._layout], notify=gridChanged)
    onView = Property("QVariantList", lambda self: [t for t in self._tiles[: self._layout] if t], notify=gridChanged)

    @Slot(int)
    def toggleAudio(self, camera_id: int) -> None:
        self._active_audio_camera_id = 0 if self._active_audio_camera_id == camera_id else camera_id
        self.audioChanged.emit()

    @Slot()
    def muteAll(self) -> None:
        if self._active_audio_camera_id:
            self._active_audio_camera_id = 0
            self.audioChanged.emit()

    activeAudioCameraId = Property(int, lambda self: self._active_audio_camera_id, notify=audioChanged)

    # ------------------------------------------------------------------ snapshots
    @Slot(str, result=str)
    def snapshotPath(self, camera_name: str) -> str:
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)) / "Shah-NVR"
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in camera_name)
        return str(folder / f"{safe}_{datetime.now():%Y-%m-%d_%H-%M-%S}.png")
