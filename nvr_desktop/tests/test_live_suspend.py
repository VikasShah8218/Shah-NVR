"""Live tiles paused behind the main-stream dialog, quiet resume, and the keep-open reconnect fix
(app/video/player.py: MpvPlayer.suspended, eof-reached). Uses a fake mpv, no network."""

import pytest

from settings.settings import settings

if not (settings.MPV_DLL_DIR / "libmpv-2.dll").exists():
    pytest.skip("libmpv-2.dll not installed (see README)", allow_module_level=True)

from app.video.loader import prepare_libmpv  # noqa: E402

prepare_libmpv(settings.MPV_DLL_DIR)

import mpv  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.video import player as player_mod  # noqa: E402
from app.video.player import MpvPlayer  # noqa: E402

RTSP = "rtsp://node:8554/cam-1/sub"
HLS = "http://node:8888/cam-1/sub/index.m3u8"


class FakeMpv(dict):
    def __init__(self):
        super().__init__(pause=False)
        self.loads = []

    def loadfile(self, url):
        self.loads.append(url)

    def command(self, *args):
        pass


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(player_mod.time, "monotonic", lambda: now["t"])
    return now


def playing(source=RTSP, fallback=""):
    """A live player that is playing `source` (the fake stands in for libmpv)."""
    p = MpvPlayer()
    fake = FakeMpv()
    p.bridge.player = fake
    p._source = source
    p._fallback_source = fallback
    p._active_source = source
    p._stopped = False
    p._render_ready = True
    p._handle_mpv_event("prop:video-params", {"w": 640, "h": 360})
    p._handle_mpv_event("prop:time-pos", 10.0)
    assert p.playState == "playing"
    return p, fake


def test_suspend_pauses_and_short_rtsp_resume_just_unpauses(clock):
    p, fake = playing()
    p.suspended = True
    assert fake["pause"] is True
    clock["t"] += 5
    p.suspended = False
    assert fake["pause"] is False
    assert fake.loads == []                      # still connected: no reconnect
    assert p.playState == "playing"
    p._handle_mpv_event("prop:time-pos", 10.2)   # new frames end the quiet window
    assert not p._quiet


def test_long_rtsp_pause_reloads_quietly_behind_the_frozen_frame(clock):
    p, fake = playing()
    p.suspended = True
    clock["t"] += 60                             # MediaMTX dropped the reader long ago
    p.suspended = False
    assert fake.loads == [RTSP]
    assert fake["pause"] is False
    assert p.playState == "playing"              # no "Connecting…" overlay
    p._handle_mpv_event("playback-restart", None)
    assert not p._quiet and p.playState == "playing"


def test_hls_always_reloads_to_the_live_edge(clock):
    p, fake = playing(HLS)
    p.suspended = True
    clock["t"] += 2
    p.suspended = False
    assert fake.loads == [HLS]


def test_stream_lost_while_suspended_reconnects_only_on_resume(clock):
    p, fake = playing(RTSP, fallback=HLS)
    p.suspended = True
    p._handle_mpv_event("end-file", {"reason": mpv.MpvEventEndFile.ERROR})
    assert not p._retry_timer.isActive() and fake.loads == []
    clock["t"] += 3                              # short, but the connection is gone: reload
    p.suspended = False
    assert fake.loads == [RTSP]                  # back to the preferred protocol, not the fallback


def test_failures_after_resume_stay_quiet_until_the_window_expires(clock):
    p, fake = playing()
    p.suspended = True
    clock["t"] += 60
    p.suspended = False
    p._handle_mpv_event("end-file", {"reason": mpv.MpvEventEndFile.ERROR})
    assert p.playState == "playing" and p.errorText == ""
    assert p._retry_timer.interval() == player_mod.QUIET_RETRY_SECONDS * 1000
    p._quiet_expired()                           # 60 s without video
    assert p.playState == "reconnecting"
    assert "Retrying" in p.errorText


def test_eof_reached_reconnects_a_live_stream():
    """keep-open=yes pauses a dropped live stream at its end instead of sending end-file."""
    p, _fake = playing()
    p._handle_mpv_event("prop:eof-reached", True)
    assert p.playState == "reconnecting"
    assert p._retry_timer.isActive()


def test_eof_reached_is_ignored_in_playback():
    p, _fake = playing()
    p._mode = "playback"
    p._handle_mpv_event("prop:eof-reached", True)
    assert p.playState == "playing"
    assert not p._retry_timer.isActive()


def test_suspend_is_live_only():
    p, fake = playing()
    p._mode = "playback"
    p.suspended = True
    assert fake["pause"] is False and not p.suspended
