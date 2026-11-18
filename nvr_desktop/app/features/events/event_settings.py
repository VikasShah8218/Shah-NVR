"""Event recording settings of a camera (port of nvr_client/src/lib/eventSettings.ts, docs/EVENT_RECORDING_PLAN.md E6)."""

from __future__ import annotations

EVENT_DEFAULTS = {"pre": 10, "post": 30, "marking": True}
PRE_MAX = 60
POST_MAX = 600
INVALID_TEXT = "Before: 0–60 s, after: 0–600 s."


def _int(value) -> int | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else None


def valid(e: dict) -> bool:
    pre, post = _int(e.get("pre")), _int(e.get("post"))
    return pre is not None and post is not None and 0 <= pre <= PRE_MAX and 0 <= post <= POST_MAX


def of_camera(cam: dict | None) -> dict:
    """The event settings of a camera (API dict), or the defaults for a new one."""
    if not cam:
        return dict(EVENT_DEFAULTS)
    return {"pre": cam.get("event_pre_seconds", 10), "post": cam.get("event_post_seconds", 30),
            "marking": cam.get("event_marking", True) is not False}


def body(e: dict) -> dict:
    """Camera create / update fields."""
    return {"event_pre_seconds": _int(e.get("pre")) or 0, "event_post_seconds": _int(e.get("post")) or 0,
            "event_marking": bool(e.get("marking", True))}
