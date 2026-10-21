"""Opt-in L3 automatic gap detection. At most one queued/running job per camera."""

import logging
from datetime import timedelta

from app.backfill.router import ACTIVE, MAX_JOB, RECENT_SAFETY, create_backfill_job, probe_backfill
from app.backfill.schemas import BackfillJobCreate
from app.cameras.models import Camera, CameraStream
from app.recordings.models import BackfillJob
from app.recordings.utils import compute_gaps, find_segments
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("central.backfill")


async def backfill_scheduler_tick() -> None:
    now = utcnow()
    cameras = await Camera.filter(backfill_mode="automatic", backfill_capability="supported")
    for camera in cameras:
        if await BackfillJob.filter(camera_id=camera.id, state__in=ACTIVE).exists():
            continue
        if camera.backfill_checked_at is None or now - camera.backfill_checked_at > timedelta(
            seconds=settings.BACKFILL_PROBE_INTERVAL_SECONDS
        ):
            try:
                await probe_backfill(camera.id)
                camera = await Camera.get(id=camera.id)
            except Exception as exc:
                logger.info("Automatic backfill probe failed for camera %s: %s", camera.id, exc)
                continue
        stream = await CameraStream.get_or_none(camera_id=camera.id, profile=camera.backfill_profile, record=True)
        if stream is None or not camera.backfill_earliest or not camera.backfill_latest:
            continue
        end = min(now - RECENT_SAFETY, camera.backfill_latest)
        # The configured lookback is relative to current time, not the newest
        # item still retained by a camera. Otherwise a stale SD card could make
        # automatic mode unexpectedly import days-old footage.
        start = max(
            camera.backfill_earliest,
            now - timedelta(hours=settings.BACKFILL_MAX_LOOKBACK_HOURS),
        )
        if end <= start:
            continue
        gaps = compute_gaps(await find_segments(camera.id, camera.backfill_profile, start, end), start, end)
        if not gaps:
            continue
        # Recover newest footage first. Queue only one bounded job; the next cycle
        # waits while it runs and then recalculates coverage.
        gap_start, gap_end = gaps[-1]
        gap_start = max(gap_start, gap_end - MAX_JOB)
        try:
            created = await create_backfill_job(camera.id, BackfillJobCreate(
                start_time=gap_start, end_time=gap_end, profile=camera.backfill_profile,
            ))
            await BackfillJob.filter(id=created.id).update(requested_by="automatic")
            logger.info("Queued automatic backfill for camera %s: %s to %s", camera.id, gap_start, gap_end)
        except Exception as exc:
            logger.info("Automatic backfill skipped for camera %s: %s", camera.id, exc)
