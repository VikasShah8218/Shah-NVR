"""MpvGlSurface (QML `MpvSurface` in GPU mode): draws an MpvPlayer with OpenGL.

`_Renderer` (QQuickFramebufferObject.Renderer) creates the mpv OpenGL render context on its first
render once the player's mpv exists, then calls `ctx.render(...)` into Qt's FBO for every frame.
Video frames never pass through Python: Python makes one small call per frame.

Rules learned the hard way (see docs/memory/11_desktop_nvr_desktop.md):
* Qt owns the FBO. Never override createFramebufferObject in Python (double free).
* Requires the OpenGL scene graph and the "basic" render loop (main.py): rendering runs on the GUI
  thread, so Python never runs on Qt's render thread (GIL deadlocks during grabWindow).
* Qt deletes the renderer with the GL context current; `__del__` frees the render context there.
  Qt may also replace a renderer while the surface lives: the player then waits for the next one
  ("render-lost" -> "render-ready").
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Property, QObject, Signal
from PySide6.QtGui import QOpenGLContext
from PySide6.QtQuick import QQuickFramebufferObject

from app.video.player import MpvPlayer, terminate_player
from app.video.render_context import GlRenderContext

logger = logging.getLogger(__name__)

_GL_COLOR_BUFFER_BIT = 0x4000


def _gl_get_proc_address(name: bytes) -> int:
    """OpenGL function lookup for libmpv, resolved in the current (Qt Quick) GL context."""
    context = QOpenGLContext.currentContext()
    if context is None:
        return 0
    address = context.getProcAddress(name)
    return int(address) if address else 0


class _Link:
    """What the renderer needs from the surface; a plain object so it outlives the surface safely."""

    def __init__(self):
        self.bridge = None  # MpvBridge of the bound player


class _Renderer(QQuickFramebufferObject.Renderer):
    """Draws mpv into the FBO that Qt creates and owns (the default createFramebufferObject)."""

    def __init__(self, link: _Link):
        super().__init__()
        self._link = link
        self._ctx: GlRenderContext | None = None
        self._bridge = None
        self._player = None

    def render(self) -> None:
        bridge = self._link.bridge
        if bridge is None or bridge.player is None:  # nothing to play yet: keep the surface transparent
            gl = QOpenGLContext.currentContext().functions()
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(_GL_COLOR_BUFFER_BIT)
            return
        if self._ctx is None:  # first frame with a player: the GL context is current here
            self._ctx = GlRenderContext(bridge.player, _gl_get_proc_address)
            self._bridge, self._player = bridge, bridge.player
            bridge.has_render_context = True
            self._ctx.set_update_callback(bridge.post_frame)
            bridge.post_event("render-ready")
        fbo = self.framebufferObject()
        self._ctx.render(fbo.handle(), fbo.width(), fbo.height())

    def __del__(self):
        # Runs when Qt deletes the renderer, with the GL context current.
        try:
            if self._ctx is None:
                return
            self._ctx.free()  # must happen before the player is destroyed
            self._ctx = None
            self._bridge.has_render_context = False
            if self._bridge.player_alive:
                self._bridge.post_event("render-lost")  # the player waits for the next renderer
            else:
                terminate_player(self._player, "after its GL render context")
        except Exception:  # never raise from a destructor
            logger.exception("Failed to release mpv render context")


class MpvGlSurface(QQuickFramebufferObject):
    playerChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player: MpvPlayer | None = None
        self._link = _Link()

    def createRenderer(self) -> QQuickFramebufferObject.Renderer:
        return _Renderer(self._link)

    def _get_player(self):
        return self._player

    def _set_player(self, player: QObject) -> None:
        if player is self._player:
            return
        if self._player is not None:
            logger.warning("MpvSurface: the player can be set only once")
            return
        self._player = player
        self._link.bridge = player.bridge
        player.mpvCreated.connect(self.update)  # the renderer creates the context on its next render
        player.frameReady.connect(self.update)
        self.playerChanged.emit()
        self.update()

    player = Property(QObject, _get_player, _set_player, notify=playerChanged)
