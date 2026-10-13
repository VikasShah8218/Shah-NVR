"""The thread hand-off between libmpv callbacks and the GUI thread (app/video/mpv_item.py::_MpvBridge)."""

import threading

import pytest

from settings.settings import settings

if not (settings.MPV_DLL_DIR / "libmpv-2.dll").exists():
    pytest.skip("libmpv-2.dll not installed (see README)", allow_module_level=True)

from app.video.loader import prepare_libmpv  # noqa: E402

prepare_libmpv(settings.MPV_DLL_DIR)

from PySide6.QtCore import QObject  # noqa: E402

from app.video.mpv_item import _MpvBridge  # noqa: E402


def make_bridge():
    owner = QObject()
    bridge = _MpvBridge(owner)
    wakes = []
    bridge.wake.connect(lambda: wakes.append(1))  # direct connection: counts emits
    return owner, bridge, wakes


def test_one_wake_per_batch_and_events_in_order():
    _owner, bridge, wakes = make_bridge()
    bridge.post_event("prop:time-pos", 1.0)
    bridge.post_frame()
    bridge.post_event("prop:time-pos", 2.0)
    assert len(wakes) == 1
    frame, events = bridge.take()
    assert frame is True
    assert events == [("prop:time-pos", 1.0), ("prop:time-pos", 2.0)]
    bridge.post_frame()
    assert len(wakes) == 2  # a new batch wakes again


def test_closed_bridge_ignores_late_callbacks():
    _owner, bridge, wakes = make_bridge()
    bridge.post_event("prop:pause", True)
    bridge.close()
    bridge.post_frame()
    bridge.post_event("end-file", {"reason": 0})
    assert bridge.take() == (False, [])
    assert len(wakes) == 1


def test_many_threads_posting():
    _owner, bridge, _wakes = make_bridge()

    def worker(n):
        for i in range(500):
            bridge.post_event("n", (n, i))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    _frame, events = bridge.take()
    assert len(events) == 8 * 500
    for n in range(8):  # per-thread order is preserved
        assert [i for (_k, (m, i)) in events if m == n] == list(range(500))
