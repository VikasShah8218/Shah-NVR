"""LiveStore: the Live View grid (layout + which camera is in which tile, remembered between runs)
and the live stream URLs for each camera on view (refreshed every 15 s so a camera that moves to
another media node reconnects to the new node). URL choice per protocol: features/live/sources.py.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Property, QStandardPaths, Signal, Slot

from app.core.context import AppContext
from app.core.poller import Poller
from app.core.store import BaseStore
from app.features.live.sources import pick_sources, streams_by_profile

LAYOUTS = (1, 4, 9, 16)


class LiveStore(BaseStore):
    gridChanged = Signal()
    urlsChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self._layout, self._tiles = ctx.prefs.live_layout()
        self._selected = 0
        self._urls: dict[int, dict] = {}  # camera id -> {profile: {"rtsp": ..., "hls": ...}}
        self._url_errors: dict[int, str] = {}
        self._urls_revision = 0  # bumped on every URL change so QML bindings calling sources() re-run
        self.urlsChanged.connect(self._bump_revision)
        self._poller = Poller(self.refresh, 15, self)
        ctx.centralChanged.connect(self.refresh)
        self._poller.start()

    # ------------------------------------------------------------------ live URLs
    @Slot()
    def refresh(self) -> None:
        for camera_id in {t for t in self._tiles if t}:
            self.ensureUrls(camera_id, force=True)

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

        self.fetch(f"live-{camera_id}", lambda: self.api.live(camera_id).to_qml(), ok, track_error=False, on_err=err)

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

    @Slot(int)
    def setLayout(self, layout: int) -> None:
        if layout in LAYOUTS:
            self._layout = layout
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
        self.ensureUrls(camera_id)
        self._save()

    @Slot(int)
    def clearTile(self, index: int) -> None:
        self._tiles[index] = None
        self._save()

    @Slot()
    def clearAll(self) -> None:
        self._tiles = [None] * 16
        self._save()

    layout = Property(int, lambda self: self._layout, notify=gridChanged)
    selected = Property(int, lambda self: self._selected, notify=gridChanged)
    tiles = Property("QVariantList", lambda self: self._tiles[: self._layout], notify=gridChanged)
    onView = Property("QVariantList", lambda self: [t for t in self._tiles[: self._layout] if t], notify=gridChanged)

    # ------------------------------------------------------------------ snapshots
    @Slot(str, result=str)
    def snapshotPath(self, camera_name: str) -> str:
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)) / "Shah-NVR"
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in camera_name)
        return str(folder / f"{safe}_{datetime.now():%Y-%m-%d_%H-%M-%S}.png")
