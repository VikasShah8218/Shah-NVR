from datetime import datetime, timedelta

from app.recordings.models import RecordingSegment, SegmentStatus
from settings.settings import settings


async def find_segments(camera_id: int, profile: str, start: datetime, end: datetime) -> list[RecordingSegment]:
    """All available segments overlapping [start, end), oldest first."""
    return await RecordingSegment.filter(
        camera_id=camera_id,
        profile=profile,
        status=SegmentStatus.AVAILABLE,
        start_time__lt=end,
        end_time__gt=start,
    ).order_by("start_time", "-generation")


def compute_gaps(
    segments: list[RecordingSegment], start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Intervals inside [start, end) not covered by any segment (overlaps from failover are merged)."""
    tolerance = timedelta(seconds=settings.PLAYBACK_GAP_TOLERANCE_SECONDS)
    gaps = []
    cursor = start
    for seg in segments:
        if seg.start_time > cursor + tolerance:
            gaps.append((cursor, min(seg.start_time, end)))
        cursor = max(cursor, seg.end_time)
        if cursor >= end:
            break
    if cursor + tolerance < end:
        gaps.append((cursor, end))
    return gaps
