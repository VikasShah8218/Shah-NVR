import asyncio
from datetime import timedelta

import pytest
from fastapi import HTTPException
from tortoise import Tortoise

from app.cameras.models import Camera, CameraStream, EncoderChange
from app.nodes.models import MediaNode, NodeState
from app.onvif import encoder_router as api
from app.onvif.encoder_schemas import EncoderWrite
from database.config import APP_MODELS
from utilities.common import utcnow

STATE = {"api": "tr2", "profile_token": "main", "encoder_token": "enc",
         "revision": "a" * 64, "current": {"encoding": "H264", "bitrate_kbps": 4096},
         "options": [], "profiles": [], "shared_profiles": ["main"], "warnings": []}


def run(fn):
    async def go():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            await MediaNode.create(name="node", api_url="http://node", media_host="node", state=NodeState.ACTIVE)
            cam = await Camera.create(name="Gate", onvif_host="camera", username="user", password="secret")
            await CameraStream.create(camera=cam, profile="main", source_url="rtsp://camera/main", onvif_profile_token="main")
            await fn(cam)
        finally:
            await Tortoise.close_connections()
    asyncio.run(go())


def body(op="encoder-operation-0001", **kwargs):
    return EncoderWrite(operation_id=op, revision="a" * 64, values={"bitrate_kbps": 2048}, **kwargs)


@pytest.fixture
def node(monkeypatch):
    calls = []
    async def call(n, path, data, **kw):
        calls.append((path, data))
        if path.endswith("/apply"):
            return {"outcome": "verified", "before": STATE,
                    "after": {**STATE, "current": {"encoding": "H264", "bitrate_kbps": 2048}},
                    "message": "Verified", "recovery": {"cam-1/main": "pending"}}
        return STATE
    monkeypatch.setattr(api, "call_node", call)
    return calls


def test_apply_journal_idempotency_and_no_camera_metadata_regression(node):
    async def go(cam):
        first = await api.put_encoder(cam.id, "main", body())
        again = await api.put_encoder(cam.id, "main", body())
        assert first == again and first["status"] == "verified"
        assert len([c for c in node if c[0].endswith("/apply")]) == 1
        saved = await EncoderChange.get(id=body().operation_id)
        assert "secret" not in str(saved.request) + str(saved.result) + str(saved.before)
        refreshed = await Camera.get(id=cam.id)
        assert refreshed.name == "Gate" and refreshed.enabled
        stream = await CameraStream.get(camera_id=cam.id, profile="main")
        assert stream.record and stream.source_url == "rtsp://camera/main"
        assert saved.active_key is None
    run(go)


def test_operation_id_cannot_be_reused_for_different_patch(node):
    async def go(cam):
        await api.put_encoder(cam.id, "main", body())
        changed = body(); changed.values.bitrate_kbps = 1024
        with pytest.raises(HTTPException) as e:
            await api.put_encoder(cam.id, "main", changed)
        assert e.value.detail["code"] == "operation_reused"
    run(go)


def test_timeout_is_durable_and_blocks_another_write(monkeypatch):
    async def call(n, path, data, **kw):
        if path.endswith("/apply"):
            raise HTTPException(504, {"code": "node_timeout", "message": "lost"})
        return STATE
    monkeypatch.setattr(api, "call_node", call)
    async def go(cam):
        with pytest.raises(HTTPException):
            await api.put_encoder(cam.id, "main", body())
        saved = await EncoderChange.get(id=body().operation_id)
        assert saved.status == "unknown" and saved.active_key
        with pytest.raises(HTTPException) as e:
            await api.put_encoder(cam.id, "main", body("encoder-operation-0002"))
        assert e.value.detail["code"] == "encoder_busy"
        with pytest.raises(HTTPException):
            await api.resolve_encoder(cam.id, "main")
        await EncoderChange.filter(id=saved.id).update(updated_at=utcnow() - timedelta(minutes=3))
        result = await api.resolve_encoder(cam.id, "main")
        assert result["status"] == "resolved"
        assert (await EncoderChange.get(id=saved.id)).active_key is None
    run(go)


def test_validation_failure_releases_mutex(monkeypatch):
    async def call(*a, **kw):
        raise HTTPException(422, {"code": "unsupported", "message": "unsupported"})
    monkeypatch.setattr(api, "call_node", call)
    async def go(cam):
        with pytest.raises(HTTPException):
            await api.put_encoder(cam.id, "main", body())
        row = await EncoderChange.get(id=body().operation_id)
        assert row.status == "failed" and row.active_key is None
    run(go)


def test_mapping_required_and_explicit_save(node):
    async def go(cam):
        await CameraStream.filter(camera_id=cam.id).update(onvif_profile_token=None)
        with pytest.raises(HTTPException) as e:
            await api.put_encoder(cam.id, "main", body())
        assert e.value.detail["code"] == "profile_mapping_required"
        await api.map_encoder(cam.id, "main", api.MappingIn(profile_token="main"))
        assert (await CameraStream.get(camera_id=cam.id)).onvif_profile_token == "main"
    run(go)


