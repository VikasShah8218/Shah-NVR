"""PtzWs store: WebSocket message protocol, telemetry and gating. No real socket or network."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.features.live.ptz_ws_store import PtzWsStore, _sign


class Ctx(QObject):
    centralChanged = Signal()


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendTextMessage(self, text):
        self.sent.append(text)

    def close(self):
        pass

    def deleteLater(self):
        pass


@pytest.fixture
def store():
    app = QCoreApplication.instance() or QCoreApplication([])  # noqa: F841 - required for QObject/QTimer
    ctx = Ctx()
    ctx.central, ctx.prefs, ctx.toasts = Mock(), SimpleNamespace(), Mock()
    s = PtzWsStore(ctx, Mock(), Mock())
    s._ws = FakeSocket()
    s._connected = True
    s._phase = "ready"
    yield s
    s._keepalive.stop()


def sent(s):
    return [json.loads(t) for t in s._ws.sent]


def test_sign():
    assert _sign(-0.3) == -1 and _sign(2) == 1 and _sign(0) == 0


def test_hold_sends_direction_then_stop_on_release(store):
    store.hold(-1, 0, 0)
    assert sent(store)[-1] == {"t": "move", "pan": -1, "tilt": 0, "zoom": 0}
    store.release()
    assert sent(store)[-1] == {"t": "stop"}


def test_hold_collapses_values_to_signs(store):
    store.hold(0.5, -0.2, 0)   # QML may pass scaled numbers; the node wants a direction
    assert sent(store)[-1] == {"t": "move", "pan": 1, "tilt": -1, "zoom": 0}


def test_focus_hold_and_release(store):
    store.holdFocus(1)
    assert sent(store)[-1] == {"t": "focus", "dir": 1}
    store.release()
    assert sent(store)[-1] == {"t": "focus_stop"}


def test_stop_halts_both_ptz_and_focus(store):
    store.stop()
    msgs = sent(store)
    assert {"t": "stop"} in msgs and {"t": "focus_stop"} in msgs


def test_commands_blocked_until_ready(store):
    store._phase = "connecting"
    store.hold(1, 0, 0)
    assert store._ws.sent == []


def test_ready_frame_sets_caps_and_telemetry(store):
    store._on_message(json.dumps({"t": "ready", "capabilities": {"pan_tilt": True, "zoom": True, "focus": True},
                                  "status": {"zoom": 5}, "speed": 0.3, "zoom_pct": 42}))
    assert store.ready and store.phase == "ready"
    assert store.caps == {"pan_tilt": True, "zoom": True, "focus": True}
    assert abs(store.speed - 0.3) < 1e-9 and store.zoomPct == 42


def test_pose_frame_updates_speed_and_null_zoom_pct(store):
    store._on_message(json.dumps({"t": "pose", "status": {"zoom": 1}, "speed": 0.5, "zoom_pct": None}))
    assert abs(store.speed - 0.5) < 1e-9 and store.zoomPct == -1


def test_error_frame_surfaces_message(store):
    store._on_message(json.dumps({"t": "error", "code": "unreachable", "message": "camera unreachable"}))
    assert store.error == "camera unreachable"
