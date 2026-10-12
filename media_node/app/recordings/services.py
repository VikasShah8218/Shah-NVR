"""Recording pipeline on the node:

  MediaMTX writes chunk  ->  scanner finds finished chunk  ->  indexer (byte offsets of keyframe parts)
  ->  LocalSegment row (SQLite, upload queue)  ->  uploader batches metadata to central
  ->  retention / disk-pressure / storage-quota cleanup deletes files and confirms to central.
"""

import asyncio
import logging
import os
import time
from datetime import timedelta
from pathlib import Path

from tortoise.functions import Sum

from app.node.models import KeyValue
from app.node.services import disk_info
from app.node.utils import CentralError, central, runtime
from app.recordings.models import LocalSegment, SkippedFile
from app.recordings.utils import Mp4IndexError, index_fmp4, parse_rel_path, segment_uuid
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("node.recordings")

KV_PENDING_DELETED = "pending_deleted"
QUOTA_HIGH = 0.95  # start deleting above 95% of the storage quota
QUOTA_LOW = 0.90  # ...until usage is below 90%
UPLOAD_BATCH = 200
RECENT_DAY_DIRS = 2  # after the first full scan, only the newest N day folders are scanned

_known: set[str] = set()
_full_scan_done = False
_used_cache: tuple[float, int] = (0.0, 0)


# ---------------------------------------------------------------- scanner


def _list_finished_files(full: bool) -> list[str]:
    """Relative paths of chunks that MediaMTX has finished writing.

    A chunk is finished when a newer chunk exists for the same stream, or when it has not
    been modified for a while (camera disconnected / path stopped)."""
    root = settings.RECORDINGS_DIR
    idle_after = max(30.0, settings.PART_SECONDS * 10)
    now = time.time()
    finished: list[str] = []
    if not root.exists():
        return finished
    for cam_dir in root.iterdir():
        if not (cam_dir.is_dir() and cam_dir.name.startswith("cam-")):
            continue
        for profile_dir in cam_dir.iterdir():
            if not profile_dir.is_dir():
                continue
            day_dirs = sorted(d for d in profile_dir.iterdir() if d.is_dir())
            if not full:
                day_dirs = day_dirs[-RECENT_DAY_DIRS:]
            files = sorted(f for d in day_dirs for f in d.iterdir() if f.suffix == ".mp4")
            for i, f in enumerate(files):
                rel = f.relative_to(root).as_posix()
                if rel in _known:
                    continue
                is_newest = i == len(files) - 1
                if is_newest and now - f.stat().st_mtime < idle_after:
                    continue  # still being written
                finished.append(rel)
    return finished


def _index_file(rel: str):
    path = settings.RECORDINGS_DIR / rel
    info = parse_rel_path(rel)
    idx = index_fmp4(path, settings.HLS_PART_TARGET_SECONDS)
    return info, idx


async def _load_known() -> None:
    since = utcnow() - timedelta(days=RECENT_DAY_DIRS + 1)
    _known.update(await LocalSegment.filter(start_time__gte=since).values_list("rel_path", flat=True))
    _known.update(await SkippedFile.all().values_list("rel_path", flat=True))


