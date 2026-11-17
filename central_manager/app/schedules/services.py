"""Recording schedules: the site clock, camera recording state, and bulk apply (docs/RECORDING_SCHEDULES_PLAN.md)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from tortoise.expressions import Q

from app.cameras.models import Camera
from app.schedules.models import RecordingSchedule
from app.schedules.utils import camera_mode, camera_next_change, mode_at, next_change, site_zone
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("central.schedules")
_warned: set[str] = set()


def site_timezone() -> str:
    """SITE_TIMEZONE, or this PC's current UTC offset ("+05:30") when it is not set."""
    name = settings.SITE_TIMEZONE.strip()
    if name:
        if site_zone(name) is timezone.utc and name.upper() not in ("UTC", "+00:00", "UTC+00:00") \
                and name not in _warned:
            _warned.add(name)
            logger.error("SITE_TIMEZONE=%r is not a known timezone; schedules run on UTC", name)
        return name
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def zone():
    return site_zone(site_timezone())


def recording_setting(camera: Camera, schedule: RecordingSchedule | None) -> dict:
    """What the node gets (and what the evaluator reads) for one camera."""
    mode = camera.recording_mode or "always"
    if mode == "schedule":
        if schedule is None:  # should not happen (FK RESTRICT); fail safe = record
            return {"mode": "always"}
        return {"mode": "schedule", "schedule_id": schedule.id, "blocks": schedule.blocks,
                "version": schedule.updated_at.isoformat() if schedule.updated_at else None}
    return {"mode": mode}


async def schedules_by_id(ids) -> dict[int, RecordingSchedule]:
    ids = {i for i in ids if i is not None}
    return {s.id: s for s in await RecordingSchedule.filter(id__in=ids)} if ids else {}


def camera_state(camera: Camera, schedule: RecordingSchedule | None, now: datetime | None = None) -> tuple[bool, datetime | None]:
    """(recording now by the schedule/mode, next change in site wall clock)."""
    now = now or utcnow()
    setting, tz = recording_setting(camera, schedule), zone()
    return camera_mode(setting, now, tz) == "continuous", camera_next_change(setting, now, tz)


async def scheduled_off_camera_ids(camera_ids=None) -> set[int]:
    """Cameras whose recorded streams are meant to be idle right now (mode never, or schedule off)."""
    qs = Camera.filter(recording_mode__in=("never", "schedule"))
    if camera_ids is not None:
        qs = qs.filter(id__in=list(camera_ids))
    cams = await qs
    schedules = await schedules_by_id(c.recording_schedule_id for c in cams)
    now, tz = utcnow(), zone()
    return {c.id for c in cams
            if camera_mode(recording_setting(c, schedules.get(c.recording_schedule_id)), now, tz) == "off"}


def schedule_state(schedule: RecordingSchedule, now: datetime | None = None) -> tuple[bool, datetime | None]:
    local = (now or utcnow()).astimezone(zone())
    return mode_at(schedule.blocks, local) == "continuous", next_change(schedule.blocks, local)


def preview(schedule: RecordingSchedule, start: datetime, days: int) -> list[dict]:
    """On/off spans from `start` for `days` days, in site wall clock."""
    local = start.astimezone(zone())
    end = local + timedelta(days=days)
    spans, t = [], local
    while t < end:
        mode = mode_at(schedule.blocks, t)
        nxt = next_change(schedule.blocks, t)
        stop = min(nxt, end) if nxt and nxt > t else end
        spans.append({"start": t, "end": stop, "mode": mode})
        t = stop
    return spans


async def get_schedule(schedule_id: int) -> RecordingSchedule:
    s = await RecordingSchedule.get_or_none(id=schedule_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found")
    return s


async def check_camera_recording(mode: str | None, schedule_id: int | None) -> None:
    """422 for a camera update that names a missing schedule, or mode 'schedule' without one."""
    if mode == "schedule" and schedule_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick a schedule for recording mode 'schedule'")
    if schedule_id is not None and not await RecordingSchedule.filter(id=schedule_id).exists():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Schedule {schedule_id} does not exist")


async def apply(mode: str, schedule_id: int | None, camera_ids: list[int], group_q: Q | None,
                visible_q: Q | None) -> int:
    if schedule_id is not None:
        await get_schedule(schedule_id)
    target = Q(id__in=list(set(camera_ids))) if camera_ids else None
    if group_q is not None:
        target = group_q if target is None else (target | group_q)
    qs = Camera.filter(target)
    if visible_q is not None:
        qs = qs.filter(visible_q)
    return await qs.update(recording_mode=mode, recording_schedule_id=schedule_id if mode == "schedule" else None)
