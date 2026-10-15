"""Recording pipeline on the node:

  MediaMTX writes chunk  ->  scanner finds finished chunk  ->  indexer (byte offsets of keyframe parts)
  ->  LocalSegment row (SQLite, upload queue)  ->  uploader batches metadata to central
  ->  retention / disk safety / volume caps / overwrite-when-all-full delete files, confirmed to central.

Chunks live on storage volumes (app/storage): MediaMTX writes to the current target volume; the
scanner walks every healthy volume; LocalSegment.volume_id says where each chunk is.
"""

import asyncio
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path

from tortoise.expressions import Q
from tortoise.functions import Sum

from app.node.models import KeyValue
from app.node.utils import CentralError, central, runtime
from app.recordings.models import LocalSegment, SkippedFile
from app.recordings.utils import Mp4IndexError, index_fmp4, parse_rel_path, segment_uuid
from app.storage.services import storage
from app.storage.utils import FREE_BELOW
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("node.recordings")

KV_PENDING_DELETED = "pending_deleted"
UPLOAD_BATCH = 200
SCAN_TIMEOUT_SECONDS = 60  # one volume's folder walk (a dead network share must not hang the scanner)
OVERWRITE_MAX_CHUNKS = 2000  # per deletion tick
CAP_TRIM_TO = 0.99  # hard-cap trimming target (fraction of the cap); must stay above storage FREE_BELOW
RECENT_DAY_DIRS = 2  # after the first full scan, only the newest N day folders are scanned

_known: set[str] = set()
_reported: set[str] = set()  # cleanup problems already logged (each is logged once until it clears)
_full_scan_done = False
_used_cache: tuple[float, int] = (0.0, 0)


# ---------------------------------------------------------------- scanner


def _list_finished_files(root: Path, full: bool) -> list[str]:
    """Paths (relative to `root`) of chunks that MediaMTX has finished writing in one volume.

    A chunk is finished when a newer chunk exists for the same stream, or when it has not
    been modified for a while (camera disconnected / path stopped)."""
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


def _index_file(root: Path, rel: str):
    info = parse_rel_path(rel)
    idx = index_fmp4(root / rel, settings.HLS_PART_TARGET_SECONDS)
    return info, idx


def _segment_id(key: int | None, rel: str):
    # The default volume keeps the original id scheme, so chunks indexed before storage volumes keep their ids.
    return segment_uuid(settings.NODE_NAME, rel if key is None else f"v{key}/{rel}")


async def _load_known() -> None:
    since = utcnow() - timedelta(days=RECENT_DAY_DIRS + 1)
    _known.update(await LocalSegment.filter(start_time__gte=since).values_list("rel_path", flat=True))
    _known.update(await SkippedFile.all().values_list("rel_path", flat=True))


