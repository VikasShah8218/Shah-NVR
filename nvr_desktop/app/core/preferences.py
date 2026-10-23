"""User preferences stored with QSettings (the desktop equivalent of the web client's localStorage).

QML singleton `Prefs`. Every preference is a property with a change signal, so UI bindings and stores
react immediately (e.g. changing the central URL reconnects all stores).
"""

from __future__ import annotations

import json

from PySide6.QtCore import Property, QObject, QRect, QSettings, Signal, Slot

from settings.settings import settings

LIVE_PROTOCOLS = ("auto", "rtsp", "hls")
RENDER_MODES = ("auto", "cpu", "gpu")  # see app/video/render_mode.py
NODE_ACCESS_MODES = ("auto", "lan", "public")
DEFAULT_TILES = [None] * 16


class Preferences(QObject):
    centralUrlChanged = Signal()
    pollSecondsChanged = Signal()
    liveProtocolChanged = Signal()
    hlsBufferSecondsChanged = Signal()
    hwdecChanged = Signal()
    sidebarCollapsedChanged = Signal()
    renderModeChanged = Signal()
    nodeAccessChanged = Signal()
    liveVolumeChanged = Signal()
    playbackVolumeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = QSettings("ShahNVR", "Desktop")
        self._active_render_mode = "gpu"  # set by main.py at startup; fixed for this process
        self._render_mode_at_start = "auto"

    # ------------------------------------------------------------------ helpers
    def _get(self, key: str, default, kind=str):
        value = self._store.value(key, default)
        if kind is bool:
            return value in (True, "true", "1", 1)
        try:
            return kind(value)
        except (TypeError, ValueError):
            return default

    def _set(self, key: str, value, signal: Signal) -> None:
        if self._store.value(key) != value:
            self._store.setValue(key, value)
            signal.emit()

    # ------------------------------------------------------------------ central URL
    def _get_central_url(self) -> str:
        return self._get("centralUrl", settings.CENTRAL_URL)

    def _set_central_url(self, value: str) -> None:
        self._set("centralUrl", value.strip().rstrip("/"), self.centralUrlChanged)

    # ------------------------------------------------------------------ display
    def _get_poll(self) -> int:
        return self._get("pollSeconds", 5, int)

    def _set_poll(self, value: int) -> None:
        self._set("pollSeconds", int(value), self.pollSecondsChanged)

    def _get_protocol(self) -> str:
        value = self._get("liveProtocol", "auto")
        return value if value in LIVE_PROTOCOLS else "auto"

    def _set_protocol(self, value: str) -> None:
        if value in LIVE_PROTOCOLS:
            self._set("liveProtocol", value, self.liveProtocolChanged)

    def _get_hls_buffer(self) -> int:
        return max(2, min(10, self._get("hlsBufferSeconds", 5, int)))

    def _set_hls_buffer(self, value: int) -> None:
        self._set("hlsBufferSeconds", max(2, min(10, int(value))), self.hlsBufferSecondsChanged)

    def _get_hwdec(self) -> str:
        return self._get("hwdec", "auto-safe")

    def _set_hwdec(self, value: str) -> None:
        self._set("hwdec", value, self.hwdecChanged)

    def _get_render_mode(self) -> str:
        value = self._get("renderMode", "auto")
        return value if value in RENDER_MODES else "auto"

    def _set_render_mode(self, value: str) -> None:
        if value in RENDER_MODES:
            self._set("renderMode", value, self.renderModeChanged)  # applies after a restart

    def set_active_render_mode(self, mode: str) -> None:
        self._active_render_mode = mode
        self._render_mode_at_start = self._get_render_mode()

    def _get_sidebar(self) -> bool:
        return self._get("sidebarCollapsed", False, bool)

    def _set_sidebar(self, value: bool) -> None:
        self._set("sidebarCollapsed", bool(value), self.sidebarCollapsedChanged)

    def _get_node_access(self) -> str:
        value = self._get("nodeAccess", "auto")
        return value if value in NODE_ACCESS_MODES else "auto"

    def _set_node_access(self, value: str) -> None:
        if value in NODE_ACCESS_MODES:
            self._set("nodeAccess", value, self.nodeAccessChanged)

    def _get_live_volume(self) -> float:
        return max(0.0, min(1.0, self._get("liveVolume", 0.8, float)))

    def _set_live_volume(self, value: float) -> None:
        self._set("liveVolume", max(0.0, min(1.0, float(value))), self.liveVolumeChanged)

    def _get_playback_volume(self) -> float:
        return max(0.0, min(1.0, self._get("playbackVolume", 0.8, float)))

    def _set_playback_volume(self, value: float) -> None:
        self._set("playbackVolume", max(0.0, min(1.0, float(value))), self.playbackVolumeChanged)

    centralUrl = Property(str, _get_central_url, _set_central_url, notify=centralUrlChanged)
    pollSeconds = Property(int, _get_poll, _set_poll, notify=pollSecondsChanged)
    liveProtocol = Property(str, _get_protocol, _set_protocol, notify=liveProtocolChanged)
    hlsBufferSeconds = Property(int, _get_hls_buffer, _set_hls_buffer, notify=hlsBufferSecondsChanged)
    hwdec = Property(str, _get_hwdec, _set_hwdec, notify=hwdecChanged)
    sidebarCollapsed = Property(bool, _get_sidebar, _set_sidebar, notify=sidebarCollapsedChanged)
    renderMode = Property(str, _get_render_mode, _set_render_mode, notify=renderModeChanged)
    activeRenderMode = Property(str, lambda self: self._active_render_mode, constant=True)
    renderModeAtStart = Property(str, lambda self: self._render_mode_at_start, constant=True)
    nodeAccess = Property(str, _get_node_access, _set_node_access, notify=nodeAccessChanged)
    liveVolume = Property(float, _get_live_volume, _set_live_volume, notify=liveVolumeChanged)
    playbackVolume = Property(float, _get_playback_volume, _set_playback_volume, notify=playbackVolumeChanged)

    # ------------------------------------------------------------------ live grid (used by LiveStore)
    def live_layout(self) -> tuple[int, list[int | None]]:
        layout = self._get("live/layout", 4, int)
        try:
            tiles = json.loads(self._store.value("live/tiles", "null")) or DEFAULT_TILES
        except (TypeError, ValueError):
            tiles = DEFAULT_TILES
        tiles = (list(tiles) + DEFAULT_TILES)[:16]
        return (layout if layout in (1, 4, 9, 16) else 4), tiles

    def save_live_layout(self, layout: int, tiles: list[int | None]) -> None:
        self._store.setValue("live/layout", int(layout))
        self._store.setValue("live/tiles", json.dumps(tiles))

    # ------------------------------------------------------------------ window state
    def window_state(self) -> tuple[QRect | None, bool]:
        """(last normal geometry or None, was maximized)."""
        geometry = self._store.value("window/geometry")
        maximized = self._store.value("window/maximized", False, type=bool)
        return (geometry if isinstance(geometry, QRect) and geometry.isValid() else None), maximized

    def save_window_state(self, geometry: QRect | None, maximized: bool) -> None:
        if geometry is not None:
            self._store.setValue("window/geometry", geometry)
        self._store.setValue("window/maximized", bool(maximized))

    @Slot()
    def reset(self) -> None:
        self._store.clear()
        for signal in (self.centralUrlChanged, self.pollSecondsChanged, self.liveProtocolChanged,
                       self.hlsBufferSecondsChanged,
                       self.hwdecChanged, self.sidebarCollapsedChanged,
                       self.renderModeChanged, self.nodeAccessChanged, self.liveVolumeChanged,
                       self.playbackVolumeChanged):
            signal.emit()
