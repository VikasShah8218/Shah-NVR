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
  `keep-open=yes` turns a dropped live stream into "paused at the end" instead of an end-file event,
  so the player also treats `eof-reached` as the end of a live stream.
* `suspended` (Live View grid behind the main-stream dialog): pausing stops reading, so the network
  and decoder are free for the big view, and the tile keeps its last frame. The node does not keep a
  paused reader (MediaMTX drops RTSP readers after ~10 s, idle HLS sessions after ~35 s), so on resume:
  RTSP paused <= RESUME_UNPAUSE_SECONDS just unpauses (it catches up to live); anything else reloads.
  For QUIET_RECONNECT_SECONDS after a resume, (re)connecting keeps the frozen frame and no
  "Connecting/Reconnecting" state; only a stream still without video after that shows "Reconnecting".
* "No picture" watchdog (live): every WATCHDOG_INTERVAL_MS the player checks when the last new frame arrived
  (libmpv's frame-ready callback or a moving time-pos; no pixel analysis, ~free). A stream that connected but
  delivers no frames for NO_PICTURE_SECONDS (LL-HLS: its buffer x2 + a margin) is treated like a dropped stream:
  "Reconnecting…" and a fresh connection with the normal backoff. Before this, such a stream stayed black forever.
  The same timer covers a load that waits for the render context ("render-ready"), which used to be a silent,
  overlay-less "idle" state. `reconnect()` (the ↻ button) drops the connection and starts a fresh one at once.
  The last state changes are kept per player and logged when the watchdog fires (diagnosis on real systems).
* Playback extras: `frameStep()` / `frameBackStep()` use mpv's exact frame stepping. Reverse play
  (`startReverse` / `stopReverse`) pauses and chains seeks backwards from a QTimer, anchored to wall
  time (maths in app/features/playback/transport.py); a tick waits for the previous seek to finish
  ("playback-restart"), so a slow decoder shows fewer frames instead of queueing seeks.

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
import time
from collections import deque
from datetime import timedelta
from functools import partial

import mpv
from PySide6.QtCore import Property, QCoreApplication, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication

from app.features.playback.transport import (
    REVERSE_TICK_MS, ReverseAnchor, reverse_done, reverse_target, seek_precision,
)
from app.video import render_mode
from app.video.profiles import BASE_OPTIONS, TIMELINE_EPOCH, options_for

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 30
RESUME_UNPAUSE_SECONDS = 8      # measured: MediaMTX drops a paused RTSP reader after ~10 s
QUIET_RECONNECT_SECONDS = 60    # after a resume, reconnect silently behind the frozen frame this long
QUIET_RETRY_SECONDS = 2
REVERSE_SEEK_TIMEOUT = 1.0      # give up waiting for a seek to finish after this (s) and seek again
WATCHDOG_INTERVAL_MS = 2000     # live: how often the "no picture" watchdog looks at the last frame time
NO_PICTURE_SECONDS = 8          # live RTSP: no new frame this long -> reconnect
NO_PICTURE_HLS_MARGIN = 4       # live LL-HLS: buffer x2 + this (the player fills its buffer before showing frames)
STATE_LOG_SIZE = 16             # recent state changes kept per player (logged on a watchdog reconnect)
OBSERVED_PROPERTIES = ("video-params", "hwdec-current", "time-pos", "duration", "pause", "speed", "eof-reached")


def _window_shown() -> bool:
    """Is any app window on screen (not minimized)? Without a GUI application (tests) assume yes."""
    if not isinstance(QCoreApplication.instance(), QGuiApplication):
        return True
    windows = QGuiApplication.topLevelWindows()
    return not windows or any(w.isExposed() for w in windows)


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
    liveBufferSecondsChanged = Signal()
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
    suspendedChanged = Signal()
    eofReached = Signal()
    reversingChanged = Signal()
    # for the surface (GUI thread)
    mpvCreated = Signal()  # the mpv.MPV now exists: create the render context
    frameReady = Signal()  # a new frame can be drawn
    renderWanted = Signal()  # a load waits for the render context: draw (create it) now

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = ""
        self._fallback_source = ""
        self._active_source = ""
        self._mode = "live"
        self._live_buffer_seconds = 5
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
        self._suspended = False
        self._suspended_at = 0.0
        self._reload_on_resume = False  # the stream ended/failed (or a load was due) while suspended
        self._quiet = False             # resumed: reconnect behind the frozen frame, no overlays
        self._quiet_time_pos: float | None = None
        self._last_progress = 0.0       # monotonic time of the last new frame (or of the last load)
        self._state_log: deque[tuple[float, str]] = deque(maxlen=STATE_LOG_SIZE)

        self._watchdog = QTimer(self)
        self._watchdog.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._watchdog_tick)

        self._quiet_timer = QTimer(self)
        self._quiet_timer.setSingleShot(True)
        self._quiet_timer.setInterval(QUIET_RECONNECT_SECONDS * 1000)
        self._quiet_timer.timeout.connect(self._quiet_expired)

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._load_active_source)

        # QML assigns properties one by one while creating the object: start playing once, after all
        # of them are set (the next event-loop turn), instead of on the first `source` assignment.
        self._play_timer = QTimer(self)
        self._play_timer.setSingleShot(True)
        self._play_timer.setInterval(0)
        self._play_timer.timeout.connect(self.play)

        self._reversing = False
        self._reverse_anchor: ReverseAnchor | None = None
        self._reverse_floor = 0.0           # playlist start (player seconds): reverse stops here
        self._reverse_seek_at: float | None = None  # monotonic time of the pending seek, None = none
        self._reverse_timer = QTimer(self)
        self._reverse_timer.setInterval(REVERSE_TICK_MS)
        self._reverse_timer.timeout.connect(self._reverse_tick)

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
            self._last_progress = time.monotonic()
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
                self._end_quiet()
        elif kind == "prop:hwdec-current":
            self._hwdec_current = payload or ""
            self.hwdecCurrentChanged.emit()
        elif kind == "prop:time-pos":
            if payload is not None:
                if float(payload) != self._time_pos:
                    self._last_progress = time.monotonic()
                self._time_pos = float(payload)
                self.timePosChanged.emit()
                if self._quiet and self._quiet_time_pos is not None and self._time_pos != self._quiet_time_pos:
                    self._end_quiet()  # new frames after an unpause
        elif kind == "prop:duration":
            self._duration = float(payload or 0)
            self.durationChanged.emit()
        elif kind == "prop:pause":
            self._paused = bool(payload)
            self.pausedChanged.emit()
            if not self._paused and self._reversing:
                self.stopReverse()  # play pressed: forward again
        elif kind == "prop:speed":
            self._speed = float(payload or 1)
            self.speedChanged.emit()
            if self._reversing:  # new rate: re-anchor so the speed changes from here
                self._reverse_anchor = ReverseAnchor(self._time_pos, time.monotonic(), self._speed)
        elif kind == "playback-restart":
            self._reverse_seek_at = None
            if not self._stopped:
                self._set_state("playing")
                self._end_quiet()
        elif kind == "prop:eof-reached":
            # keep-open=yes: a dropped live stream pauses at its end instead of sending end-file
            if payload and self._mode == "live" and not self._stopped and not self._retry_timer.isActive():
                self._on_end_file(mpv.MpvEventEndFile.EOF)
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
        if self._suspended:
            self._reload_on_resume = True  # reconnect when the grid is visible again
            return
        self._retry_live("Stream unavailable. Retrying…")

    def _retry_live(self, message: str) -> None:
        """Live: retry with backoff (switching to the fallback protocol if any)."""
        self._failures += 1
        if self._fallback_source and self._active_source != self._fallback_source:
            logger.info("Live stream failed, falling back to %s", self._fallback_source)
            self._set_active_source(self._fallback_source)
        if self._quiet:  # behind the frozen frame: retry quickly, show nothing yet
            self._retry_timer.start(QUIET_RETRY_SECONDS * 1000)
            return
        delay = min(MAX_BACKOFF_SECONDS, 2 * 2 ** min(self._failures - 1, 4))
        self._error_text = message
        self.errorTextChanged.emit()
        self._set_state("reconnecting")
        self._retry_timer.start(int(delay * 1000))

    # ------------------------------------------------------------------ "no picture" watchdog (live)
    def _no_picture_limit(self) -> float:
        if ".m3u8" in self._active_source.lower():
            return max(NO_PICTURE_SECONDS, self._live_buffer_seconds * 2 + NO_PICTURE_HLS_MARGIN)
        return NO_PICTURE_SECONDS

    @Slot()
    def _watchdog_tick(self) -> None:
        if self._mode != "live" or self._stopped or self._suspended or not self._active_source:
            self._watchdog.stop()
            return
        if self._quiet or self._retry_timer.isActive():  # the quiet window / a scheduled retry handles it
            return
        if not _window_shown():
            # Minimized: Qt draws nothing, so mpv may hold frames back. Not a dead stream: restart the clock.
            self._last_progress = time.monotonic()
            return
        idle = time.monotonic() - self._last_progress
        if idle < self._no_picture_limit():
            return
        logger.info("No picture for %.0f s from %s (state %s, render ready %s): reconnecting. Recent: %s",
                    idle, self._active_source, self._state, self._render_ready, self.timeline())
        if self.mpv is not None:
            self.mpv.command("stop")  # drop the dead connection now (frees the node's reader)
        self._last_progress = time.monotonic()
        self._retry_live("No picture. Reconnecting…")

    def timeline(self) -> str:
        """Recent state changes, e.g. "connecting@0.0s playing@0.8s reconnecting@31.2s"."""
        if not self._state_log:
            return "-"
        start = self._state_log[0][0]
        return " ".join(f"{state}@{at - start:.1f}s" for at, state in self._state_log)

    # ------------------------------------------------------------------ helpers
    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self._state_log.append((time.monotonic(), state))
            logger.debug("%s -> %s (%s)", id(self), state, self._active_source)
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
        for key, value in options_for(self._mode, render_mode.active(), self._active_source,
                                      self._live_buffer_seconds).items():
            try:
                self.mpv[key.replace("_", "-")] = value
            except Exception as exc:  # an option unknown to this libmpv build must not break playback
                logger.warning("mpv option %s=%s rejected: %s", key, value, exc)

    def _end_quiet(self) -> None:
        if self._quiet:
            self._quiet = False
            self._quiet_time_pos = None
            self._quiet_timer.stop()

    @Slot()
    def _quiet_expired(self) -> None:
        """No video QUIET_RECONNECT_SECONDS after a resume: show the reconnecting state from now on."""
        if not self._quiet:
            return
        self._quiet = False
        self._quiet_time_pos = None
        if self._stopped:
            return
        self._error_text = "Stream unavailable. Retrying…"
        self.errorTextChanged.emit()
        self._set_state("reconnecting")
        if not self._retry_timer.isActive():
            self._load_active_source()

    def _suspend(self) -> None:
        self._suspended = True
        self._suspended_at = time.monotonic()
        self._watchdog.stop()
        self._end_quiet()
        if self._retry_timer.isActive():  # failing stream: try again once the grid is visible
            self._retry_timer.stop()
            self._reload_on_resume = True
        if self.mpv is not None:
            self.mpv["pause"] = True

    def _resume(self) -> None:
        self._suspended = False
        if self._stopped or self.mpv is None:
            return
        paused_for = time.monotonic() - self._suspended_at
        is_hls = ".m3u8" in self._active_source.lower()
        self._quiet = True
        self._quiet_time_pos = self._time_pos
        self._quiet_timer.start()
        self._last_progress = time.monotonic()
        self._watchdog.start()
        if not self._reload_on_resume and not is_hls and paused_for <= RESUME_UNPAUSE_SECONDS:
            self.mpv["pause"] = False  # RTSP still connected: continues, catching up to live
            return
        # The node has dropped the paused reader (or HLS would stay behind live): reconnect from scratch,
        # keeping the last frame on screen until the new one arrives.
        self._reload_on_resume = False
        self._retry_timer.stop()
        self._failures = 0
        self._set_active_source(self._source)  # back to the preferred protocol
        self.mpv["pause"] = False
        self._load_active_source()

    @Slot()
    def _load_active_source(self) -> None:
        if self._stopped or not self._active_source:
            return
        if self._suspended:
            self._reload_on_resume = True
            return
        if not self._quiet:
            self._set_state("connecting" if self._failures == 0 else "reconnecting")
        if self._mode == "live":
            self._last_progress = time.monotonic()
            self._watchdog.start()
        if not self._render_ready:
            # mpv's video output needs the surface's render context first. Used to wait silently ("idle", no
            # overlay); now it shows "Connecting", asks the surface to draw, and the watchdog retries if it never comes.
            self.renderWanted.emit()
            return
        self._apply_mode_options()
        logger.debug("Loading %s (%s)", self._active_source, self._mode)
        self.mpv.loadfile(self._active_source)

    # ------------------------------------------------------------------ QML API
    @Slot()
    def play(self) -> None:
        """(Re)start the current source from scratch."""
        self._play_timer.stop()
        self.stopReverse()
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
    def reconnect(self) -> None:
        """↻: drop the current connection and start a fresh one now (preferred protocol, no backoff)."""
        if not self._source:
            return
        logger.info("Reconnect requested: %s (recent: %s)", self._source, self.timeline())
        self._end_quiet()
        self._reload_on_resume = False
        if self.mpv is not None:
            self.mpv.command("stop")
        self.play()

    @Slot()
    def stop(self) -> None:
        self.stopReverse()
        self._stopped = True
        self._retry_timer.stop()
        self._watchdog.stop()
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

    @Slot()
    def frameStep(self) -> None:
        """Pause and show the exact next frame."""
        self.stopReverse()
        if self.mpv is not None:
            self.mpv.command("frame-step")

    @Slot()
    def frameBackStep(self) -> None:
        """Pause and show the exact previous frame (mpv decodes from the previous keyframe)."""
        self.stopReverse()
        if self.mpv is not None:
            self.mpv.command("frame-back-step")

    @Slot(float)
    def startReverse(self, floor_epoch_ms: float) -> None:
        """Playback only: play backwards at the current speed until the playlist start (`floor_epoch_ms`)."""
        if self.mpv is None or self._mode != "playback" or self._reversing:
            return
        self._reverse_floor = max(0.0, floor_epoch_ms / 1000 - TIMELINE_EPOCH.timestamp())
        if reverse_done(self._time_pos, self._reverse_floor):
            return
        self.mpv["pause"] = True
        self._reverse_anchor = ReverseAnchor(self._time_pos, time.monotonic(), self._speed)
        self._reverse_seek_at = None
        self._reversing = True
        self._reverse_timer.start()
        self.reversingChanged.emit()

    @Slot()
    def stopReverse(self) -> None:
        if not self._reversing:
            return
        self._reversing = False
        self._reverse_timer.stop()
        self._reverse_anchor = None
        self.reversingChanged.emit()

    @Slot()
    def _reverse_tick(self) -> None:
        anchor = self._reverse_anchor
        if anchor is None or self.mpv is None:
            self.stopReverse()
            return
        now = time.monotonic()
        if self._reverse_seek_at is not None and now - self._reverse_seek_at < REVERSE_SEEK_TIMEOUT:
            return  # the previous seek is still decoding
        target = reverse_target(anchor, now, self._reverse_floor)
        self._reverse_seek_at = now
        self.mpv.seek(target, reference="absolute", precision=seek_precision(anchor.rate))
        if reverse_done(target, self._reverse_floor):
            self.stopReverse()

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
            self.stopReverse()
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

    def _get_live_buffer_seconds(self) -> int:
        return self._live_buffer_seconds

    def _set_live_buffer_seconds(self, value: int) -> None:
        value = max(2, min(10, int(value)))
        if value != self._live_buffer_seconds:
            self._live_buffer_seconds = value
            self.liveBufferSecondsChanged.emit()
            if (self._mode == "live" and ".m3u8" in self._active_source.lower()
                    and not self._stopped and self._render_ready):
                self._retry_timer.stop()
                self._load_active_source()

    def _get_suspended(self) -> bool:
        return self._suspended

    def _set_suspended(self, value: bool) -> None:
        value = bool(value)
        if value == self._suspended or self._mode != "live":
            return
        if value:
            self._suspend()
        else:
            self._resume()
        self.suspendedChanged.emit()

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
    liveBufferSeconds = Property(int, _get_live_buffer_seconds, _set_live_buffer_seconds,
                                 notify=liveBufferSecondsChanged)
    hwdec = Property(str, _get_hwdec, _set_hwdec, notify=hwdecChanged)
    paused = Property(bool, _get_paused, _set_paused, notify=pausedChanged)
    reversing = Property(bool, lambda self: self._reversing, notify=reversingChanged)
    suspended = Property(bool, _get_suspended, _set_suspended, notify=suspendedChanged)
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
