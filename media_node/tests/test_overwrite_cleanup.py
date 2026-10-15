"""When every volume is full, only just enough of the oldest recordings may be overwritten."""

import asyncio
from datetime import timedelta
from uuid import uuid4

from tortoise import Tortoise

import app.recordings.services as rec
from app.recordings.models import LocalSegment
from app.storage.services import storage
from utilities.common import utcnow

MB = 1024**2
CONFIG = [
    {"id": 1, "path": "x", "position": 0, "quota_bytes": 10 * MB, "accepting": True, "is_default": True},
    {"id": 9, "path": "Y:/vol9", "position": 1, "quota_bytes": 10 * MB, "accepting": True, "is_default": False},
]


async def _setup(tmp_path):
    await Tortoise.init(db_url=f"sqlite://{(tmp_path / 'node.sqlite3').as_posix()}",
                        modules={"models": ["app.node.models", "app.recordings.models"]})
    await Tortoise.generate_schemas()
    start = utcnow() - timedelta(hours=5)
    # Default volume filled first (oldest chunks), then volume 9: 5 x 2 MB each = 10 MB = full.
    for i in range(10):
        await LocalSegment.create(
            id=uuid4(), camera_id=1, profile="main", volume_id=None if i < 5 else 9,
            rel_path=f"cam-1/main/2026-10-15/00-00-{i:02d}-000000.mp4",
            start_time=start + timedelta(minutes=i), end_time=start + timedelta(minutes=i, seconds=59),
            duration_ms=60000, size_bytes=2 * MB, init_size=100, parts=[], tracks={},
        )
    storage._build(CONFIG, None)
    for v in storage.volumes.values():
        v.state, v.full, v.recordings_bytes = "OK", True, 10 * MB
        v.total_bytes, v.disk_used_percent = 1000 * MB, 10.0


def test_overwrite_deletes_only_the_oldest_needed(tmp_path, monkeypatch):
    deleted_ids = []

    async def fake_delete(items):  # no files in this test: just record what would be deleted
        deleted_ids.extend(i for i, _key, _rel in items)
        return [i for i, _key, _rel in items]

    monkeypatch.setattr(rec, "_delete_local", fake_delete)

    async def run():
        await _setup(tmp_path)
        try:
            oldest = await LocalSegment.all().order_by("start_time").first()
            result = await rec.overwrite_cleanup()
            # 10 MB - 2 MB = 8 MB < 90% of 10 MB: one chunk frees the first volume again.
            assert result == [str(oldest.id)]
        finally:
            await Tortoise.close_connections()

    asyncio.run(run())
    assert len(deleted_ids) == 1


def test_no_overwrite_while_some_volume_has_room(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "_delete_local", lambda items: (_ for _ in ()).throw(AssertionError("deleted")))

    async def run():
        await _setup(tmp_path)
        try:
            storage.get(9).full = False
            assert await rec.overwrite_cleanup() == []
        finally:
            await Tortoise.close_connections()

    asyncio.run(run())
