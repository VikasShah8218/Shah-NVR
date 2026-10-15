import logging
from datetime import timedelta

from tortoise.functions import Max

from app.cameras.models import Camera
from app.recordings.models import RecordingSegment, SegmentStatus
from utilities.common import utcnow

logger = logging.getLogger("central.retention")


async def retention_tick() -> None:
    """Age-based retention: mark chunks older than each camera's limit as DELETING; the owning node deletes the
    files and confirms.

    The limit counts back from the camera's *latest recording* (per stream profile), not from "now":
    * while a camera records, this is a rolling window of `retention_days` (e.g. 1 day: at hour 25 the first
      hour goes);
    * when a camera stops (manual stop, fault, disabled), nothing more is deleted by age: its last
      `retention_days` of footage stay (stopped at hour 25 -> at hour 30 still hours 1-25).
    * `retention_days = None` means "keep until storage is full": never deleted by age.

    Space is handled separately on the node (fill in order, overwrite the oldest when all storage is full), so
    recording never stops for lack of space whatever is set here.
    """
    now = utcnow()
    limits = {c["id"]: c["retention_days"]
              for c in await Camera.filter(retention_days__isnull=False).values("id", "retention_days")}
    if not limits:
        return
    newest_rows = (
        await RecordingSegment.filter(camera_id__in=list(limits), status=SegmentStatus.AVAILABLE)
        .annotate(newest=Max("end_time"))
        .group_by("camera_id", "profile")
        .values("camera_id", "profile", "newest")
    )
    total = 0
    for row in newest_rows:
        anchor = min(row["newest"], now)  # a camera clock in the future must not shorten everything
        cutoff = anchor - timedelta(days=limits[row["camera_id"]])
        total += await RecordingSegment.filter(
            camera_id=row["camera_id"], profile=row["profile"], status=SegmentStatus.AVAILABLE, end_time__lt=cutoff
        ).update(status=SegmentStatus.DELETING)
    if total:
        logger.info("Retention: %s segment(s) scheduled for deletion", total)