async def scan_tick() -> None:
    global _full_scan_done
    full = not _full_scan_done
    if full:
        await _load_known()
    candidates = await asyncio.to_thread(_list_finished_files, full)
    if full:
        # First scan also checks old folders, so files written while the agent was down are not lost.
        old = [r for r in candidates if not await LocalSegment.exists(rel_path=r)]
        candidates = [r for r in old if not await SkippedFile.exists(rel_path=r)]
        _full_scan_done = True
        if candidates:
            logger.info("Recovery scan: %s unindexed chunk(s) found", len(candidates))

    for rel in candidates:
        try:
            info, idx = await asyncio.to_thread(_index_file, rel)
        except (Mp4IndexError, ValueError, OSError) as exc:
            logger.warning("Skipping chunk %s: %s", rel, exc)
            await SkippedFile.update_or_create(rel_path=rel, defaults={"reason": str(exc)[:250]})
            _known.add(rel)
            continue

        end_time = info.start_time + timedelta(milliseconds=idx.duration_ms)
        await LocalSegment.update_or_create(
            rel_path=rel,
            defaults=dict(
                id=segment_uuid(settings.NODE_NAME, rel),
                camera_id=info.camera_id,
                profile=info.profile,
                generation=runtime.generation_for(info.camera_id),
                start_time=info.start_time,
                end_time=end_time,
                duration_ms=idx.duration_ms,
                size_bytes=idx.size_bytes,
                init_size=idx.init_size,
                codec=idx.codec,
                parts=idx.parts,
                tracks=idx.tracks,
                uploaded=False,
            ),
        )
        _known.add(rel)
        key = (info.camera_id, info.profile)
        if key not in runtime.last_segment_end or end_time > runtime.last_segment_end[key]:
            runtime.last_segment_end[key] = end_time
        logger.debug("Indexed %s (%.1fs, %s parts)", rel, idx.duration_ms / 1000, len(idx.parts))


# ---------------------------------------------------------------- uploader


async def upload_tick() -> None:
    if runtime.node_id is None:
        return
    while True:
        batch = await LocalSegment.filter(uploaded=False).order_by("created_at").limit(UPLOAD_BATCH)
        if not batch:
            return
        items = [
            {
                "id": str(s.id),
                "camera_id": s.camera_id,
                "profile": s.profile,
                "generation": s.generation,
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat(),
                "duration_ms": s.duration_ms,
                "size_bytes": s.size_bytes,
                "codec": s.codec,
                "file_path": s.rel_path,
                "parts": [p["d"] for p in s.parts],
            }
            for s in batch
        ]
        try:
            result = await central.upload_segments(runtime.node_id, items)
        except CentralError as exc:
            logger.debug("Upload failed (will retry): %s", exc)
            return
        await LocalSegment.filter(id__in=[s.id for s in batch]).update(uploaded=True)
        if result.get("accepted"):
            logger.info("Uploaded %s chunk(s) to central (%s)", len(batch), result)
        if len(batch) < UPLOAD_BATCH:
            return


# ---------------------------------------------------------------- deletion (retention + disk pressure)


def _delete_file(rel: str) -> None:
    root = settings.RECORDINGS_DIR.resolve()
    path = (root / rel).resolve()
    if root not in path.parents:
        raise ValueError(f"refusing to delete outside recordings dir: {rel}")
    path.unlink(missing_ok=True)
    # Remove empty day folder.
    try:
        path.parent.rmdir()
    except OSError:
        pass


async def _delete_local(ids_paths: list[tuple[str, str]]) -> list[str]:
    deleted = []
    for seg_id, rel in ids_paths:
        try:
            await asyncio.to_thread(_delete_file, rel)
        except (OSError, ValueError) as exc:
            logger.error("Could not delete %s: %s", rel, exc)
            continue
        await LocalSegment.filter(id=seg_id).delete()
        _known.discard(rel)
        deleted.append(seg_id)
    return deleted


async def _confirm(ids: list[str]) -> None:
    pending = (await KeyValue.get_value(KV_PENDING_DELETED, [])) + ids
    if not pending or runtime.node_id is None:
        await KeyValue.set_value(KV_PENDING_DELETED, pending)
        return
    try:
        for i in range(0, len(pending), 1000):
            await central.confirm_deleted(runtime.node_id, pending[i : i + 1000])
        pending = []
    except CentralError as exc:
        logger.debug("Delete confirmation failed (will retry): %s", exc)
    await KeyValue.set_value(KV_PENDING_DELETED, pending)


