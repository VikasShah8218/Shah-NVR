"""MpvSwSurface (QML `MpvSurface` in CPU mode): draws an MpvPlayer without any GPU.

The Chrome approach: each decoded frame is converted (YUV -> RGB) and scaled to the tile's pixel size
in a single libswscale pass, then Qt's software renderer repaints only this tile.

    libmpv update callback --(Event)--> render worker thread --(post_frame)--> GUI: update() -> paint()
                                        ctx.update() / ctx.render()
                                        into the back buffer, swap

* One worker thread per surface. The render call releases the GIL, so tiles convert in parallel on
  several cores and the GUI thread never waits for video.
* Two buffers (front / back), each a 64-byte-aligned block wrapped by a QImage (RGBX8888 = mpv "rgb0").
  The worker renders into the back buffer and swaps under a lock; paint() draws the front one.
* The update callback only sets an Event: libmpv forbids calling it back from inside the callback.
* No letterbox bars from mpv: it clears bars to 0,0,0,0, which Qt's RGBX format shows as transparent.
  The worker renders into a buffer with exactly the picture's aspect ratio (mpv runs with
  keepaspect=no, see profiles.CPU_RENDER_OPTIONS) and paint() centres it on the background colour.

Lifetime (same rule as GPU mode, see player.py): the render context is freed before the mpv player is
destroyed. On teardown the worker is stopped and joined first, so nothing renders while freeing.
"""

from __future__ import annotations

import ctypes
import logging
import threading

from PySide6.QtCore import Property, QObject, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtQuick import QQuickPaintedItem

from app.video.player import MpvPlayer, terminate_player
from app.video.render_context import UPDATE_FRAME, SwRenderContext

logger = logging.getLogger(__name__)

_ALIGN = 64
_BACKGROUND = QColor("#1f232b")  # Theme.video


class _Frame:
    """A width x height RGBX image in a 64-byte-aligned buffer that libmpv writes into directly."""

    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.stride = (width * 4 + _ALIGN - 1) // _ALIGN * _ALIGN
        size = self.stride * height
        self._raw = (ctypes.c_ubyte * (size + _ALIGN))()
        self.pointer = (ctypes.addressof(self._raw) + _ALIGN - 1) // _ALIGN * _ALIGN
        self._view = (ctypes.c_ubyte * size).from_address(self.pointer)
        self.image = QImage(self._view, width, height, self.stride, QImage.Format.Format_RGBX8888)


class _SwState:
    """Everything the worker uses: a plain object, so the worker never touches the QML item."""

    def __init__(self):
        self.bridge = None
        self.ctx: SwRenderContext | None = None
        self.wake = threading.Event()
        self.stopping = False
        self.thread: threading.Thread | None = None
        self.lock = threading.Lock()
        self.front: _Frame | None = None
        self.back: _Frame | None = None
        self.target = (0, 0)  # pixel size of the item (set on the GUI thread)
        self.ratio = 1.0      # device pixels per item unit


def _fit(video: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]:
    """Largest size with the video's aspect ratio that fits in `box` (pixels)."""
    (vw, vh), (bw, bh) = video, box
    if vw <= 0 or vh <= 0:
        return box
    scale = min(bw / vw, bh / vh)
    return max(1, round(vw * scale)), max(1, round(vh * scale))


def _display_size(player) -> tuple[int, int]:
    """The video's display size (after pixel aspect), (0, 0) until known. Thread-safe libmpv query."""
    try:
        return int(player.dwidth or 0), int(player.dheight or 0)
    except Exception:
        return 0, 0


def _render_loop(state: _SwState) -> None:
    drawn_size = (0, 0)
    while True:
        state.wake.wait()
        state.wake.clear()
        if state.stopping:
            return
        flags = state.ctx.update()
        box = state.target
        if box[0] <= 0 or box[1] <= 0:
            continue
        width, height = _fit(_display_size(state.bridge.player), box)
        if not (flags & UPDATE_FRAME) and (width, height) == drawn_size:
            continue  # nothing new to show
        back = state.back
        if back is None or (back.width, back.height) != (width, height):
            back = _Frame(width, height)
        state.ctx.render(back.pointer, width, height, back.stride)
        drawn_size = (width, height)
        with state.lock:
            state.back, state.front = state.front, back
        state.bridge.post_frame()  # -> player.frameReady -> surface.update() on the GUI thread


def _teardown(state: _SwState, *_args) -> None:
    """Surface destroyed (GUI thread): stop the worker, free the render context, maybe end the player."""
    if state.thread is not None:
        state.stopping = True
        state.wake.set()
        state.thread.join()
    if state.ctx is not None:
        state.ctx.free()
        state.ctx = None
        bridge = state.bridge
        bridge.has_render_context = False
        if bridge.player_alive:
            bridge.post_event("render-lost")
        else:
            terminate_player(bridge.player, "after its SW render context")


class MpvSwSurface(QQuickPaintedItem):
    playerChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player: MpvPlayer | None = None
        self._state = _SwState()
        self.setOpaquePainting(True)
        self.setFillColor(_BACKGROUND)
        self.setAntialiasing(False)
        self.destroyed.connect(lambda *_a, s=self._state: _teardown(s))

    # ------------------------------------------------------------------ player binding
    def _get_player(self):
        return self._player

    def _set_player(self, player: QObject) -> None:
        if player is self._player:
            return
        if self._player is not None:
            logger.warning("MpvSurface: the player can be set only once")
            return
        self._player = player
        self._state.bridge = player.bridge
        player.mpvCreated.connect(self._create_context)
        player.frameReady.connect(self.update)
        self.playerChanged.emit()
        if player.bridge.player is not None:
            self._create_context()

    player = Property(QObject, _get_player, _set_player, notify=playerChanged)

    def _create_context(self) -> None:
        state = self._state
        if state.ctx is not None or state.bridge is None or state.bridge.player is None:
            return
        state.ctx = SwRenderContext(state.bridge.player)
        state.bridge.has_render_context = True
        state.ctx.set_update_callback(state.wake.set)
        self._update_target()
        state.thread = threading.Thread(target=_render_loop, args=(state,), name="mpv-sw-render", daemon=True)
        state.thread.start()
        state.bridge.post_event("render-ready")

    # ------------------------------------------------------------------ size
    def _pixel_ratio(self) -> float:
        # Never call self.window() from Python here: PySide ties the returned QQuickWindow wrapper to
        # this item and the *window* gets deleted together with the tile (seen as the whole app window
        # vanishing when a tile is removed). The screen under the tile gives the same ratio.
        screen = QGuiApplication.screenAt(self.mapToGlobal(QPointF(0, 0)).toPoint()) or QGuiApplication.primaryScreen()
        return screen.devicePixelRatio() if screen is not None else 1.0

    def _update_target(self) -> None:
        ratio = self._pixel_ratio()
        target = (max(0, round(self.width() * ratio)), max(0, round(self.height() * ratio)))
        if target != self._state.target:
            self._state.ratio = ratio or 1.0
            self._state.target = target
            self._state.wake.set()  # redraw the current frame at the new size

    def geometryChange(self, new_geometry, old_geometry) -> None:
        super().geometryChange(new_geometry, old_geometry)
        self._update_target()

    # ------------------------------------------------------------------ painting (GUI thread)
    def paint(self, painter: QPainter) -> None:
        state = self._state
        with state.lock:
            frame = state.front
            if frame is None:
                return
            w, h = frame.width / state.ratio, frame.height / state.ratio  # centred, already at pixel size
            painter.drawImage(QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), frame.image)
