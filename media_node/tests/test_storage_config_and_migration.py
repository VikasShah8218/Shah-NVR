"""Storage configuration mapping (central ids <-> local keys) and the local SQLite upgrade."""

import asyncio
import sqlite3

from tortoise import Tortoise

from app.storage.services import Storage
from settings.settings import settings

CONFIG = [
    {"id": 7, "path": "ignored-for-default", "position": 0, "quota_bytes": 100, "accepting": True, "is_default": True},
    {"id": 9, "path": r"D:\ShahNVR\recordings", "position": 1, "quota_bytes": None, "accepting": True, "is_default": False},
    {"id": 12, "path": r"\\192.168.1.9\nvr", "position": 2, "quota_bytes": 500, "accepting": False, "is_default": False},
]


def test_build_maps_default_volume_to_key_none():
    s = Storage()
    s._build(CONFIG, legacy_quota=None)
    default = s.get(None)
    assert default.central_id == 7 and default.path == settings.RECORDINGS_DIR and default.quota_bytes == 100
    assert s.key_for_central(7) is None and s.key_for_central(9) == 9 and s.key_for_central(None) is None
    assert s.central_id(None) == 7 and s.central_id(12) == 12
    assert [v.key for v in s.ordered()] == [None, 9, 12]
    assert s.get(12).is_network and not s.get(9).is_network


def test_build_without_central_volumes_uses_legacy_quota():
    s = Storage()
    s._build(None, legacy_quota=5 * 1024**3)
    assert list(s.volumes) == [None]
    assert s.get(None).quota_bytes == 5 * 1024**3 and s.get(None).central_id is None
    assert s.reports() == []  # nothing to report until central knows the default volume


def test_migration_adds_volume_columns_to_an_old_database(tmp_path):
    db = tmp_path / "old.sqlite3"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE local_segments (id CHAR(36) PRIMARY KEY, camera_id INT, profile VARCHAR(32), generation BIGINT,
            rel_path VARCHAR(512) UNIQUE, start_time TIMESTAMP, end_time TIMESTAMP, duration_ms INT, size_bytes BIGINT,
            init_size INT, codec VARCHAR(32), parts JSON, tracks JSON, uploaded INT, created_at TIMESTAMP);
        CREATE TABLE skipped_files (rel_path VARCHAR(512) PRIMARY KEY, reason VARCHAR(256), created_at TIMESTAMP);
        INSERT INTO local_segments (id, rel_path, size_bytes) VALUES ('a', 'cam-1/main/2026-10-15/00-00-00-000000.mp4', 10);
    """)
    con.close()

    from database.migrate import migrate

    async def run():
        await Tortoise.init(db_url=f"sqlite://{db.as_posix()}", modules={"models": ["app.node.models"]})
        try:
            await migrate()
            await migrate()  # idempotent
        finally:
            await Tortoise.close_connections()

    asyncio.run(run())
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(local_segments)")}
    assert {"volume_id", "audio_codec", "audio_sample_rate", "audio_channels"} <= cols
    assert "volume_id" in {r[1] for r in con.execute("PRAGMA table_info(skipped_files)")}
    assert con.execute("SELECT volume_id, size_bytes FROM local_segments").fetchone() == (None, 10)  # old rows = default
    con.close()
