"""Live "no picture" watchdog, the never-silent load and the ↻ reconnect (app/video/player.py). A stream that
connects but delivers no frames used to stay black forever; a load waiting for the render context used to sit in
an overlay-less "idle" state. Fake mpv, fake clock, no network."""

import pytest

from settings.settings import settings

if not (settings.MPV_DLL_DIR / "libmpv-2.dll").exists():
    pytest.skip("libmpv-2.dll not installed (see README)", allow_module_level=True)

from app.video.loader import prepare_libmpv  # noqa: E402

prepare_libmpv(settings.MPV_DLL_DIR)

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.video import player as player_mod  # noqa: E402
from app.video.player import NO_PICTURE_SECONDS, MpvPlayer  # noqa: E402

RTSP = "rtsp://node:8554/cam-1/main"
HLS = "http://node:8888/cam-1/main/index.m3u8"


class FakeMpv(dict):
    def __init__(self):
        super().__init__(pause=False)
        self.loads = []
        self.commands = []

    def loadfile(self, url):
        self.loads.append(url)

    def command(self, *args):
        self.commands.append(args)


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(player_mod.time, "monotonic", lambda: now["t"])
    return now


def started(source=RTSP, fallback="", render_ready=True):
    """A live player that has just loaded `source` (the fake stands in for libmpv)."""
    p = MpvPlayer()
    fake = FakeMpv()
    p.bridge.player = fake
    p._source = source
    p._fallback_source = fallback
    p._render_ready = render_ready
    p.play()
    return p, fake


def test_connected_but_no_frames_reconnects(clock):
    p, fake = started()
    assert fake.loads == [RTSP] and p.playState == "connecting" and p._watchdog.isActive()
    p._handle_mpv_event("prop:video-params", {"w": 1920, "h": 1080})  # size known, but no frame ever shown
    assert p.playState == "playing"
    clock["t"] += NO_PICTURE_SECONDS - 1
    p._watchdog_tick()
    assert p.playState == "playing"  # not yet
    clock["t"] += 2
    p._watchdog_tick()
    assert p.playState == "reconnecting" and p.errorText == "No picture. Reconnecting…"
    assert ("stop",) in fake.commands and p._retry_timer.isActive()
    p._retry_timer.stop()
    p._load_active_source()  # the retry
    assert fake.loads == [RTSP, RTSP]


def test_frames_keep_the_stream_alive(clock):
    p, fake = started()
    for _ in range(10):
        clock["t"] += 3
        p.bridge.post_frame()
        p._drain()  # a new frame arrived
        p._watchdog_tick()
    assert p.playState != "reconnecting" and fake.loads == [RTSP]
    clock["t"] += NO_PICTURE_SECONDS + 1  # then the frames stop: reconnect
    p._watchdog_tick()
    assert p.playState == "reconnecting"


def test_moving_time_pos_counts_as_progress(clock):
    p, fake = started()
    for i in range(5):
        clock["t"] += 3
        p._handle_mpv_event("prop:time-pos", float(i + 1))
        p._watchdog_tick()
    assert fake.loads == [RTSP] and p.playState != "reconnecting"


def test_hls_waits_for_its_buffer_and_auto_falls_back(clock):
    p, fake = started(source=RTSP, fallback=HLS)
    clock["t"] += NO_PICTURE_SECONDS + 1
    p._watchdog_tick()
    assert p.activeSource == HLS  # Auto: RTSP gave no picture -> LL-HLS
    p._retry_timer.stop()
    p._load_active_source()
    assert p._no_picture_limit() == 14  # buffer 5 s x2 + 4
    clock["t"] += NO_PICTURE_SECONDS + 1  # 9 s: LL-HLS still filling its buffer
    p._watchdog_tick()
    assert not p._retry_timer.isActive()
    clock["t"] += 6  # 15 s without a frame
    p._watchdog_tick()
    assert p._retry_timer.isActive() and p.errorText == "No picture. Reconnecting…"


def test_suspended_and_minimized_never_reconnect(clock, monkeypatch):
    p, fake = started()
    p.suspended = True
    assert not p._watchdog.isActive()
    p._watchdog_tick()
    assert fake.loads == [RTSP]
    p.suspended = False  # resume: fresh clock, quiet window handles the reconnect
    assert p._watchdog.isActive()
    p._end_quiet()
    monkeypatch.setattr(player_mod, "_window_shown", lambda: False)
    clock["t"] += 60
    p._watchdog_tick()
    assert p.playState != "reconnecting"  # minimized: Qt draws nothing, not a dead stream


def test_load_waiting_for_the_render_context_is_not_silent(clock):
    p, fake = started(render_ready=False)
    wanted = []
    p.renderWanted.connect(lambda: wanted.append(1))
    p._load_active_source()
    assert p.playState == "connecting" and wanted and fake.loads == []  # was "idle": black, no overlay
    p._handle_mpv_event("render-ready", None)
    assert fake.loads == [RTSP]


def test_reconnect_starts_fresh_on_the_preferred_protocol(clock):
    p, fake = started(source=RTSP, fallback=HLS)
    p._failures = 3
    p._set_active_source(HLS)
    p.reconnect()
    assert ("stop",) in fake.commands and fake.loads[-1] == RTSP and p._failures == 0
    assert p.playState == "connecting" and "connecting@" in p.timeline()


def test_stop_ends_the_watchdog(clock):
    p, fake = started()
    p.stop()
    assert not p._watchdog.isActive() and p.playState == "idle"
