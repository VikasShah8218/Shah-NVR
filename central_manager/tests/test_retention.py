"""Age retention counts back from each camera's latest recording; None = keep until storage is full."""

import asyncio
from datetime import timedelta
from uuid import uuid4

from tortoise import Tortoise

from app.cameras.models import Camera
from app.nodes.models import MediaNode
from app.recordings.models import RecordingSegment, SegmentStatus
from app.recordings.services import retention_tick
from database.config import APP_MODELS
from utilities.common import utcnow


def run(coro_fn):
    async def wrapper():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            await coro_fn()
        finally:
            await Tortoise.close_connections()

    asyncio.run(wrapper())


async def camera_with_hours(retention_days, end_hours_ago, profile="main", camera=None):
    """One 1-hour chunk per entry, ending `h` hours ago."""
    node = await MediaNode.first() or await MediaNode.create(name="n", api_url="http://n", media_host="n")
    camera = camera or await Camera.create(name="cam", retention_days=retention_days)
    now = utcnow()
    for h in end_hours_ago:
        end = now - timedelta(hours=h)
        await RecordingSegment.create(id=uuid4(), camera=camera, profile=profile, node=node, start_time=end - timedelta(hours=1),
                                      end_time=end, duration_ms=3600000, size_bytes=1, file_path=f"{profile}/{h}", parts=[1])
    return camera


async def marked_hours(camera, profile="main"):
    now = utcnow()
    rows = await RecordingSegment.filter(camera=camera, profile=profile, status=SegmentStatus.DELETING)
    return sorted(round((now - r.end_time).total_seconds() / 3600) for r in rows)


def test_recording_camera_keeps_a_rolling_window():
    async def body():
        # recording for 25 h right up to now; 1 day kept -> only the chunk that ended 25 h ago goes
        cam = await camera_with_hours(1, range(0, 26))
        await retention_tick()
        assert await marked_hours(cam) == [25]
    run(body)


def test_stopped_camera_loses_nothing_more():
    async def body():
        # recorded hours 0..25 of its life, then stopped 5 hours ago (newest chunk ended 5 h ago)
        cam = await camera_with_hours(1, range(5, 31))
        await retention_tick()
        # window = 24 h before the newest chunk (5 h ago) -> only chunks ending before 29 h ago
        assert await marked_hours(cam) == [30]
        before = await marked_hours(cam)
        await retention_tick()  # time passes, no new recording: nothing more goes
        assert await marked_hours(cam) == before
    run(body)


def test_keep_until_full_never_deletes_by_age():
    async def body():
        cam = await camera_with_hours(None, range(0, 24 * 40, 24))
        await retention_tick()
        assert await marked_hours(cam) == []
    run(body)


def test_profiles_anchor_separately():
    async def body():
        cam = await camera_with_hours(1, range(0, 26), profile="main")      # still recording
        await camera_with_hours(1, range(50, 76), profile="sub", camera=cam)  # stopped 50 h ago
        await retention_tick()
        assert await marked_hours(cam, "main") == [25]
        assert await marked_hours(cam, "sub") == [75]  # sub keeps its last day before it stopped
    run(body)


def test_raising_retention_keeps_remaining_chunks():
    async def body():
        cam = await camera_with_hours(1, range(0, 26))
        cam.retention_days = 30
        await cam.save()
        await retention_tick()
        assert await marked_hours(cam) == []
    run(body)


def test_future_chunk_does_not_shorten_retention():
    async def body():
        cam = await camera_with_hours(1, [-48, 0, 10, 23])  # one chunk "ends" 2 days in the future (bad camera clock)
        await retention_tick()
        assert await marked_hours(cam) == []  # anchor is clamped to now
    run(body)


def test_api_null_means_keep_until_full():
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as client:
        stream = [{"profile": "main", "source_url": "rtsp://1.2.3.4/x", "record": True}]
        default = client.post("/api/v1/cameras", json={"name": "a", "streams": stream}).json()
        assert default["retention_days"] == 7
        unlimited = client.post("/api/v1/cameras", json={"name": "b", "retention_days": None, "streams": stream}).json()
        assert unlimited["retention_days"] is None
        cid = default["id"]
        assert client.patch(f"/api/v1/cameras/{cid}", json={"name": "a2"}).json()["retention_days"] == 7
        assert client.patch(f"/api/v1/cameras/{cid}", json={"retention_days": None}).json()["retention_days"] is None
        assert client.patch(f"/api/v1/cameras/{cid}", json={"retention_days": 30}).json()["retention_days"] == 30
        assert client.patch(f"/api/v1/cameras/{cid}", json={"retention_days": 0}).status_code == 422
