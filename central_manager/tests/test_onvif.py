"""ONVIF on central: add-from-ONVIF fills streams + device fields, "already added" matching, node choice."""

import asyncio

import pytest
from fastapi import HTTPException
from tortoise import Tortoise

from app.assignments.models import CameraAssignment
from app.cameras.models import Camera, CameraStream
from app.nodes import client
from app.nodes.models import MediaNode, NodeState
from app.onvif import router as onvif
from app.onvif.schemas import DeviceIn, DiscoverIn, OnvifCameraCreate, StreamPick
from app.onvif.services import default_name, pick_streams
from database.config import APP_MODELS


def profile(token, w, h, enc="H264"):
    return {"token": token, "name": token, "api": "media2", "encoding": enc, "width": w, "height": h, "fps": 25,
            "bitrate_kbps": None, "has_audio": False, "has_ptz": False,
            "rtsp": f"rtsp://192.168.1.50/{token}", "snapshot": None}


PROBE = {
    "host": "192.168.1.50", "port": 80, "device_url": "http://192.168.1.50/onvif/device_service",
    "clock": {"offset_seconds": -563.0, "source": "Manual", "timezone": None, "camera_utc": None},
    "info": {"manufacturer": "Hanwha", "model": "SNV-L6014RM", "firmwareversion": "1.0", "serialnumber": "SN1",
             "hardwareid": None},
    "services": ["http://www.onvif.org/ver10/device/wsdl", "http://www.onvif.org/ver20/media/wsdl"],
    "profiles": [profile("p_main", 1920, 1080), profile("p_sub", 640, 360), profile("p_jpeg", 1920, 1080, "JPEG")],
    "suggested": {"main": "p_main", "sub": "p_sub"},
}


def run(fn):
    async def wrapper():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            await fn()
        finally:
            await Tortoise.close_connections()

    asyncio.run(wrapper())


@pytest.fixture
def fake_node(monkeypatch):
    calls = []

    async def call_node(node, path, json=None, *, timeout=30.0, raw=False):
        calls.append((node.name, path, json))
        if path.endswith("/discover"):
            return [{"endpoint": "urn:uuid:1", "host": "192.168.1.50", "port": 80, "xaddr": "http://192.168.1.50/onvif/device_service",
                     "name": None, "hardware": "SNV", "location": None, "mac": None, "profiles": ["Streaming"],
                     "interface_ip": "192.168.1.3"},
                    {"endpoint": "urn:uuid:2", "host": "192.168.1.241", "port": 80, "xaddr": "http://192.168.1.241/onvif/device_service",
                     "name": "AXIS M1125", "hardware": "M1125", "location": None, "mac": None, "profiles": ["G"],
                     "interface_ip": "192.168.1.3"}]
        if path.endswith("/probe"):
            return PROBE
        raise AssertionError(path)

    monkeypatch.setattr(onvif, "call_node", call_node)
    return calls


async def _node(name="n1", state=NodeState.ACTIVE):
    return await MediaNode.create(name=name, api_url=f"http://{name}:7100", media_host=name, state=state)


def test_add_camera_fills_streams_and_device(fake_node):
    async def go():
        node = await _node()
        out = await onvif.add_camera(OnvifCameraCreate(node_id=node.id, host="192.168.1.50", username="admin", password="pw"))
        assert out.name == "Hanwha SNV-L6014RM (192.168.1.50)"
        assert out.retention_days == 7 and out.manufacturer == "Hanwha" and out.serial == "SN1"
        assert out.onvif_host == "192.168.1.50" and out.clock_offset_seconds == -563.0
        streams = {s.profile: s for s in out.streams}
        assert streams["main"].source_url == "rtsp://192.168.1.50/p_main" and streams["main"].record
        assert streams["sub"].source_url == "rtsp://192.168.1.50/p_sub" and not streams["sub"].record
        assert streams["main"].onvif_profile_token == "p_main"
        assert fake_node[0][2]["password"] == "pw"  # credentials travel to the node per request

        with pytest.raises(HTTPException) as e:  # same device again
            await onvif.add_camera(OnvifCameraCreate(node_id=node.id, host="192.168.1.50"))
        assert e.value.status_code == 409 and e.value.detail["camera_id"] == out.id

    run(go)