async def scan_tick() -> None:
    global _full_scan_done
    full = not _full_scan_done
    if full:
        await _load_known()
    candidates: list[tuple[int | None, Path, str]] = []
    for key, root in storage.scan_roots():
        try:
            rels = await asyncio.wait_for(asyncio.to_thread(_list_finished_files, root, full), SCAN_TIMEOUT_SECONDS)
        except (OSError, asyncio.TimeoutError) as exc:
            logger.warning("Cannot scan %s: %r", root, exc)
            continue
        candidates += [(key, root, r) for r in rels]
    if full:
        # First scan also checks old folders, so files written while the agent was down are not lost.
        old = [c for c in candidates if not await LocalSegment.exists(rel_path=c[2])]
        candidates = [c for c in old if not await SkippedFile.exists(rel_path=c[2])]
        _full_scan_done = True
        if candidates:
            logger.info("Recovery scan: %s unindexed chunk(s) found", len(candidates))

    for key, root, rel in candidates:
        try:
            info, idx = await asyncio.to_thread(_index_file, root, rel)
        except (Mp4IndexError, ValueError, OSError) as exc:
            logger.warning("Skipping chunk %s: %s", rel, exc)
            await SkippedFile.update_or_create(rel_path=rel, defaults={"reason": str(exc)[:250], "volume_id": key})
            _known.add(rel)
            continue

        end_time = info.start_time + timedelta(milliseconds=idx.duration_ms)
        await LocalSegment.update_or_create(
            rel_path=rel,
            defaults=dict(
                id=_segment_id(key, rel),
                volume_id=key,
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
        stream = (info.camera_id, info.profile)
        if stream not in runtime.last_segment_end or end_time > runtime.last_segment_end[stream]:
            runtime.last_segment_end[stream] = end_time
        logger.debug("Indexed %s on %s (%.1fs, %s parts)", rel, root, idx.duration_ms / 1000, len(idx.parts))


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
                "volume_id": storage.central_id(s.volume_id),
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


# ---------------------------------------------------------------- deletion (retention + storage cleanup)


def _delete_file(root: Path, rel: str) -> None:
    root = root.resolve()
    path = (root / rel).resolve()
    if root not in path.parents:
        raise ValueError(f"refusing to delete outside the storage folder: {rel}")
    path.unlink(missing_ok=True)
    # Remove empty day folder.
    try:
        path.parent.rmdir()
    except OSError:
        pass


async def _delete_local(items: list[tuple[str, int | None, str]]) -> list[str]:
    """Delete chunks given as (segment id, volume key, relative path). Returns the ids actually deleted.

    Chunks on a volume that is offline are skipped (not confirmed), so they are retried later."""
    deleted = []
    for seg_id, key, rel in items:
        volume = storage.get(key)
        if volume is None or not volume.usable:
            continue
        try:
            await asyncio.to_thread(_delete_file, volume.path, rel)
        except (OSError, ValueError) as exc:
            logger.error("Could not delete %s on %s: %s", rel, volume.path, exc)
            continue
        await LocalSegment.filter(id=seg_id).delete()
        _known.discard(rel)
        deleted.append(seg_id)
    return deleted


def _as_items(segments) -> list[tuple[str, int | None, str]]:
    return [(str(s.id), s.volume_id, s.rel_path) for s in segments]


def _on_volume(key: int | None) -> Q:
    return Q(volume_id__isnull=True) if key is None else Q(volume_id=key)


def _on_volumes(keys) -> Q:
    keys = list(keys)
    q = Q(volume_id__in=[k for k in keys if k is not None])
    return q | Q(volume_id__isnull=True) if None in keys else q


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


def _report_once(key: str, message: str, *args) -> None:
    if key not in _reported:
        _reported.add(key)
        logger.error(message, *args)


def _resolved(key: str) -> None:
    _reported.discard(key)


def _disk_percent(path: Path) -> float:
    usage = shutil.disk_usage(path)
    return 100 * usage.used / usage.total


async def disk_safety_cleanup() -> list[str]:
    """Protect each volume's disk (often the OS drive): above DISK_MAX_USED_PERCENT, delete that volume's
    oldest chunks (never newer than DISK_MIN_KEEP_HOURS) until it is below DISK_TARGET_USED_PERCENT."""
    keep_after = utcnow() - timedelta(hours=settings.DISK_MIN_KEEP_HOURS)
    deleted: list[str] = []
    for v in storage.ordered():
        if not v.usable or (v.disk_used_percent or 0) < settings.DISK_MAX_USED_PERCENT:
            continue
        removed = 0
        while await asyncio.to_thread(_disk_percent, v.path) > settings.DISK_TARGET_USED_PERCENT:
            oldest = await LocalSegment.filter(_on_volume(v.key), start_time__lt=keep_after).order_by("start_time").limit(50)
            if not oldest:
                _report_once(f"disk:{v.key}", "Disk of %s above %.0f%% but none of its chunks is old enough to delete",
                             v.path, settings.DISK_TARGET_USED_PERCENT)
                break
            batch = await _delete_local(_as_items(oldest))
            if not batch:
                break
            removed += len(batch)
            deleted += batch
        if removed:
            logger.warning("Disk pressure on %s: deleted %s oldest chunk(s)", v.path, removed)
    return deleted


async def _volume_used(key: int | None) -> int:
    rows = await LocalSegment.filter(_on_volume(key)).annotate(total=Sum("size_bytes")).values("total")
    return int((rows[0]["total"] if rows else 0) or 0)


async def cap_cleanup() -> list[str]:
    """Hard cap: a volume holding more than its cap (e.g. the cap was lowered) loses its oldest chunks
    down to just under the cap. Recording normally moves on at 95%, so this only trims the overshoot.
    It deliberately stops above the 90% "free again" mark: the volume stays FULL, so the fill order is kept
    (trimming further would pull recording back here and skip the later volumes)."""
    keep_after = utcnow() - timedelta(hours=settings.DISK_MIN_KEEP_HOURS)
    deleted: list[str] = []
    for v in storage.ordered():
        if not v.quota_bytes or not v.usable:
            continue
        used = await _volume_used(v.key)
        if used <= v.quota_bytes:
            _resolved(f"cap:{v.key}")
            continue
        target = v.quota_bytes * CAP_TRIM_TO
        while used > target:
            oldest = await LocalSegment.filter(_on_volume(v.key), start_time__lt=keep_after).order_by("start_time").limit(200)
            if not oldest:
                _report_once(f"cap:{v.key}", "%s is over its cap but none of its chunks is old enough to delete", v.path)
                break
            batch, freed = [], 0
            for s in oldest:
                if used - freed <= target:
                    break
                batch.append(s)
                freed += s.size_bytes
            sizes = {str(s.id): s.size_bytes for s in batch}
            removed = await _delete_local(_as_items(batch))
            used -= sum(sizes[i] for i in removed)
            deleted += removed
            if not removed:
                break
        if deleted:
            logger.warning("%s was over its cap: now %.2f GB of %.2f GB", v.path, used / 1024**3, v.quota_bytes / 1024**3)
    return deleted


async def overwrite_cleanup() -> list[str]:
    """Every accepting volume is full: overwrite the oldest recordings (ring buffer).

    Chunks are chosen oldest-first, one at a time, keeping a running estimate of each volume's usage; it
    stops as soon as one volume would be "free again" (below 90% of its cap and below the disk target).
    Recording then returns to the first volume with room, in fill order. Deleting more than needed
    would throw away footage for nothing."""
    if not storage.all_full():
        _resolved("overwrite")
        return []
    keep_after = utcnow() - timedelta(hours=settings.DISK_MIN_KEEP_HOURS)
    volumes = {v.key: v for v in storage.ordered() if v.accepting and v.usable}
    used = {k: v.recordings_bytes for k, v in volumes.items()}
    disk_used = {k: (v.disk_used_percent or 0) / 100 * (v.total_bytes or 0) for k, v in volumes.items()}

    def free_again(k) -> bool:
        v = volumes[k]
        under_cap = not v.quota_bytes or used[k] < v.quota_bytes * FREE_BELOW
        disk_ok = not v.total_bytes or 100 * disk_used[k] / v.total_bytes < settings.DISK_TARGET_USED_PERCENT
        return under_cap and disk_ok

    chosen = []
    offset = 0
    done = False
    while not done and len(chosen) < OVERWRITE_MAX_CHUNKS:
        page = await (LocalSegment.filter(_on_volumes(volumes), start_time__lt=keep_after)
                      .order_by("start_time").offset(offset).limit(100))
        if not page:
            break
        offset += len(page)
        for seg in page:
            chosen.append(seg)
            used[seg.volume_id] -= seg.size_bytes
            disk_used[seg.volume_id] -= seg.size_bytes
            if free_again(seg.volume_id):
                done = True
                break
    if not chosen:
        _report_once("overwrite", "All storage is full but no chunk is older than DISK_MIN_KEEP_HOURS (%s h) "
                     "to overwrite", settings.DISK_MIN_KEEP_HOURS)
        return []
    deleted = await _delete_local(_as_items(chosen))
    if deleted:
        logger.warning("All storage full: overwrote %s oldest chunk(s)", len(deleted))
    return deleted


async def recordings_used_bytes(max_age_seconds: float = 30.0) -> int:
    """Total size of indexed chunks on this node, all volumes (cached for `max_age_seconds`)."""
    global _used_cache
    if time.monotonic() - _used_cache[0] > max_age_seconds:
        rows = await LocalSegment.all().annotate(total=Sum("size_bytes")).values("total")
        _used_cache = (time.monotonic(), int((rows[0]["total"] if rows else 0) or 0))
    return _used_cache[1]


async def _central_deletions() -> list[str]:
    """Retention decided by central (days per camera)."""
    if runtime.node_id is None:
        return []
    try:
        todo = await central.pending_deletions(runtime.node_id)
    except CentralError as exc:
        logger.debug("Could not fetch deletions: %s", exc)
        return []
    if not todo:
        return []
    local = {str(s.id): s for s in await LocalSegment.filter(id__in=[d["id"] for d in todo])}
    items = []
    for d in todo:
        s = local.get(d["id"])
        if s is not None:  # trust our own record of where the file is
            items.append((d["id"], s.volume_id, s.rel_path))
        else:
            items.append((d["id"], storage.key_for_central(d.get("volume_id")), d["file_path"]))
    deleted = await _delete_local(items)
    if deleted:
        logger.info("Retention: deleted %s chunk(s)", len(deleted))
    return deleted


async def deletion_tick() -> None:
    deleted = await _central_deletions()
    deleted += await disk_safety_cleanup()
    deleted += await cap_cleanup()
    deleted += await overwrite_cleanup()
    if deleted:
        await recordings_used_bytes(max_age_seconds=0)
        await storage.refresh()
    await _confirm(deleted)


def read_slice(root: Path, rel: str, offset: int, size: int) -> bytes:
    with open(root / rel, "rb") as f:
        f.seek(offset)
        return f.read(size)


def file_exists(root: Path, rel: str) -> bool:
    return os.path.isfile(root / rel)