async def disk_pressure_cleanup() -> list[str]:
    """Emergency cleanup: if the disk is above DISK_MAX_USED_PERCENT, delete the oldest chunks
    (never newer than DISK_MIN_KEEP_HOURS) until usage drops below DISK_TARGET_USED_PERCENT."""
    if disk_info()["used_percent"] < settings.DISK_MAX_USED_PERCENT:
        return []
    keep_after = utcnow() - timedelta(hours=settings.DISK_MIN_KEEP_HOURS)
    deleted: list[str] = []
    while disk_info()["used_percent"] > settings.DISK_TARGET_USED_PERCENT:
        oldest = await LocalSegment.filter(start_time__lt=keep_after).order_by("start_time").limit(50)
        if not oldest:
            logger.error("Disk above %.0f%% but nothing old enough to delete", settings.DISK_TARGET_USED_PERCENT)
            break
        deleted += await _delete_local([(str(s.id), s.rel_path) for s in oldest])
    if deleted:
        logger.warning("Disk pressure: deleted %s oldest chunk(s)", len(deleted))
    return deleted


async def recordings_used_bytes(max_age_seconds: float = 30.0) -> int:
    """Total size of indexed chunks on this node (cached for `max_age_seconds`)."""
    global _used_cache
    if time.monotonic() - _used_cache[0] > max_age_seconds:
        rows = await LocalSegment.all().annotate(total=Sum("size_bytes")).values("total")
        _used_cache = (time.monotonic(), int((rows[0]["total"] if rows else 0) or 0))
    return _used_cache[1]


async def quota_cleanup() -> list[str]:
    """If recordings exceed QUOTA_HIGH of the storage quota set by central, delete the oldest
    chunks (never newer than DISK_MIN_KEEP_HOURS) until usage drops below QUOTA_LOW."""
    quota = runtime.storage_quota_bytes
    if not quota:
        return []
    used = await recordings_used_bytes(max_age_seconds=0)
    if used <= quota * QUOTA_HIGH:
        return []
    keep_after = utcnow() - timedelta(hours=settings.DISK_MIN_KEEP_HOURS)
    deleted: list[str] = []
    while used > quota * QUOTA_LOW:
        # Pick just enough of the oldest chunks to get below QUOTA_LOW.
        oldest = await LocalSegment.filter(start_time__lt=keep_after).order_by("start_time").limit(200)
        if not oldest:
            logger.error("Recordings above storage quota but nothing old enough to delete")
            break
        batch, freed = [], 0
        for s in oldest:
            if used - freed <= quota * QUOTA_LOW:
                break
            batch.append(s)
            freed += s.size_bytes
        sizes = {str(s.id): s.size_bytes for s in batch}
        removed = await _delete_local([(str(s.id), s.rel_path) for s in batch])
        used -= sum(sizes[i] for i in removed)
        deleted += removed
        if not removed:
            break
    if deleted:
        logger.warning("Storage quota: deleted %s oldest chunk(s); now %.2f GB of %.2f GB",
                       len(deleted), used / 1024**3, quota / 1024**3)
    await recordings_used_bytes(max_age_seconds=0)
    return deleted


async def deletion_tick() -> None:
    deleted: list[str] = []
    if runtime.node_id is not None:
        try:
            todo = await central.pending_deletions(runtime.node_id)
        except CentralError as exc:
            logger.debug("Could not fetch deletions: %s", exc)
            todo = []
        if todo:
            deleted += await _delete_local([(d["id"], d["file_path"]) for d in todo])
            logger.info("Retention: deleted %s chunk(s)", len(deleted))
    deleted += await disk_pressure_cleanup()
    deleted += await quota_cleanup()
    await _confirm(deleted)


def read_slice(rel: str, offset: int, size: int) -> bytes:
    with open(Path(settings.RECORDINGS_DIR) / rel, "rb") as f:
        f.seek(offset)
        return f.read(size)


def file_exists(rel: str) -> bool:
    return os.path.isfile(settings.RECORDINGS_DIR / rel)