def test_add_camera_with_picked_streams_and_keep_until_full(fake_node):
    async def go():
        node = await _node()
        out = await onvif.add_camera(OnvifCameraCreate(
            node_id=node.id, host="192.168.1.50", name="Gate", retention_days=None,
            streams=[StreamPick(profile="main", token="p_sub", record=True)]))
        assert out.name == "Gate" and out.retention_days is None
        assert [(s.profile, s.onvif_profile_token) for s in out.streams] == [("main", "p_sub")]

    run(go)


def test_discover_marks_already_added_by_stream_url(fake_node):
    async def go():
        await _node()
        await _node("n2", NodeState.UNREACHABLE)  # not asked
        cam = await Camera.create(name="Manual AXIS")
        await CameraStream.create(camera=cam, profile="main", source_url="rtsp://192.168.1.241/axis-media/media.amp")
        found = await onvif.discover(DiscoverIn())
        by_host = {d["host"]: d for d in found}
        assert by_host["192.168.1.241"]["camera_id"] == cam.id and by_host["192.168.1.50"]["camera_id"] is None
        assert {c[0] for c in fake_node} == {"n1"}

        probe = await onvif.probe(DeviceIn(host="192.168.1.241"))
        assert probe["camera_id"] == cam.id and probe["node_id"]

    run(go)


def test_pick_node_rules():
    async def go():
        with pytest.raises(HTTPException) as e:
            await client.pick_node()
        assert e.value.detail["code"] == "no_node_online"
        n1 = await _node("n1")
        n2 = await _node("n2")
        off = await _node("off", NodeState.UNREACHABLE)
        with pytest.raises(HTTPException) as e:
            await client.pick_node(off.id)
        assert e.value.detail["code"] == "node_offline"
        cam = await Camera.create(name="c")
        await CameraAssignment.create(camera=cam, node=n2)
        assert (await client.pick_node(camera_id=cam.id)).id == n2.id  # the camera's own node
        n2.state = NodeState.UNREACHABLE
        await n2.save()
        assert (await client.pick_node(camera_id=cam.id)).id == n1.id  # fallback: first online

    run(go)


def test_pick_streams_errors_and_names():
    with pytest.raises(HTTPException):
        pick_streams({**PROBE, "suggested": {"main": None, "sub": None}}, None)
    with pytest.raises(HTTPException):
        pick_streams(PROBE, [{"profile": "main", "token": "nope", "record": True}])
    assert default_name({"manufacturer": "AXIS", "model": "AXIS M1125"}, "1.2.3.4") == "AXIS M1125 (1.2.3.4)"
    assert default_name({}, "1.2.3.4") == "Camera (1.2.3.4)"


def test_heartbeat_health_only_for_own_cameras():
    from datetime import datetime, timezone

    from app.nodes.schemas import OnvifHealthIn
    from app.onvif.services import apply_onvif_health

    async def go():
        n1, n2 = await _node("n1"), await _node("n2")
        mine, other = await Camera.create(name="mine"), await Camera.create(name="other")
        await CameraAssignment.create(camera=mine, node=n1)
        await CameraAssignment.create(camera=other, node=n2)
        now = datetime.now(timezone.utc)
        await apply_onvif_health(n1.id, [
            OnvifHealthIn(camera_id=mine.id, reachable=True, clock_offset_seconds=-563, checked_at=now),
            OnvifHealthIn(camera_id=other.id, reachable=False, checked_at=now)])
        await mine.refresh_from_db()
        await other.refresh_from_db()
        assert mine.clock_offset_seconds == -563 and mine.onvif_reachable is True
        assert other.onvif_reachable is None  # n1 does not own it

        await apply_onvif_health(n1.id, [OnvifHealthIn(camera_id=mine.id, reachable=False, checked_at=now)])
        await mine.refresh_from_db()
        assert mine.onvif_reachable is False and mine.clock_offset_seconds == -563  # last known offset kept

    run(go)
