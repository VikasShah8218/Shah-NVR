import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status

from app.cameras.models import Camera, CameraStream
from app.nodes.models import MediaNode, StorageVolume
from app.recordings.models import RecordingSegment, SegmentStatus
from app.recordings.schemas import (
    DeletedIn,
    DeletionItem,
    GapOut,
    SegmentBatchIn,
    SegmentBatchOut,
    SegmentOut,
    TimelineOut,
)
from app.recordings.utils import compute_gaps, find_segments
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("central.recordings")

router = APIRouter(prefix="/api/v1/cameras", tags=["Recordings"])
internal_router = APIRouter(prefix="/internal/v1", tags=["Internal: Recordings"])


def resolve_range(start: datetime | None, end: datetime | None, minutes: int | None) -> tuple[datetime, datetime]:
    """Naive datetimes are treated as UTC. `minutes` = the last N minutes up to now."""
    if minutes is not None:
        end = utcnow()
        start = end - timedelta(minutes=minutes)
    if start is None or end is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provide start & end, or minutes")
    start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    if end <= start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "end must be after start")
    if end - start > timedelta(hours=settings.PLAYBACK_MAX_HOURS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Range limited to {settings.PLAYBACK_MAX_HOURS}h")
    return start, end


# ================================================================ public API


@router.get("/{camera_id}/recordings", response_model=TimelineOut, summary="Recording timeline (segments + gaps)")
async def timeline(
    camera_id: int,
    profile: str = "main",
    start: datetime | None = Query(default=None, examples=["2026-10-11T10:00:00Z"]),
    end: datetime | None = Query(default=None, examples=["2026-10-11T11:00:00Z"]),
    minutes: int | None = Query(default=None, ge=1, description="Shortcut: the last N minutes"),
):
    if not await Camera.exists(id=camera_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    start, end = resolve_range(start, end, minutes)
    segments = await find_segments(camera_id, profile, start, end)
    gaps = compute_gaps(segments, start, end)

    window = (end - start).total_seconds()
    gap_seconds = sum((g[1] - g[0]).total_seconds() for g in gaps)
    recorded = max(0.0, window - gap_seconds)
    return TimelineOut(
        camera_id=camera_id,
        profile=profile,
        start=start,
        end=end,
        recorded_seconds=round(recorded, 3),
        coverage_percent=round(100 * recorded / window, 2),
        total_size_bytes=sum(s.size_bytes for s in segments),
        segments=[SegmentOut.model_validate(s, from_attributes=True) for s in segments],
        gaps=[GapOut(start_time=a, end_time=b, seconds=round((b - a).total_seconds(), 3)) for a, b in gaps],
    )


# ================================================================ internal API (called by media nodes)


@internal_router.post("/recordings/segments", response_model=SegmentBatchOut)
async def ingest_segments(body: SegmentBatchIn):
    """Idempotent: re-sending the same segment ids is safe."""
    if not await MediaNode.exists(id=body.node_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")

    ids = [s.id for s in body.items]
    existing = set(await RecordingSegment.filter(id__in=ids).values_list("id", flat=True))
    known_cameras = set(
        await Camera.filter(id__in={s.camera_id for s in body.items}).values_list("id", flat=True)
    )
    node_volumes = set(await StorageVolume.filter(node_id=body.node_id).values_list("id", flat=True))

    new_rows = []
    latest: dict[tuple[int, str], datetime] = {}
    ignored = 0
    for s in body.items:
        if s.id in existing:
            continue
        if s.camera_id not in known_cameras:
            ignored += 1
            continue
        row = s.model_dump()
        if row["volume_id"] not in node_volumes:  # unknown / removed volume: keep the row, drop the link
            row["volume_id"] = None
        new_rows.append(RecordingSegment(**row, node_id=body.node_id))
        key = (s.camera_id, s.profile)
        if key not in latest or s.end_time > latest[key]:
            latest[key] = s.end_time

    if new_rows:
        await RecordingSegment.bulk_create(new_rows, ignore_conflicts=True)
    for (camera_id, profile), end_time in latest.items():
        stream = await CameraStream.get_or_none(camera_id=camera_id, profile=profile)
        if stream and (stream.last_segment_at is None or end_time > stream.last_segment_at):
            stream.last_segment_at = end_time
            await stream.save(update_fields=["last_segment_at"])

    return SegmentBatchOut(accepted=len(new_rows), duplicates=len(existing), ignored=ignored)


@internal_router.get("/nodes/{node_id}/deletions", response_model=list[DeletionItem])
async def pending_deletions(node_id: int, limit: int = Query(default=500, le=5000)):
    rows = await RecordingSegment.filter(node_id=node_id, status=SegmentStatus.DELETING).limit(limit)
    return [DeletionItem(id=r.id, file_path=r.file_path, volume_id=r.volume_id) for r in rows]


@internal_router.post("/nodes/{node_id}/deleted", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_deleted(node_id: int, body: DeletedIn):
    """Node confirms files are gone (retention or disk-pressure cleanup)."""
    if body.ids:
        n = await RecordingSegment.filter(node_id=node_id, id__in=body.ids).delete()
        logger.info("Node %s deleted %s segment(s)", node_id, n)
