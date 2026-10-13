"""MpvVideoItem: a QML item that plays a stream with libmpv and draws it on the GPU.

How it works
------------
* Each item owns at most one `mpv.MPV` player, created on the first `play()` (empty grid tiles cost
  nothing). libmpv runs its own network + decode threads; hardware decoding via `hwdec`, CPU fallback
  built in.
* `_Renderer` (QQuickFramebufferObject.Renderer) creates the mpv OpenGL render context on its first
  render with a player, then calls `ctx.render(...)` into Qt's FBO for every frame. Video frames
  never pass through Python: Python makes one small call per frame.

Threads
-------
libmpv calls back from its own threads (frame ready, property changes, end of file). Those callbacks
never hand arguments to Qt: they append to a lock-protected queue in `_MpvBridge` and emit one
argument-less `wake` signal (queued to the GUI thread), where the item drains the queue.
The bridge is a child of the item, so it is always deleted on the GUI thread; it is closed (under
the lock) before that, so a late libmpv callback becomes a no-op instead of touching a dead object.

Lifetime
--------
libmpv requires: free the render context (with its GL context current) before destroying the player.
* Qt owns the renderer and deletes it with the GL context current; `_Renderer.__del__` frees the
  render context. Qt may also replace a renderer while the item lives (scene graph invalidated):
  the item then waits for the new renderer's context ("render-lost" -> "render-ready").
* The player is terminated exactly once, by whichever goes last: the item (if no renderer holds a
  render context) or the renderer (if the item is already gone).

Requires (set in main.py before the QGuiApplication exists):
* the OpenGL scene graph: QQuickWindow.setGraphicsApi(QSGRendererInterface.OpenGL);
* the "basic" render loop (QSG_RENDER_LOOP=basic): rendering runs on the GUI thread, so Python never
  runs on Qt's render thread and GIL deadlocks (e.g. during grabWindow) are impossible. mpv still
  decodes on its own threads.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import timedelta
from functools import partial

import mpv
from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QOpenGLContext
from PySide6.QtQml import QmlElement
from PySide6.QtQuick import QQuickFramebufferObject

from app.video.profiles import BASE_OPTIONS, TIMELINE_EPOCH, options_for
from app.video.render_context import GlRenderContext

logger = logging.getLogger(__name__)

QML_IMPORT_NAME = "Nvr.Video"
QML_IMPORT_MAJOR_VERSION = 1

MAX_BACKOFF_SECONDS = 30
OBSERVED_PROPERTIES = ("video-params", "hwdec-current", "time-pos", "duration", "pause", "speed")
_GL_COLOR_BUFFER_BIT = 0x4000


def _gl_get_proc_address(name: bytes) -> int:
    """OpenGL function lookup for libmpv, resolved in the current (Qt Quick) GL context."""
    context = QOpenGLContext.currentContext()
    if context is None:
        return 0
    address = context.getProcAddress(name)
    return int(address) if address else 0


def _log_mpv_message(level: str, prefix: str, text: str) -> None:
    logger.debug("mpv[%s] %s: %s", level, prefix, text.strip())


class _MpvBridge(QObject):
    """Hand-off between libmpv threads and the GUI thread, plus the state shared with the renderer."""

    wake = Signal()  # no arguments: nothing is converted or copied across threads

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self.player: mpv.MPV | None = None  # created lazily by the item (GUI thread)
        self.has_render_context = False     # GUI thread only (basic render loop)
        self.item_alive = True              # GUI thread only
        self._lock = threading.Lock()
        self._open = True
        self._frame = False
        self._events: deque[tuple[str, object]] = deque()
        self._woken = False

    # ---- any thread
    def post_frame(self) -> None:
        with self._lock:
            if self._open:
                self._frame = True
                self._wake_locked()

    def post_event(self, kind: str, payload=None) -> None:
        with self._lock:
            if self._open:
                self._events.append((kind, payload))
                self._wake_locked()

    def _wake_locked(self) -> None:
        if not self._woken:  # one queued wake-up per batch
            self._woken = True
            self.wake.emit()

    # ---- GUI thread
    def take(self) -> tuple[bool, list[tuple[str, object]]]:
        with self._lock:
            frame, events = self._frame, list(self._events)
            self._frame, self._woken = False, False
            self._events.clear()
        return frame, events

    def close(self) -> None:
        """After this, callbacks from libmpv threads do nothing (the QObject may be deleted next)."""
        with self._lock:
            self._open = False
            self._events.clear()


def _terminate(player: mpv.MPV | None, why: str) -> None:
    if player is not None:
        player.terminate()
        logger.debug("mpv player released (%s)", why)


class _Renderer(QQuickFramebufferObject.Renderer):
    """Draws mpv into the FBO that Qt creates and owns (the default createFramebufferObject).

    Not creating the FBO in Python is deliberate: PySide would leave a Python-created FBO owned by
    Python, and Qt deletes it too -> double free. Here Python never owns any GPU object.
    """

    def __init__(self, bridge: _MpvBridge):
        super().__init__()
        self._bridge = bridge
        self._ctx: GlRenderContext | None = None
        self._player: mpv.MPV | None = None

    def render(self) -> None:
        player = self._bridge.player
        if player is None:  # nothing to play yet: keep the surface transparent
            gl = QOpenGLContext.currentContext().functions()
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(_GL_COLOR_BUFFER_BIT)
            return
        if self._ctx is None:  # first frame with a player: the GL context is current here
            self._ctx = GlRenderContext(player, _gl_get_proc_address)
            self._player = player
            self._bridge.has_render_context = True
            self._ctx.set_update_callback(self._bridge.post_frame)
            self._bridge.post_event("render-ready")
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
            if self._bridge.item_alive:
                self._bridge.post_event("render-lost")  # the item waits for the next renderer
            else:
                _terminate(self._player, "after its render context")
        except Exception:  # never raise from a destructor
            logger.exception("Failed to release mpv render context")


def _on_item_destroyed(bridge: _MpvBridge, *_args) -> None:
    bridge.close()
    bridge.item_alive = False
    if not bridge.has_render_context:  # otherwise the renderer terminates it after freeing its context
        _terminate(bridge.player, "item destroyed")


def _forward_mpv_event(bridge: _MpvBridge, event) -> None:
    """libmpv event thread -> bridge queue (only the events the item cares about)."""
    event_id = event.event_id.value
    if event_id == mpv.MpvEventID.END_FILE:
        bridge.post_event("end-file", {"reason": event.data.reason, "error": event.data.error})
    elif event_id == mpv.MpvEventID.PLAYBACK_RESTART:
        bridge.post_event("playback-restart")


@QmlElement
class MpvVideoItem(QQuickFramebufferObject):
    sourceChanged = Signal()
    fallbackSourceChanged = Signal()
    modeChanged = Signal()
    hwdecChanged = Signal()
    playStateChanged = Signal()
    errorTextChanged = Signal()
    videoSizeChanged = Signal()
    hwdecCurrentChanged = Signal()
    timePosChanged = Signal()
    durationChanged = Signal()
    pausedChanged = Signal()
    speedChanged = Signal()
    activeSourceChanged = Signal()
    eofReached = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = ""
        self._fallback_source = ""
        self._active_source = ""
        self._mode = "live"
        self._hwdec = "auto-safe"
        self._state = "idle"  # idle | connecting | playing | reconnecting | error
        self._error_text = ""
        self._video_w = 0
        self._video_h = 0
        self._hwdec_current = ""
        self._time_pos = 0.0
        self._duration = 0.0
        self._paused = False
        self._speed = 1.0
        self._failures = 0
        self._stopped = True
        self._complete = False  # QML sets properties in any order; start only after all are set
        self._render_ready = False  # mpv's video output needs the render context before loadfile

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._load_active_source)

        self._bridge = _MpvBridge(self)
        self._bridge.wake.connect(self._drain, Qt.ConnectionType.QueuedConnection)
        self.destroyed.connect(partial(_on_item_destroyed, self._bridge))

    @property
    def player(self) -> mpv.MPV | None:
        return self._bridge.player

    def _ensure_player(self) -> mpv.MPV:
        if self._bridge.player is None:
            player = mpv.MPV(log_handler=_log_mpv_message, loglevel="warn", hwdec=self._hwdec, **BASE_OPTIONS)
            bridge = self._bridge  # callbacks capture the bridge, never the item
            for name in OBSERVED_PROPERTIES:
                player.observe_property(name, lambda prop, value, b=bridge: b.post_event("prop:" + prop, value))
            player.register_event_callback(partial(_forward_mpv_event, bridge))
            bridge.player = player
            self.update()  # let the renderer create the render context
        return self._bridge.player

    # ------------------------------------------------------------------ Qt Quick hooks
    def createRenderer(self) -> QQuickFramebufferObject.Renderer:
        return _Renderer(self._bridge)

    def componentComplete(self) -> None:
        super().componentComplete()
        self._complete = True
        if self._source:
            self.play()

    # ------------------------------------------------------------------ events (GUI thread)
    @Slot()
    def _drain(self) -> None:
        frame, events = self._bridge.take()
        for kind, payload in events:
            self._handle_mpv_event(kind, payload)
        if frame:
            self.update()

    def _handle_mpv_event(self, kind: str, payload) -> None:
        if kind == "render-ready":
            self._render_ready = True
            if not self._stopped:
                self._load_active_source()
        elif kind == "render-lost":
            self._render_ready = False  # the next renderer brings a new context ("render-ready")
            self.update()
        elif kind == "prop:video-params":
            w = int((payload or {}).get("w") or 0)
            h = int((payload or {}).get("h") or 0)
            if (w, h) != (self._video_w, self._video_h):
                self._video_w, self._video_h = w, h
                self.videoSizeChanged.emit()
            if w and not self._stopped:
                self._failures = 0
                self._set_state("playing")
        elif kind == "prop:hwdec-current":
            self._hwdec_current = payload or ""
            self.hwdecCurrentChanged.emit()
        elif kind == "prop:time-pos":
            if payload is not None:
                self._time_pos = float(payload)
                self.timePosChanged.emit()
        elif kind == "prop:duration":
            self._duration = float(payload or 0)
            self.durationChanged.emit()
        elif kind == "prop:pause":
            self._paused = bool(payload)
            self.pausedChanged.emit()
        elif kind == "prop:speed":
            self._speed = float(payload or 1)
            self.speedChanged.emit()
        elif kind == "playback-restart":
            if not self._stopped:
                self._set_state("playing")
        elif kind == "end-file":
            self._on_end_file(payload["reason"])

    def _on_end_file(self, reason: int) -> None:
        ignored = (mpv.MpvEventEndFile.RESTARTED, mpv.MpvEventEndFile.ABORTED,
                   mpv.MpvEventEndFile.QUIT, mpv.MpvEventEndFile.REDIRECT)
        if self._stopped or reason in ignored:
            return
        if self._mode == "playback":
            if reason == mpv.MpvEventEndFile.ERROR:
                self._set_error("Playback failed. The recording may be unavailable.")
            else:
                self.eofReached.emit()
            return
        # Live: the stream ended or failed -> retry with backoff (switching to the fallback if any).
        self._failures += 1
        if self._fallback_source and self._active_source != self._fallback_source:
            logger.info("Live stream failed, falling back to %s", self._fallback_source)
            self._set_active_source(self._fallback_source)
        delay = min(MAX_BACKOFF_SECONDS, 2 * 2 ** min(self._failures - 1, 4))
        self._error_text = "Stream unavailable. Retrying…"
        self.errorTextChanged.emit()
        self._set_state("reconnecting")
        self._retry_timer.start(int(delay * 1000))

    # ------------------------------------------------------------------ helpers
    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.playStateChanged.emit()
        if state == "playing" and self._error_text:
            self._error_text = ""
            self.errorTextChanged.emit()

    def _set_error(self, text: str) -> None:
        self._error_text = text
        self.errorTextChanged.emit()
        self._set_state("error")

    def _set_active_source(self, url: str) -> None:
        if url != self._active_source:
            self._active_source = url
            self.activeSourceChanged.emit()

    def _apply_mode_options(self) -> None:
        for key, value in options_for(self._mode).items():
            try:
                self.player[key.replace("_", "-")] = value
            except Exception as exc:  # an option unknown to this libmpv build must not break playback
                logger.warning("mpv option %s=%s rejected: %s", key, value, exc)

    @Slot()
    def _load_active_source(self) -> None:
        if self._stopped or not self._active_source or not self._render_ready:
            return
        self._set_state("connecting" if self._failures == 0 else "reconnecting")
        self._apply_mode_options()
        logger.debug("Loading %s (%s)", self._active_source, self._mode)
        self.player.loadfile(self._active_source)

    # ------------------------------------------------------------------ QML API
    @Slot()
    def play(self) -> None:
        """(Re)start the current source from scratch."""
        if not self._complete:
            return
        if not self._source:
            self.stop()
            return
        self._stopped = False
        self._failures = 0
        self._retry_timer.stop()
        self._set_active_source(self._source)
        self._ensure_player()
        self._load_active_source()

    @Slot()
    def stop(self) -> None:
        self._stopped = True
        self._retry_timer.stop()
        if self.player is not None:
            self.player.command("stop")
        self._set_state("idle")

    @Slot(float)
    def seekAbsolute(self, seconds: float) -> None:
        if self.player is not None:
            self.player.seek(seconds, reference="absolute", precision="exact")

    @Slot(float)
    def seekRelative(self, seconds: float) -> None:
        if self.player is not None:
            self.player.seek(seconds, reference="relative", precision="exact")

    @Slot(str, result=bool)
    def screenshot(self, path: str) -> bool:
        if self.player is None:
            return False
        try:
            self.player.command("screenshot-to-file", path, "video")
            return True
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)
            return False

    @Slot(result=float)
    def wallClockMs(self) -> float:
        """Playback only: real recorded time of the current frame, in ms since the Unix epoch."""
        return (TIMELINE_EPOCH + timedelta(seconds=self._time_pos)).timestamp() * 1000

    @Slot(float)
    def seekToWallClock(self, epoch_ms: float) -> None:
        """Playback only: seek to a real time inside the loaded playlist."""
        self.seekAbsolute(epoch_ms / 1000 - TIMELINE_EPOCH.timestamp())

    # ------------------------------------------------------------------ properties
    def _get_source(self) -> str:
        return self._source

    def _set_source(self, value: str) -> None:
        if value != self._source:
            self._source = value
            self.sourceChanged.emit()
            self.play()

    def _get_fallback(self) -> str:
        return self._fallback_source

    def _set_fallback(self, value: str) -> None:
        if value != self._fallback_source:
            self._fallback_source = value
            self.fallbackSourceChanged.emit()

    def _get_mode(self) -> str:
        return self._mode

    def _set_mode(self, value: str) -> None:
        if value in ("live", "playback") and value != self._mode:
            self._mode = value
            self.modeChanged.emit()

    def _get_hwdec(self) -> str:
        return self._hwdec

    def _set_hwdec(self, value: str) -> None:
        if value and value != self._hwdec:
            self._hwdec = value
            if self.player is not None:
                self.player["hwdec"] = value
            self.hwdecChanged.emit()

    def _get_paused(self) -> bool:
        return self._paused

    def _set_paused(self, value: bool) -> None:
        if self.player is not None:
            self.player["pause"] = bool(value)

    def _get_speed(self) -> float:
        return self._speed

    def _set_speed(self, value: float) -> None:
        if self.player is not None:
            self.player["speed"] = float(value)

    source = Property(str, _get_source, _set_source, notify=sourceChanged)
    fallbackSource = Property(str, _get_fallback, _set_fallback, notify=fallbackSourceChanged)
    mode = Property(str, _get_mode, _set_mode, notify=modeChanged)
    hwdec = Property(str, _get_hwdec, _set_hwdec, notify=hwdecChanged)
    paused = Property(bool, _get_paused, _set_paused, notify=pausedChanged)
    speed = Property(float, _get_speed, _set_speed, notify=speedChanged)
    # not "state": QQuickItem already has a `state` property (QML states) that would shadow it
    playState = Property(str, lambda self: self._state, notify=playStateChanged)
    errorText = Property(str, lambda self: self._error_text, notify=errorTextChanged)
    videoWidth = Property(int, lambda self: self._video_w, notify=videoSizeChanged)
    videoHeight = Property(int, lambda self: self._video_h, notify=videoSizeChanged)
    hwdecCurrent = Property(str, lambda self: self._hwdec_current, notify=hwdecCurrentChanged)
    timePos = Property(float, lambda self: self._time_pos, notify=timePosChanged)
    duration = Property(float, lambda self: self._duration, notify=durationChanged)
    activeSource = Property(str, lambda self: self._active_source, notify=activeSourceChanged)
