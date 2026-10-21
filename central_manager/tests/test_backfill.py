import asyncio
from datetime import timedelta

import pytest
from fastapi import HTTPException
from tortoise import Tortoise

from app.assignments.models import CameraAssignment
from app.backfill.router import create_backfill_job
from app.backfill.services import backfill_scheduler_tick
from app.backfill.schemas import BackfillJobCreate
from app.cameras.models import Camera, CameraStream
from app.nodes.models import MediaNode
from app.recordings.models import BackfillJob, BackfillState, RecordingSegment, SegmentOrigin
from database.config import APP_MODELS
from utilities.common import utcnow


def run(fn):
    async def wrapper():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            await fn()
        finally:
            await Tortoise.close_connections()
    asyncio.run(wrapper())


def test_manual_job_is_created_only_for_a_real_gap_and_is_idempotent():
    async def go():
        node = await MediaNode.create(name="n1", api_url="http://n1:7100", media_host="n1")
        camera = await Camera.create(
            name="edge", backfill_mode="manual", backfill_capability="supported",
            backfill_recording_token="recording-1", backfill_profile="main",
        )
        await CameraStream.create(camera=camera, profile="main", source_url="rtsp://camera/main", record=True)
        await CameraAssignment.create(camera=camera, node=node, generation=3)
        end = utcnow() - timedelta(hours=1)
        start = end - timedelta(minutes=5)
        body = BackfillJobCreate(start_time=start, end_time=end, profile="main")
        first = await create_backfill_job(camera.id, body)
        second = await create_backfill_job(camera.id, body)
        assert first.id == second.id
        job = await BackfillJob.get(id=first.id)
        assert job.state == BackfillState.QUEUED and job.assignment_generation == 3

        await RecordingSegment.create(
            id="00000000-0000-0000-0000-000000000001", camera=camera, node=node, profile="main",
            start_time=start, end_time=end, duration_ms=300000, size_bytes=1, file_path="x.mp4",
            parts=[300000], origin=SegmentOrigin.NVR,
        )
        await job.delete()
        with pytest.raises(HTTPException) as exc:
            await create_backfill_job(camera.id, body)
        assert exc.value.status_code == 409 and exc.value.detail["code"] == "no_gap"
    run(go)


def test_automatic_scheduler_queues_only_one_bounded_recent_gap():
    async def go():
        node = await MediaNode.create(name="n1", api_url="http://n1:7100", media_host="n1")
        now = utcnow()
        camera = await Camera.create(
            name="auto", backfill_mode="automatic", backfill_capability="supported",
            backfill_recording_token="recording-1", backfill_profile="main",
            backfill_earliest=now - timedelta(hours=2), backfill_latest=now - timedelta(minutes=10),
            backfill_checked_at=now,
        )
        await CameraStream.create(camera=camera, profile="main", source_url="rtsp://camera/main", record=True)
        await CameraAssignment.create(camera=camera, node=node, generation=1)
        await backfill_scheduler_tick()
        [job] = await BackfillJob.all()
        assert job.requested_by == "automatic"
        assert timedelta(0) < job.end_time - job.start_time <= timedelta(minutes=15)
        await backfill_scheduler_tick()
        assert await BackfillJob.all().count() == 1
    run(go)


def test_automatic_scheduler_does_not_import_stale_camera_history():
    async def go():
        node = await MediaNode.create(name="n1", api_url="http://n1:7100", media_host="n1")
        now = utcnow()
        camera = await Camera.create(
            name="stale", backfill_mode="automatic", backfill_capability="supported",
            backfill_recording_token="recording-1", backfill_profile="main",
            backfill_earliest=now - timedelta(days=4), backfill_latest=now - timedelta(days=2),
            backfill_checked_at=now,
        )
        await CameraStream.create(camera=camera, profile="main", source_url="rtsp://camera/main", record=True)
        await CameraAssignment.create(camera=camera, node=node, generation=1)
        await backfill_scheduler_tick()
        assert await BackfillJob.all().count() == 0
    run(go)
