"""Timeline maths. Port of nvr_client/src/features/playback/Timeline.tsx (mergeRanges, tickStep,
local-time tick alignment). All times are epoch milliseconds.
"""

from __future__ import annotations

import math
from datetime import datetime

from app.core.format import parse_iso

MIN = 60_000
HOUR = 60 * MIN
DAY = 24 * HOUR

ZOOMS = [("24h", DAY), ("6h", 6 * HOUR), ("1h", HOUR), ("10m", 10 * MIN)]


def to_ms(iso: str) -> float:
    return parse_iso(iso).timestamp() * 1000


def merge_ranges(segments: list[dict], tolerance_ms: float = 2000) -> list[tuple[float, float]]:
    """Touching/overlapping segments -> continuous recorded ranges."""
    ranges = sorted((to_ms(s["start_time"]), to_ms(s["end_time"])) for s in segments)
    merged: list[list[float]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + tolerance_ms:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def tick_step(span_ms: float) -> int:
    """Tick spacing that gives at most ~14 labels."""
    for step in (MIN, 2 * MIN, 5 * MIN, 10 * MIN, 15 * MIN, 30 * MIN, HOUR, 2 * HOUR, 3 * HOUR):
        if span_ms / step <= 14:
            return step
    return 4 * HOUR


def ticks(view_start: float, view_end: float) -> list[dict]:
    """Tick marks aligned to *local* clock time (e.g. 00:00, 02:00 in UTC+05:30, not UTC multiples)."""
    step = tick_step(view_end - view_start)
    offset_ms = datetime.fromtimestamp(view_start / 1000).astimezone().utcoffset().total_seconds() * 1000
    t = math.ceil((view_start + offset_ms) / step) * step - offset_ms
    out = []
    while t <= view_end:
        out.append({"t": t, "label": datetime.fromtimestamp(t / 1000).strftime("%H:%M")})
        t += step
    return out


def local_midnight(epoch_ms: float) -> float:
    d = datetime.fromtimestamp(epoch_ms / 1000)
    return datetime(d.year, d.month, d.day).timestamp() * 1000


def parse_clock(text: str) -> int | None:
    """'HH:MM' or 'HH:MM:SS' -> milliseconds after midnight, or None."""
    parts = text.strip().split(":")
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None
    h, m, s = (int(p) for p in (parts + ["0"])[:3])
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= s < 60):
        return None
    return ((h * 60 + m) * 60 + s) * 1000
