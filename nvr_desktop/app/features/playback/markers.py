"""Timeline markers (port of nvr_client/src/features/playback/markers.ts).

Bookmarks today; motion / ONVIF events later use the same layer. A marker is a point (`t`) or a range
(`t` .. `end_t`). Positions are fractions 0..1 of the visible window so QML just multiplies by its width.
"""

from __future__ import annotations

import re

from app.features.playback.timeline import to_ms

MIN_RANGE_WIDTH = 0.004  # a range never shrinks below 0.4 % of the bar, so it stays visible and clickable


def place_markers(markers: list[dict], view_start: float, view_end: float) -> list[dict]:
    """Markers that touch the window, with `x` (0..1) and `width` (0..1, or None for a point)."""
    span = view_end - view_start
    if span <= 0:
        return []
    out = []
    for m in markers:
        t, end_t = m["t"], m.get("end_t")
        if end_t is not None and end_t > t:
            if end_t <= view_start or t >= view_end:
                continue
            x = max(0.0, (t - view_start) / span)
            right = min(1.0, (end_t - view_start) / span)
            out.append({**m, "x": x, "width": max(MIN_RANGE_WIDTH, right - x)})
        elif view_start <= t <= view_end:
            out.append({**m, "x": (t - view_start) / span, "width": None})
    return out


def bookmark_marker(b: dict) -> dict:
    label = f"{b['label']}: {b['note']}" if b.get("label") else b["note"]
    return {
        "id": f"bookmark-{b['id']}",
        "t": to_ms(b["start_time"]),
        "end_t": to_ms(b["end_time"]) if b.get("end_time") else None,
        "kind": "bookmark",
        "label": label,
        "color": b.get("color") or "",
    }


# Colours of event types (same as nvr_client markers.ts); unknown types are grey.
# same values as nvr_client/src/features/playback/markers.ts; camera events (ONVIF): motion, tamper, input, other
EVENT_COLORS = {"manual": "#3b82f6", "api": "#8b5cf6", "video_loss": "#ef4444", "motion": "#f59e0b",
                "tamper": "#f97316", "digital_input": "#14b8a6", "onvif": "#94a3b8",
                # camera analytics (docs/ONVIF_ANALYTICS_EVENTS_PLAN.md §1)
                "line_crossing": "#d946ef", "intrusion": "#e11d48", "loitering": "#0ea5e9", "object_left": "#84cc16",
                "person": "#22c55e", "face": "#ec4899", "counting": "#64748b", "audio_alarm": "#eab308"}
EVENT_LABELS = {"manual": "Marked", "api": "External", "video_loss": "Video loss", "motion": "Motion",
                "tamper": "Tamper", "digital_input": "Input", "onvif": "Camera event",
                "line_crossing": "Line crossing", "intrusion": "Intrusion", "loitering": "Loitering",
                "object_left": "Object left", "person": "Person", "face": "Face", "counting": "People counting",
                "audio_alarm": "Audio alarm"}
# Groups of the Events type filter (central `group=`), same as the web
EVENT_TYPE_GROUPS = (
    ("camera", "Camera", ("motion", "tamper", "digital_input", "video_loss", "onvif")),
    ("analytics", "Analytics", ("line_crossing", "intrusion", "loitering", "object_left", "person", "face", "counting",
                                "audio_alarm")),
    ("operator", "Operator", ("manual", "api")),
)
UNKNOWN_COLOR = "#94a3b8"


def event_color(type_: str) -> str:
    return EVENT_COLORS.get(type_, UNKNOWN_COLOR)


def event_type_label(type_: str) -> str:
    if type_ in EVENT_LABELS:
        return EVENT_LABELS[type_]
    text = re.sub(r"[_.:-]+", " ", type_)
    return text[:1].upper() + text[1:]


def event_text(e: dict) -> str:
    """'Line crossing · Gate line ×3' (analytics labels already start with their type title), 'Marked: Gate open'."""
    title = event_type_label(e["type"])
    label = e.get("label")
    if not label:
        return title
    return label if label.startswith(title) else f"{title}: {label}"


def event_marker(e: dict, now_ms: float) -> dict:
    """Event (from the API) -> timeline marker: a moment is a pin, a range a band, an open event runs to now.
    A click plays from `seek_t` (the camera's pre-event seconds before the start)."""
    t = to_ms(e["start_time"])
    end = to_ms(e["end_time"]) if e.get("end_time") else now_ms
    label = event_text(e) + ("" if e.get("end_time") else " (ongoing)")
    return {
        "id": f"event-{e['id']}",
        "t": t,
        "end_t": end if end > t else None,
        "kind": "event",
        "label": label,
        "color": event_color(e["type"]),
        "seek_t": t - int(e.get("pre_seconds") or 0) * 1000,
    }
