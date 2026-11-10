"""Timeline markers (port of nvr_client/src/features/playback/markers.ts).

Bookmarks today; motion / ONVIF events later use the same layer. A marker is a point (`t`) or a range
(`t` .. `end_t`). Positions are fractions 0..1 of the visible window so QML just multiplies by its width.
"""

from __future__ import annotations

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
