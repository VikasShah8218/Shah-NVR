import logging
from datetime import timedelta

from app.cameras.models import Camera
from app.recordings.models import RecordingSegment, SegmentStatus
from utilities.common import utcnow

logger = logging.getLogger("central.retention")


async def retention_tick() -> None:
    """Mark segments older than each camera's retention as DELETING.
    The owning node polls for them, deletes the files and confirms."""
    now = utcnow()
    total = 0
    for camera in await Camera.all().only("id", "retention_days"):
        cutoff = now - timedelta(days=camera.retention_days)
        total += await RecordingSegment.filter(
            camera_id=camera.id, status=SegmentStatus.AVAILABLE, end_time__lt=cutoff
        ).update(status=SegmentStatus.DELETING)
    if total:
        logger.info("Retention: %s segment(s) scheduled for deletion", total)
