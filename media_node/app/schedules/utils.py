"""Recording schedule evaluator (docs/RECORDING_SCHEDULES_PLAN.md §4.2).

SHARED FILE: an identical copy lives in media_node/app/schedules/utils.py (the node decides when to record; central
uses the same answer for status, alerts and the "recording until" hint). Change both; a test checks they match.

A schedule is a list of weekly blocks `{"days": [0-6], "start": "HH:MM", "end": "HH:MM", "mode": "continuous"}`,
Mon=0 ... Sun=6, in the site's wall-clock time. `end <= start` runs past midnight into the next day
(`start == end` = 24 hours). `end` may be "24:00". Overlapping blocks: the strongest mode wins
(continuous > event > off). A time no block covers is "off". Malformed blocks are ignored here (the API
validates them on write).

A camera's recording setting is `{"mode": "always" | "never" | "schedule" | "event", "blocks": [...],
"events": {"pre": s, "post": s, "marking": bool, "max": s}}`; a missing setting is "always" (central older than the
node, or a camera saved before schedules existed). Mode "event" (and schedule blocks with mode "event") keep video only
around events (docs/EVENT_RECORDING_PLAN.md).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

MODES = ("off", "event", "continuous")  # weakest -> strongest
CAMERA_MODES = ("always", "schedule", "never", "event")
WEEK = 7 * 24 * 60


def parse_hhmm(value: str) -> int:
    """'08:30' -> 510 minutes. '24:00' is allowed. ValueError on anything else."""
    hh, _, mm = str(value).partition(":")
    if len(hh) != 2 or len(mm) != 2 or not hh.isdigit() or not mm.isdigit():
        raise ValueError(f"time must be HH:MM, got {value!r}")
    h, m = int(hh), int(mm)
    if m > 59 or h > 24 or (h == 24 and m):
        raise ValueError(f"time out of range: {value!r}")
    return h * 60 + m


def _intervals(blocks) -> list[tuple[int, int, int]]:
    """(start, end, strength) in minutes of the week; end may pass the week end (Sunday night -> Monday)."""
    out = []
    for b in blocks or ():
        try:
            start, end = parse_hhmm(b["start"]), parse_hhmm(b["end"])
            strength = MODES.index(b.get("mode", "continuous"))
            days = {int(d) for d in b["days"] if 0 <= int(d) <= 6}
        except (KeyError, TypeError, ValueError):
            continue
        length = end - start if end > start else end - start + 24 * 60
        for d in days:
            out.append((d * 1440 + start, d * 1440 + start + length, strength))
    return out


def _minute_of_week(local: datetime) -> int:
    return local.weekday() * 1440 + local.hour * 60 + local.minute


def _mode_at_minute(intervals, m: int) -> str:
    best = 0
    for start, end, strength in intervals:
        if strength > best and (start <= m < end or start <= m + WEEK < end):
            best = strength
    return MODES[best]


def mode_at(blocks, local: datetime) -> str:
    """The schedule's mode at a wall-clock time of the site."""
    return _mode_at_minute(_intervals(blocks), _minute_of_week(local))


def next_change(blocks, local: datetime) -> datetime | None:
    """When the mode next changes (a wall-clock time in local's zone), or None when it never changes."""
    intervals = _intervals(blocks)
    now_m = _minute_of_week(local)
    current = _mode_at_minute(intervals, now_m)
    edges = {e % WEEK for start, end, _ in intervals for e in (start, end)}
    base = local.replace(second=0, microsecond=0, tzinfo=None)
    for delta in sorted((e - now_m) % WEEK or WEEK for e in edges):
        if _mode_at_minute(intervals, (now_m + delta) % WEEK) != current:
            return (base + timedelta(minutes=delta)).replace(tzinfo=local.tzinfo)
    return None


def site_zone(name: str | None) -> tzinfo:
    """The site timezone: an IANA name ("Asia/Kolkata") or a fixed offset ("+05:30", "UTC-03:00").
    UTC when empty or unknown (the caller logs that)."""
    name = (name or "").strip()
    offset = name.removeprefix("UTC") if name.startswith(("UTC+", "UTC-")) else name
    if offset[:1] in ("+", "-"):
        try:
            minutes = parse_hhmm(offset[1:])
        except ValueError:
            return timezone.utc
        return timezone(timedelta(minutes=minutes if offset[0] == "+" else -minutes))
    if name:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - ZoneInfoNotFoundError, or no tz database at all
            pass
    return timezone.utc


def camera_mode(recording: dict | None, now: datetime, zone: tzinfo) -> str:
    """What a camera's recorded streams should do now: 'continuous', 'event' or 'off'. `now` is timezone-aware."""
    mode = (recording or {}).get("mode", "always")
    if mode == "never":
        return "off"
    if mode == "event":
        return "event"
    if mode == "schedule":
        return mode_at(recording.get("blocks"), now.astimezone(zone))
    return "continuous"


def may_use_events(recording: dict | None) -> bool:
    """Whether the camera can ever be in event mode (mode "event", or a schedule with an event block)."""
    mode = (recording or {}).get("mode", "always")
    if mode == "event":
        return True
    return mode == "schedule" and any(b.get("mode") == "event" for b in recording.get("blocks") or ()
                                      if isinstance(b, dict))


def camera_next_change(recording: dict | None, now: datetime, zone: tzinfo) -> datetime | None:
    if (recording or {}).get("mode") != "schedule":
        return None
    return next_change(recording.get("blocks"), now.astimezone(zone))
