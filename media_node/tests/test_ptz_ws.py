"""Tests for the low-latency PTZ WebSocket path (app/onvif/ptz_ws.py)."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lxml import etree

from app.onvif import ptz, ptz_ws, ptz_router


def xml(text):
    return etree.fromstring(f'<root xmlns:p="{ptz.PTZ}" xmlns:tt="{ptz.NS["tt"]}">{text}</root>')


STATUS = ('<p:PTZStatus><tt:Position><tt:PanTilt x="10" y="-5"/><tt:Zoom x="100"/></tt:Position>'
          '<tt:MoveStatus><tt:PanTilt>IDLE</tt:PanTilt><tt:Zoom>IDLE</tt:Zoom></tt:MoveStatus></p:PTZStatus>')

CAPS = {"pan_tilt": True, "zoom": True, "presets": False, "home": False, "home_set": False, "camera_timeout_seconds": 10}
SPACES = {"pan_tilt": "ptspace", "zoom": "zspace"}


def fake_dev():
    dev = SimpleNamespace(soap=SimpleNamespace(offset=0.0, http_digest=False))
    async def aexit(*exc):
        dev.closed = True
    dev.__aexit__ = aexit
    dev.closed = False
    return dev


def make_session(sid="s" * 24, backend="onvif", caps=None, spaces=None):
    return ptz_ws.WsSession(sid, fake_dev(), "profile_1", "http://camera/ptz",
                            dict(spaces or SPACES), dict(caps or CAPS), backend)


# --- pure helpers -----------------------------------------------------------
@pytest.mark.parametrize("value, expected", [(0.5, 1), (-0.2, -1), (0, 0), (None, 0), ("x", 0), (1, 1), (-3, -1)])
def test_sign(value, expected):
    assert ptz_ws.sign(value) == expected


def test_auto_speed_tracks_observed_zoom():
    s = make_session()
    assert ptz_ws.auto_speed(s) == ptz_ws.SPEED_MAX          # no range seen yet -> full speed
    ptz_ws.observe_zoom(s, 0.0)
    ptz_ws.observe_zoom(s, 100.0)                            # wide..tele range learned; now at tele
    assert abs(ptz_ws.auto_speed(s) - ptz_ws.SPEED_MIN) < 1e-9
    ptz_ws.observe_zoom(s, 50.0)                             # mid -> midway speed
    assert abs(ptz_ws.auto_speed(s) - (ptz_ws.SPEED_MAX + ptz_ws.SPEED_MIN) / 2) < 1e-6


# --- continuous move SOAP ---------------------------------------------------
def test_do_move_pan_only_has_speed_space_and_timeout(monkeypatch):
    async def run():
        log = []
        async def call(dev, url, req):
            log.append((etree.QName(req).localname, etree.tostring(req).decode()))
        monkeypatch.setattr(ptz, "call", call)
        s = make_session()                                   # wide end -> SPEED_MAX
        await ptz_ws.do_move(s, pan=-1, tilt=0, zoom=0)
        action, text = log[-1]
        assert action == "ContinuousMove"
        assert f'x="{-ptz_ws.SPEED_MAX:.3f}"' in text and 'space="ptspace"' in text
        assert "PT10S" in text and "Zoom" not in text       # axis-only; zoom space omitted
    asyncio.run(run())


def test_do_move_scales_with_zoom(monkeypatch):
    async def run():
        log = []
        async def call(dev, url, req):
            log.append(etree.tostring(req).decode())
        monkeypatch.setattr(ptz, "call", call)
        s = make_session()
        ptz_ws.observe_zoom(s, 0.0)
        ptz_ws.observe_zoom(s, 100.0)                        # tele -> SPEED_MIN
        await ptz_ws.do_move(s, pan=1, tilt=0, zoom=0)
        assert f'x="{ptz_ws.SPEED_MIN:.3f}"' in log[-1]
    asyncio.run(run())


def test_do_move_unsupported_axis_sends_nothing(monkeypatch):
    async def run():
        log = []
        async def call(dev, url, req):
            log.append(req)
        monkeypatch.setattr(ptz, "call", call)
        s = make_session(caps={**CAPS, "pan_tilt": False})
        await ptz_ws.do_move(s, pan=1, tilt=0, zoom=0)       # pan_tilt unsupported -> ignored
        assert log == []
    asyncio.run(run())


def test_do_stop_sends_stop(monkeypatch):
    async def run():
        log = []
        async def call(dev, url, req):
            log.append(etree.QName(req).localname)
        monkeypatch.setattr(ptz, "call", call)
        await ptz_ws.do_stop(make_session())
        assert log == ["Stop"]
    asyncio.run(run())


# --- open: migrate a discovery into a live WS session -----------------------
def test_open_ws_session_holds_live_device_and_migrates_rest(monkeypatch):
    async def run():
        ptz.sessions.clear()
        ptz_ws.ws_sessions.clear()
        made = {}

        class FakeDev:
            def __init__(self, *a, **k):
                made["dev"] = self
                self.soap = SimpleNamespace(offset=3, http_digest=False)
            async def __aexit__(self, *exc):
                made["closed"] = True

        monkeypatch.setattr(ptz_ws, "OnvifDevice", FakeDev)
        rest_sid = "rest" + "x" * 20

        async def fake_open(dev, profile):
            ptz.sessions[rest_sid] = ptz.Session(("camera", 80, "u", profile), "http://camera/ptz", profile,
                                                 3, False, {"pan_tilt": True}, {"pan_tilt": "pt"}, "onvif")
            return {"session_id": rest_sid, "capabilities": {"pan_tilt": True}, "status": {"zoom": 1},
                    "presets": [], "warnings": []}

        monkeypatch.setattr(ptz, "open_session", fake_open)
        state = await ptz_ws.open_ws_session("camera", 80, "u", "p", "profile_1")
        assert state["session_id"] != rest_sid               # fresh opaque id for the client
        assert rest_sid not in ptz.sessions                  # discovery migrated out of the REST registry
        s = ptz_ws.ws_sessions[state["session_id"]]
        assert s.dev is made["dev"] and s.spaces == {"pan_tilt": "pt"}
        await ptz_ws.close_session(s, stop=False)
        ptz_ws.ws_sessions.pop(state["session_id"], None)
        assert made.get("closed")
    asyncio.run(run())


# --- full WebSocket round trip ----------------------------------------------
def _app():
    app = FastAPI()
    app.include_router(ptz_router.router)
    return app


def test_ws_move_then_stop_round_trip(monkeypatch):
    log = []

    async def call(dev, url, req):
        action = etree.QName(req).localname
        log.append(action)
        return xml(STATUS) if action == "GetStatus" else xml("")

    monkeypatch.setattr(ptz, "call", call)
    sid = "wssid" + "y" * 20
    ptz_ws.ws_sessions[sid] = make_session(sid)
    try:
        with TestClient(_app()).websocket_connect(f"/api/v1/onvif/ptz/ws?session={sid}") as ws:
            ready = ws.receive_json()
            assert ready["t"] == "ready" and ready["capabilities"]["pan_tilt"]
            ws.send_json({"t": "move", "pan": -1})
            ws.send_json({"t": "stop"})
            seen = []
            for _ in range(10):
                seen.append(ws.receive_json()["t"])
                if "stopped" in seen:
                    break
            assert "stopped" in seen
        assert "ContinuousMove" in log and "Stop" in log
    finally:
        ptz_ws.ws_sessions.pop(sid, None)


def test_ws_unknown_session_is_rejected():
    with TestClient(_app()).websocket_connect("/api/v1/onvif/ptz/ws?session=missing") as ws:
        msg = ws.receive_json()
        assert msg["t"] == "error" and msg["code"] == "ptz_session_expired"


def test_ws_second_connection_rejected(monkeypatch):
    async def call(dev, url, req):
        return xml(STATUS) if etree.QName(req).localname == "GetStatus" else xml("")
    monkeypatch.setattr(ptz, "call", call)
    sid = "wssid" + "z" * 20
    ptz_ws.ws_sessions[sid] = make_session(sid)
    try:
        client = TestClient(_app())
        with client.websocket_connect(f"/api/v1/onvif/ptz/ws?session={sid}") as first:
            assert first.receive_json()["t"] == "ready"
            with client.websocket_connect(f"/api/v1/onvif/ptz/ws?session={sid}") as second:
                msg = second.receive_json()
                assert msg["t"] == "error" and msg["code"] == "ptz_busy"
    finally:
        ptz_ws.ws_sessions.pop(sid, None)
