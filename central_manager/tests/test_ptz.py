import asyncio
import time
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from tortoise import Tortoise
from app.assignments.models import CameraAssignment
from app.cameras.models import Camera, CameraStream
from app.nodes.models import MediaNode, NodeState
from app.onvif import ptz_router as api
from app.onvif.ptz_schemas import PtzCommand
from database.config import APP_MODELS

SID = "ptz-session-test-000001"
STATE = {"session_id": SID, "capabilities": {"pan_tilt": True, "zoom": True}, "status": {}, "presets": []}


def run(fn):
    async def go():
        api.pins.clear()
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            node = await MediaNode.create(name="one", api_url="http://node-one", media_host="node-one", state=NodeState.ACTIVE)
            camera = await Camera.create(name="Gate", onvif_host="camera", username="user", password="secret")
            await CameraStream.create(camera=camera, profile="main", source_url="rtsp://camera/main", onvif_profile_token="profile_1")
            assignment = await CameraAssignment.create(camera=camera, node=node, generation=1)
            await fn(camera, node, assignment)
        finally:
            await Tortoise.close_connections()
    asyncio.run(go())


@pytest.fixture
def calls(monkeypatch):
    calls = []
    async def call(node, path, body, **kw):
        calls.append((node.id, path, body))
        return STATE if path.endswith("/open") else {"message": "Stop acknowledged"}
    monkeypatch.setattr(api, "call_node", call)
    return calls


def cmd(action="move", **kwargs):
    return PtzCommand(session_id=SID, sequence=1, action=action, **({"pan": .1} if action == "move" else {}), **kwargs)


def test_open_and_command_use_saved_credentials_not_browser_input(calls):
    async def go(camera, node, _):
        result = await api.open_ptz(camera.id, "main")
        assert "secret" not in str(result)
        await api.ptz_command(camera.id, "main", cmd())
        assert calls[0][0] == node.id
        assert calls[0][2] == {"host": "camera", "port": 80, "username": "user", "password": "secret", "profile_token": "profile_1"}
        fresh = await Camera.get(id=camera.id)
        assert fresh.name == "Gate" and fresh.enabled
    run(go)


def test_assignment_change_blocks_moves_but_stop_goes_to_original_node(calls):
    async def go(camera, node, assignment):
        await api.open_ptz(camera.id, "main")
        second = await MediaNode.create(name="two", api_url="http://node-two", media_host="node-two", state=NodeState.ACTIVE)
        assignment.node = second; assignment.generation = 2
        await assignment.save()
        with pytest.raises(HTTPException) as e:
            await api.ptz_command(camera.id, "main", cmd())
        assert e.value.detail["code"] == "ptz_target_changed"
        await api.ptz_command(camera.id, "main", cmd("stop"))
        assert calls[-1][0] == node.id and len(calls) == 2
    run(go)


def test_stop_uses_old_target_after_mapping_and_host_change(calls):
    async def go(camera, node, _):
        await api.open_ptz(camera.id, "main")
        await Camera.filter(id=camera.id).update(onvif_host="new-camera", enabled=False)
        await CameraStream.filter(camera_id=camera.id).update(onvif_profile_token="new-profile")
        await MediaNode.filter(id=node.id).update(state=NodeState.UNREACHABLE)
        await api.ptz_command(camera.id, "main", cmd("stop"))
        assert calls[-1][2]["host"] == "camera" and calls[-1][2]["profile_token"] == "profile_1"
    run(go)


def test_unassigned_camera_never_falls_back_to_another_node(calls):
    async def go(camera, _, assignment):
        await assignment.delete()
        with pytest.raises(HTTPException):
            await api.open_ptz(camera.id, "main")
        assert not calls
    run(go)


def test_mapping_required_and_disabled_camera_rejected(calls):
    async def go(camera, *_):
        await CameraStream.filter(camera_id=camera.id).update(onvif_profile_token=None)
        with pytest.raises(HTTPException) as e:
            await api.open_ptz(camera.id, "main")
        assert e.value.detail["code"] == "profile_mapping_required"
        await Camera.filter(id=camera.id).update(enabled=False)
        with pytest.raises(HTTPException) as e:
            await api.open_ptz(camera.id, "main")
        assert e.value.detail["code"] == "camera_disabled"
        assert not calls
    run(go)


def test_expired_session_and_cross_camera_rejected_stop_allowed(calls):
    async def go(camera, *_):
        await api.open_ptz(camera.id, "main")
        api.pins[SID].touched = time.monotonic() - 121
        with pytest.raises(HTTPException):
            await api.ptz_command(camera.id, "main", cmd())
        with pytest.raises(HTTPException):
            await api.ptz_command(camera.id + 1, "main", cmd("stop"))
        await api.ptz_command(camera.id, "main", cmd("stop"))
        assert len(calls) == 2
    run(go)


def test_relay_does_not_retry_unknown_outcome(monkeypatch, calls):
    async def go(camera, *_):
        await api.open_ptz(camera.id, "main")
        sent = []
        async def timeout(*args, **kwargs):
            sent.append(args)
            raise HTTPException(504, {"code": "node_timeout", "message": "Unknown outcome"})
        monkeypatch.setattr(api, "call_node", timeout)
        with pytest.raises(HTTPException):
            await api.ptz_command(camera.id, "main", cmd())
        assert len(sent) == 1
    run(go)


def test_http_contract_no_credentials_and_validation(calls):
    async def go(camera, *_):
        app = FastAPI(); app.include_router(api.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://central") as client:
            path = f"/api/v1/cameras/{camera.id}/streams/main/ptz"
            opened = await client.post(path)
            assert opened.status_code == 200 and "secret" not in opened.text
            invalid = await client.post(path + "/command", json={"session_id": SID, "sequence": 1, "action": "move", "pan": 99})
            assert invalid.status_code == 422
    run(go)
