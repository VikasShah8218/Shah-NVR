"""GET /api/v1/segments is paged (docs/PAGINATION_PLAN.md, N1): newest first, total counted, camera filter."""

import asyncio
from datetime import timedelta
from uuid import uuid4

from tortoise import Tortoise

from app.recordings.models import LocalSegment
from app.recordings.router import list_local_segments
from utilities.common import utcnow


def test_segments_are_paged_newest_first(tmp_path):
    async def go():
        await Tortoise.init(db_url=f"sqlite://{(tmp_path / 'node.sqlite3').as_posix()}",
                            modules={"models": ["app.node.models", "app.recordings.models"]})
        await Tortoise.generate_schemas()
        try:
            start = utcnow() - timedelta(hours=1)
            for i in range(5):
                await LocalSegment.create(
                    id=uuid4(), camera_id=1 if i < 4 else 2, profile="main", rel_path=f"cam/{i}.mp4",
                    start_time=start + timedelta(minutes=i), end_time=start + timedelta(minutes=i, seconds=59),
                    duration_ms=60000, size_bytes=1, init_size=1, parts=[{"o": 0}], tracks={})
            first = await list_local_segments(camera_id=None, limit=2, offset=0)
            last = await list_local_segments(camera_id=1, limit=2, offset=2)
            return first, last
        finally:
            await Tortoise.close_connections()

    first, last = asyncio.run(go())
    assert first.total == 5 and [s.rel_path for s in first.items] == ["cam/4.mp4", "cam/3.mp4"]
    assert first.items[0].part_count == 1
    assert last.total == 4 and [s.rel_path for s in last.items] == ["cam/1.mp4", "cam/0.mp4"]
