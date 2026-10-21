"""Upgrades of the node's local SQLite database.

Tables are created by Tortoise (generate_schemas=True), but that never changes an existing table. Each
step below brings an older node_state.sqlite3 up to date. Steps are idempotent and run in order at
startup, before any loop touches the database.
"""

import logging

from tortoise import connections

logger = logging.getLogger("node.migrate")


async def _columns(conn, table: str) -> set[str]:
    _, rows = await conn.execute_query(f"PRAGMA table_info({table})")
    return {r["name"] for r in rows}


async def _add_column(conn, table: str, column: str, ddl: str) -> None:
    if column not in await _columns(conn, table):
        await conn.execute_script(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        logger.info("Local database: added %s.%s", table, column)


async def migrate() -> None:
    conn = connections.get("default")
    # 2026-10-15 storage volumes: which volume holds each chunk (NULL = RECORDINGS_DIR).
    await _add_column(conn, "local_segments", "volume_id", "INT NULL")
    await _add_column(conn, "skipped_files", "volume_id", "INT NULL")
    # 2026-10-20 H6: structured audio metadata for recorded chunks.
    await _add_column(conn, "local_segments", "audio_codec", "VARCHAR(32) NULL")
    await _add_column(conn, "local_segments", "audio_sample_rate", "INT NULL")
    await _add_column(conn, "local_segments", "audio_channels", "INT NULL")
    # 2026-10-20 L3: distinguish ordinary recordings from camera-SD imports.
    await _add_column(conn, "local_segments", "origin", "VARCHAR(16) NOT NULL DEFAULT 'NVR'")
    await _add_column(conn, "local_segments", "backfill_job_id", "CHAR(36) NULL")
    await conn.execute_script("CREATE INDEX IF NOT EXISTS idx_local_segments_volume ON local_segments (volume_id, start_time)")