def test_restore_uses_saved_previous_values_not_untrusted_patch(node):
    async def go(cam):
        await api.put_encoder(cam.id, "main", body())
        await api.put_encoder(cam.id, "main", body("encoder-operation-0002", restore_from=body().operation_id))
        assert node[-1][1]["values"]["bitrate_kbps"] == 4096
    run(go)


def test_history_and_recovery_do_not_claim_success_on_old_heartbeat(node):
    async def go(cam):
        await api.put_encoder(cam.id, "main", body())
        history = await api.encoder_history(cam.id, "main")
        assert len(history["changes"]) == 1 and history["pending"] is None
        recovery = await api.encoder_recovery(cam.id, "main")
        assert not recovery["fresh_status"] and not recovery["new_recording"]
        await CameraStream.filter(camera_id=cam.id).update(last_status_at=utcnow(), last_segment_at=utcnow())
        recovery = await api.encoder_recovery(cam.id, "main")
        assert recovery["fresh_status"] and recovery["new_recording"]
    run(go)


def test_duplicate_device_camera_entries_restart_together(node):
    async def go(cam):
        second = await Camera.create(name="Duplicate", onvif_host="CAMERA.")
        await api.put_encoder(cam.id, "main", body())
        assert node[-1][1]["camera_ids"] == [cam.id, second.id]
    run(go)


def test_central_http_contract_roundtrip_and_camera_metadata(node):
    import httpx
    from fastapi import FastAPI
    from app.cameras.router import router as cameras
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(cameras)
    async def go(cam):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://central") as http:
            path = f"/api/v1/cameras/{cam.id}/streams/main/encoder"
            read = await http.get(path)
            assert read.status_code == 200 and read.json()["current"]["encoding"] == "H264"
            checked = await http.post(path + "/check", json=body().model_dump())
            assert checked.status_code == 200
            written = await http.put(path, json=body().model_dump())
            assert written.status_code == 200, written.text
            assert written.json()["status"] == "verified"
            assert "secret" not in written.text
            history = (await http.get(path + "/history")).json()
            assert history["changes"][0]["result"]["after"]["current"]["bitrate_kbps"] == 2048
            camera = (await http.get(f"/api/v1/cameras/{cam.id}")).json()
            assert camera["name"] == "Gate" and camera["enabled"]
            assert camera["streams"][0]["profile"] == "main"
            assert (await http.get(path + "/recovery")).status_code == 200
    run(go)


def test_concurrent_requests_share_durable_device_mutex(monkeypatch):
    async def go(cam):
        entered, release = asyncio.Event(), asyncio.Event()
        async def call(n, path, data, **kw):
            if path.endswith("/check"):
                entered.set()
                await release.wait()
                return STATE
            return {"outcome": "verified", "before": STATE, "after": STATE, "message": "Verified"}
        monkeypatch.setattr(api, "call_node", call)
        first = asyncio.create_task(api.put_encoder(cam.id, "main", body()))
        await entered.wait()
        try:
            with pytest.raises(HTTPException) as e:
                await api.put_encoder(cam.id, "main", body("encoder-operation-0002"))
            assert e.value.detail["code"] == "encoder_busy"
            with pytest.raises(HTTPException):
                await api.map_encoder(cam.id, "main", api.MappingIn(profile_token="sub"))
        finally:
            release.set()
            await first
    run(go)


def test_unknown_node_result_keeps_mutex(monkeypatch):
    async def call(n, path, data, **kw):
        if path.endswith("/apply"):
            return {"outcome": "unknown", "before": STATE, "after": STATE, "message": "No readback confirmation"}
        return STATE
    monkeypatch.setattr(api, "call_node", call)
    async def go(cam):
        result = await api.put_encoder(cam.id, "main", body())
        assert result["status"] == "unknown"
        assert (await EncoderChange.get(id=body().operation_id)).active_key
    run(go)


def test_restore_rejected_when_camera_device_address_changed(node):
    async def go(cam):
        await api.put_encoder(cam.id, "main", body())
        await Camera.filter(id=cam.id).update(onvif_host="replacement-camera")
        with pytest.raises(HTTPException) as e:
            await api.put_encoder(cam.id, "main", body("encoder-operation-0002", restore_from=body().operation_id))
        assert e.value.detail["code"] == "restore_unavailable"
    run(go)


def test_removed_mapping_returns_profile_choices_without_changing_database(monkeypatch):
    async def call(n, path, data, **kw):
        if data["profile_token"]:
            raise HTTPException(422, {"code": "profile_mapping_required", "message": "profile removed"})
        return {"api": "tr2", "profile_token": None, "profiles": [{"token": "new", "encoder_token": "enc"}]}
    monkeypatch.setattr(api, "call_node", call)
    async def go(cam):
        state = await api.get_encoder(cam.id, "main")
        assert state["profile_token"] is None and state["warnings"]
        assert (await CameraStream.get(camera_id=cam.id)).onvif_profile_token == "main"
    run(go)


def test_public_contract_is_identical_on_central_and_node():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    assert (root / "central_manager/app/onvif/encoder_schemas.py").read_text() == (
        root / "media_node/app/onvif/encoder_schemas.py").read_text()
