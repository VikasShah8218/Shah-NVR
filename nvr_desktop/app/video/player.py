"""MpvPlayer: one libmpv player and everything about playing a stream, except drawing it.

Drawing is done by a surface (QML type `MpvSurface`) bound to the player:
* GPU mode: app/video/gl_surface.py (OpenGL, Qt Quick FBO);
* CPU mode: app/video/sw_surface.py (libswscale into memory, Qt Quick software renderer).
The QML API is identical in both modes; ui/video/VideoView.qml pairs one player with one surface.

How it works
------------
* The `mpv.MPV` is created on the first `play()`, so empty grid tiles cost nothing. libmpv runs its
  own network + decode threads.
* A source starts loading only once the surface has created mpv's render context ("render-ready"):
  mpv's video output (vo=libmpv) needs it before `loadfile`.
* Live mode reconnects by itself (backoff 2 s, 4 s, 8 s ... max 30 s, reset once frames arrive) and,
  when `fallbackSource` is set (Auto protocol), switches RTSP -> LL-HLS after the first failure.

Threads
-------
libmpv calls back from its own threads (frame ready, property changes, end of file). Those callbacks
never hand arguments to Qt: they append to a lock-protected queue in `MpvBridge` and emit one
argument-less `wake` signal (queued to the GUI thread), where the player drains the queue.
The bridge is a child of the player, so it is always deleted on the GUI thread; it is closed (under
the lock) before that, so a late libmpv callback becomes a no-op instead of touching a dead object.

Lifetime
--------
libmpv requires: free the render context before destroying the player. The render context belongs
to the surface. The `mpv.MPV` is terminated exactly once, by whichever goes last:
* the player, when it is destroyed and no render context exists (`bridge.has_render_context`);
* otherwise the surface, right after freeing its render context (`bridge.player_alive` is False).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import timedelta
from functools import partial

import mpv
from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot

from app.video import render_mode
from app.video.profiles import BASE_OPTIONS, TIMELINE_EPOCH, options_for

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 30
OBSERVED_PROPERTIES = ("video-params", "hwdec-current", "time-pos", "duration", "pause", "speed")


def _log_mpv_message(level: str, prefix: str, text: str) -> None:
    logger.debug("mpv[%s] %s: %s", level, prefix, text.strip())


class MpvBridge(QObject):
    """Hand-off between libmpv threads and the GUI thread, plus the state the surface shares."""

    wake = Signal()  # no arguments: nothing is converted or copied across threads

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self.player: mpv.MPV | None = None  # created lazily (GUI thread)
        self.has_render_context = False     # GUI thread only
        self.player_alive = True            # GUI thread only
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


def terminate_player(player: mpv.MPV | None, why: str) -> None:
    if player is not None:
        player.terminate()
        logger.debug("mpv player released (%s)", why)


def _on_player_destroyed(bridge: MpvBridge, *_args) -> None:
    bridge.close()
    bridge.player_alive = False
    if not bridge.has_render_context:  # otherwise the surface terminates it after freeing its context
        terminate_player(bridge.player, "player destroyed")


def _forward_mpv_event(bridge: MpvBridge, event) -> None:
    """libmpv event thread -> bridge queue (only the events the player cares about)."""
    event_id = event.event_id.value
    if event_id == mpv.MpvEventID.END_FILE:
        bridge.post_event("end-file", {"reason": event.data.reason, "error": event.data.error})
    elif event_id == mpv.MpvEventID.PLAYBACK_RESTART:
        bridge.post_event("playback-restart")


class MpvPlayer(QObject):
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
    mutedChanged = Signal()
    volumeChanged = Signal()
    activeSourceChanged = Signal()
    eofReached = Signal()
    # for the surface (GUI thread)
    mpvCreated = Signal()  # the mpv.MPV now exists: create the render context
    frameReady = Signal()  # a new frame can be drawn

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
        self._muted = True
        self._volume = 0.8
        self._failures = 0
        self._stopped = True
        self._render_ready = False  # mpv's video output needs the render context before loadfile

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._load_active_source)

        # QML assigns properties one by one while creating the object: start playing once, after all
        # of them are set (the next event-loop turn), instead of on the first `source` assignment.
        self._play_timer = QTimer(self)
        self._play_timer.setSingleShot(True)
        self._play_timer.setInterval(0)
        self._play_timer.timeout.connect(self.play)

        self.bridge = MpvBridge(self)
        self.bridge.wake.connect(self._drain, Qt.ConnectionType.QueuedConnection)
        self.destroyed.connect(partial(_on_player_destroyed, self.bridge))

    @property
    def mpv(self) -> mpv.MPV | None:
        return self.bridge.player

    def _hwdec_option(self) -> str:
        return "no" if render_mode.active() == "cpu" else self._hwdec  # CPU mode decodes on the processor

    def _ensure_mpv(self) -> mpv.MPV:
        if self.bridge.player is None:
            player = mpv.MPV(log_handler=_log_mpv_message, loglevel="warn", hwdec=self._hwdec_option(), **BASE_OPTIONS)
            player["mute"] = self._muted
            player["volume"] = self._volume * 100
            bridge = self.bridge  # callbacks capture the bridge, never the player object
            for name in OBSERVED_PROPERTIES:
                player.observe_property(name, lambda prop, value, b=bridge: b.post_event("prop:" + prop, value))
            player.register_event_callback(partial(_forward_mpv_event, bridge))
            bridge.player = player
            self.mpvCreated.emit()
        return self.bridge.player

    # ------------------------------------------------------------------ events (GUI thread)
    @Slot()
    def _drain(self) -> None:
        frame, events = self.bridge.take()
        for kind, payload in events:
            self._handle_mpv_event(kind, payload)
        if frame:
            self.frameReady.emit()

    def _handle_mpv_event(self, kind: str, payload) -> None:
        if kind == "render-ready":
            self._render_ready = True
            if not self._stopped:
                self._load_active_source()
        elif kind == "render-lost":
            self._render_ready = False  # the surface brings a new context ("render-ready")
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
        for key, value in options_for(self._mode, render_mode.active()).items():
            try:
                self.mpv[key.replace("_", "-")] = value
            except Exception as exc:  # an option unknown to this libmpv build must not break playback
                logger.warning("mpv option %s=%s rejected: %s", key, value, exc)

    @Slot()
    def _load_active_source(self) -> None:
        if self._stopped or not self._active_source or not self._render_ready:
            return
        self._set_state("connecting" if self._failures == 0 else "reconnecting")
        self._apply_mode_options()
        logger.debug("Loading %s (%s)", self._active_source, self._mode)
        self.mpv.loadfile(self._active_source)

    # ------------------------------------------------------------------ QML API
    @Slot()
    def play(self) -> None:
        """(Re)start the current source from scratch."""
        self._play_timer.stop()
        if not self._source:
            self.stop()
            return
        self._stopped = False
        self._failures = 0
        self._retry_timer.stop()
        self._set_active_source(self._source)
        self._ensure_mpv()
        self._load_active_source()

    @Slot()
    def stop(self) -> None:
        self._stopped = True
        self._retry_timer.stop()
        if self.mpv is not None:
            self.mpv.command("stop")
        self._set_state("idle")

    @Slot(float)
    def seekAbsolute(self, seconds: float) -> None:
        if self.mpv is not None:
            self.mpv.seek(seconds, reference="absolute", precision="exact")

    @Slot(float)
    def seekRelative(self, seconds: float) -> None:
        if self.mpv is not None:
            self.mpv.seek(seconds, reference="relative", precision="exact")

    @Slot(str, result=bool)
    def screenshot(self, path: str) -> bool:
        if self.mpv is None:
            return False
        try:
            self.mpv.command("screenshot-to-file", path, "video")
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
            self._play_timer.start()

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
            if self.mpv is not None:
                self.mpv["hwdec"] = self._hwdec_option()
            self.hwdecChanged.emit()

    def _get_paused(self) -> bool:
        return self._paused

    def _set_paused(self, value: bool) -> None:
        if self.mpv is not None:
            self.mpv["pause"] = bool(value)

    def _get_speed(self) -> float:
        return self._speed

    def _set_speed(self, value: float) -> None:
        if self.mpv is not None:
            self.mpv["speed"] = float(value)

    def _get_muted(self) -> bool:
        return self._muted

    def _set_muted(self, value: bool) -> None:
        value = bool(value)
        if value != self._muted:
            self._muted = value
            if self.mpv is not None:
                self.mpv["mute"] = value
            self.mutedChanged.emit()

    def _get_volume(self) -> float:
        return self._volume

    def _set_volume(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if value != self._volume:
            self._volume = value
            if self.mpv is not None:
                self.mpv["volume"] = value * 100
            self.volumeChanged.emit()

    source = Property(str, _get_source, _set_source, notify=sourceChanged)
    fallbackSource = Property(str, _get_fallback, _set_fallback, notify=fallbackSourceChanged)
    mode = Property(str, _get_mode, _set_mode, notify=modeChanged)
    hwdec = Property(str, _get_hwdec, _set_hwdec, notify=hwdecChanged)
    paused = Property(bool, _get_paused, _set_paused, notify=pausedChanged)
    speed = Property(float, _get_speed, _set_speed, notify=speedChanged)
    muted = Property(bool, _get_muted, _set_muted, notify=mutedChanged)
    volume = Property(float, _get_volume, _set_volume, notify=volumeChanged)
    # not "state": a QQuickItem has a `state` property (QML states); keep the same name everywhere
    playState = Property(str, lambda self: self._state, notify=playStateChanged)
    errorText = Property(str, lambda self: self._error_text, notify=errorTextChanged)
    videoWidth = Property(int, lambda self: self._video_w, notify=videoSizeChanged)
    videoHeight = Property(int, lambda self: self._video_h, notify=videoSizeChanged)
    hwdecCurrent = Property(str, lambda self: self._hwdec_current, notify=hwdecCurrentChanged)
    timePos = Property(float, lambda self: self._time_pos, notify=timePosChanged)
    duration = Property(float, lambda self: self._duration, notify=durationChanged)
    activeSource = Property(str, lambda self: self._active_source, notify=activeSourceChanged)
