import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.exports.schemas import ExportCreate
from app.exports.router import create_export
from app.cameras.models import Camera, CameraStream
from app.nodes.models import MediaNode
from app.recordings.models import RecordingSegment
from database.config import APP_MODELS
from fastapi import HTTPException
from tortoise import Tortoise


def test_export_defaults_to_original():
    now = datetime.now(timezone.utc)
    body = ExportCreate(camera_id=1, start_time=now - timedelta(minutes=5), end_time=now)
    assert body.mode == "original"
    assert body.max_height == 0
    assert body.max_fps == 0


def test_export_rejects_invalid_fps():
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        ExportCreate(camera_id=1, start_time=now - timedelta(minutes=5), end_time=now,
                     mode="compressed", max_fps=121)


def run(coro_fn):
    async def wrapper():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            await coro_fn()
        finally:
            await Tortoise.close_connections()
    asyncio.run(wrapper())


async def fixture(codec="H264", signature="one"):
    node = await MediaNode.create(name="node", api_url="http://node:7100", media_host="node")
    camera = await Camera.create(name="Front Door")
    await CameraStream.create(camera=camera, profile="main", source_url="rtsp://camera/main", record=True)
    now = datetime.now(timezone.utc)
    await RecordingSegment.create(id=uuid4(), camera=camera, node=node, profile="main",
        start_time=now - timedelta(minutes=10), end_time=now - timedelta(minutes=5), duration_ms=300000,
        size_bytes=100, codec=codec, config_signature=signature, file_path="one.mp4", parts=[1000])
    return camera, node, now


def test_create_export_persists_job_on_recording_node():
    async def body():
        camera, node, now = await fixture()
        out = await create_export(ExportCreate(camera_id=camera.id, start_time=now - timedelta(minutes=9),
            end_time=now - timedelta(minutes=6), mode="original"))
        assert out.node_id == node.id
        assert out.state == "QUEUED"
        assert out.output_name.startswith("Front_Door_main_")
        assert out.options["estimated_input_bytes"] == 100
    run(body)


def test_original_export_rejects_encoder_change():
    async def body():
        camera, node, now = await fixture()
        await RecordingSegment.create(id=uuid4(), camera=camera, node=node, profile="main",
            start_time=now - timedelta(minutes=5), end_time=now - timedelta(minutes=1), duration_ms=240000,
            size_bytes=100, codec="H265", config_signature="two", file_path="two.mp4", parts=[1000])
        with pytest.raises(HTTPException) as exc:
            await create_export(ExportCreate(camera_id=camera.id, start_time=now - timedelta(minutes=9),
                end_time=now - timedelta(minutes=2), mode="original"))
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "incompatible_segments"
    run(body)
