"""When this node's recorded streams record (docs/RECORDING_SCHEDULES_PLAN.md §5).

Central sends each camera's recording setting (always / never / a weekly schedule) with the assignments, plus the
site timezone. Both are cached with the assignments, so schedules keep running while central is down. The reconcile
tick (every RECONCILE_INTERVAL_SECONDS) asks `recording_on()` and PATCHes MediaMTX `record` when the answer
changes; the source stays connected, so live view is not interrupted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.node.utils import runtime
from app.schedules.utils import camera_mode, camera_next_change, site_zone
from utilities.common import utcnow

logger = logging.getLogger("node.schedules")
_zone_cache: dict[str, object] = {}
_last_state: dict[int, str] = {}  # camera id -> mode (continuous / event / off), for the transition log
EVENT_DEFAULTS = {"pre": 10, "post": 30, "marking": True, "max": 300}


def zone():
    name = runtime.site_timezone or "UTC"
    tz = _zone_cache.get(name)
    if tz is None:
        tz = _zone_cache[name] = site_zone(name)
        if tz is timezone.utc and name.upper() not in ("UTC", "+00:00", "UTC+00:00"):
            logger.error("Unknown site timezone %r from central; recording schedules run on UTC", name)
    return tz


def mode_now(cam: dict, now: datetime | None = None) -> str:
    """The camera's recording mode at `now`: continuous / event / off."""
    return camera_mode(cam.get("recording"), now or utcnow(), zone())


def recording_on(cam: dict, now: datetime | None = None) -> bool:
    """Whether MediaMTX writes chunks for the camera's recorded streams right now. In event mode it does too:
    the chunks are held and kept only around events (app/events)."""
    return mode_now(cam, now) != "off"


def event_setting(cam: dict | None) -> dict:
    """{"pre", "post", "marking", "max"} of the camera (defaults for a central older than event recording)."""
    return {**EVENT_DEFAULTS, **(((cam or {}).get("recording") or {}).get("events") or {})}


def next_change(cam: dict, now: datetime | None = None) -> datetime | None:
    return camera_next_change(cam.get("recording"), now or utcnow(), zone())


def format_change(when: datetime, now: datetime) -> str:
    """'Mon 18:00', or 'Mon 23 Nov 18:00' when it is a week or more away (same weekday)."""
    local_now = now.astimezone(when.tzinfo) if when.tzinfo else now
    return f"{when:%a %d %b %H:%M}" if when - local_now >= timedelta(days=6) else f"{when:%a %H:%M}"


def log_transitions(now: datetime | None = None) -> None:
    """One log line per camera when its schedule turns recording on or off (and once at start-up)."""
    now = now or utcnow()
    for cid, cam in runtime.assignments.items():
        if not any(s["record"] for s in cam["streams"]):
            continue
        state = mode_now(cam, now)
        if _last_state.get(cid) != state:
            _last_state[cid] = state
            nxt = next_change(cam, now)
            until = f" until {format_change(nxt, now)}" if nxt else ""
            mode = (cam.get("recording") or {}).get("mode", "always")
            word = {"continuous": "ON", "off": "OFF"}.get(state, "ON EVENTS (video kept around events)")
            logger.info("Recording %s for camera %s (%s, %s)%s", word, cid, cam.get("camera_name", "?"), mode, until)
    for cid in list(_last_state):
        if cid not in runtime.assignments:
            del _last_state[cid]
