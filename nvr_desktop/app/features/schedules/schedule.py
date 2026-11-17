"""Recording schedules: pure helpers. Port of nvr_client/src/lib/schedule.ts (docs/RECORDING_SCHEDULES_PLAN.md).

Same rules as central_manager/app/schedules/utils.py: Mon = 0, `end <= start` runs past midnight, start == end =
24 h, "24:00" = end of the day, a time no block covers is off. The grid editor works on a minute bitmap of the week.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DAY_MIN = 1440
WEEK_MIN = 7 * DAY_MIN
SLOT_MIN = 15  # grid snap
SLOTS = DAY_MIN // SLOT_MIN  # 96 per day
MAX_BLOCKS = 50
TIME_RE = re.compile(r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")
ALL_WEEK = [0, 1, 2, 3, 4, 5, 6]


def block(days, start: str, end: str, mode: str = "continuous") -> dict:
    return {"days": list(days), "start": start, "end": end, "mode": mode}


TEMPLATES = [
    {"key": "always", "label": "Always", "hint": "24 × 7", "blocks": [block(ALL_WEEK, "00:00", "24:00")]},
    {"key": "office", "label": "Office hours", "hint": "Mon–Fri 08:00–18:00", "blocks": [block([0, 1, 2, 3, 4], "08:00", "18:00")]},
    {"key": "nights", "label": "Nights", "hint": "Every day 18:00–08:00", "blocks": [block(ALL_WEEK, "18:00", "08:00")]},
    {"key": "weekends", "label": "Weekends", "hint": "Sat–Sun all day", "blocks": [block([5, 6], "00:00", "24:00")]},
]


def parse_hhmm(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def fmt_hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def block_error(b: dict) -> str | None:
    if not b.get("days"):
        return "pick at least one day"
    if not TIME_RE.match(b.get("start", "")) or not TIME_RE.match(b.get("end", "")):
        return "use HH:MM (00:00–24:00)"
    if b["start"] == "24:00":
        return "start cannot be 24:00"
    return None


def blocks_to_bitmap(blocks: list[dict]) -> bytearray:
    """One byte per minute of the week: 1 = recording. "off" blocks never win over "continuous", so they add nothing."""
    bits = bytearray(WEEK_MIN)
    for b in blocks:
        if b.get("mode", "continuous") != "continuous" or block_error(b):
            continue
        s, e = parse_hhmm(b["start"]), parse_hhmm(b["end"])
        length = e - s if e > s else DAY_MIN - s + e  # e == s -> 24 h
        for d in b["days"]:
            base = d * DAY_MIN + s
            end = base + length
            if end <= WEEK_MIN:
                bits[base:end] = b"\x01" * length
            else:  # Sunday night into Monday
                bits[base:] = b"\x01" * (WEEK_MIN - base)
                bits[: end - WEEK_MIN] = b"\x01" * (end - WEEK_MIN)
    return bits


def bitmap_to_blocks(bits: bytearray) -> list[dict]:
    """Minute bitmap -> the fewest readable blocks: runs split at midnight, except one overnight block
    (e.g. 18:00-08:00) when the run ends the next morning; equal times on several days share one block."""
    try:
        off = bits.index(0)
    except ValueError:
        return [block(ALL_WEEK, "00:00", "24:00")]
    chunks: list[tuple[int, int, int]] = []
    i = 0
    while i < WEEK_MIN:  # walk the circular week from an "off" minute, so no run is cut at the array end
        at = (off + i) % WEEK_MIN
        if not bits[at]:
            i += 1
            continue
        length = 0
        while length < WEEK_MIN and bits[(at + length) % WEEK_MIN]:
            length += 1
        i += length
        s, left = at, length
        while left > 0:
            day, t = divmod(s, DAY_MIN)
            to_midnight = DAY_MIN - t
            if left <= to_midnight:
                take = left
            elif t > 0 and left - to_midnight < t:
                take = left  # overnight block, ends before its start time
            else:
                take = to_midnight
            end = DAY_MIN if take == to_midnight else (t + take) % DAY_MIN
            chunks.append((day, t, end))
            s = (s + take) % WEEK_MIN
            left -= take
    by_times: dict[tuple[int, int], list[int]] = {}
    for day, s, e in chunks:
        by_times.setdefault((s, e), []).append(day)
    out = [block(sorted(set(days)), fmt_hhmm(s), fmt_hhmm(e)) for (s, e), days in by_times.items()]
    return sorted(out, key=lambda b: (b["days"][0], b["start"]))


def paint(blocks: list[dict], d0: int, d1: int, q0: int, q1: int, on: bool) -> list[dict]:
    """The grid's drag: set days d0..d1 x 15-min slots q0..q1 (inclusive) to record (on) or off."""
    bits = blocks_to_bitmap(blocks)
    d0, d1 = sorted((max(0, min(6, d0)), max(0, min(6, d1))))
    q0, q1 = sorted((max(0, min(SLOTS - 1, q0)), max(0, min(SLOTS - 1, q1))))
    value = b"\x01" if on else b"\x00"
    for d in range(d0, d1 + 1):
        a, b = d * DAY_MIN + q0 * SLOT_MIN, d * DAY_MIN + (q1 + 1) * SLOT_MIN
        bits[a:b] = value * (b - a)
    return bitmap_to_blocks(bits)


def day_runs(bits: bytearray, day: int) -> list[tuple[int, int]]:
    """Recording runs of one day as (start_min, end_min) for drawing."""
    runs, start = [], -1
    base = day * DAY_MIN
    for m in range(DAY_MIN + 1):
        on = m < DAY_MIN and bits[base + m] == 1
        if on and start < 0:
            start = m
        if not on and start >= 0:
            runs.append((start, m))
            start = -1
    return runs


def week_rows(blocks: list[dict]) -> list[list[dict]]:
    """Per day, the recording runs as [{"start": min, "end": min}] (what WeekGrid / WeekStrip draw)."""
    bits = blocks_to_bitmap(blocks)
    return [[{"start": s, "end": e} for s, e in day_runs(bits, d)] for d in range(7)]


def recorded_hours(blocks: list[dict]) -> float:
    return sum(blocks_to_bitmap(blocks)) / 60


def days_label(days: list[int]) -> str:
    d = sorted(days)
    if len(d) == 7:
        return "Every day"
    consecutive = len(d) > 2 and all(x == d[0] + i for i, x in enumerate(d))
    return f"{DAYS[d[0]]}–{DAYS[d[-1]]}" if consecutive else ", ".join(DAYS[x] for x in d)


def block_label(b: dict) -> str:
    all_day = b["start"] == "00:00" and b["end"] in ("24:00", "00:00")
    if all_day:
        return f"{days_label(b['days'])} all day"
    next_day = " (next day)" if parse_hhmm(b["end"]) <= parse_hhmm(b["start"]) else ""
    return f"{days_label(b['days'])} {b['start']}–{b['end']}{next_day}"


def blocks_summary(blocks: list[dict]) -> str:
    if not blocks:
        return "No blocks (never records)"
    more = f" +{len(blocks) - 2}" if len(blocks) > 2 else ""
    return "; ".join(block_label(b) for b in blocks[:2]) + more


def site_wall(iso: str) -> tuple[int, int, str]:
    """Wall clock of an ISO time that carries the site offset ("2026-11-16T18:00:00+05:30"), not the PC's zone:
    (weekday Mon=0, minute of day, "YYYY-MM-DD")."""
    day_part, rest = iso.split("T")
    weekday = date.fromisoformat(day_part).weekday()
    return weekday, parse_hhmm(rest[:5]), day_part


def fmt_change(iso: str, now: datetime | None = None) -> str:
    """'Mon 18:00', or 'Mon 23 Nov 18:00' when 6 days or more away (same as the node's log line)."""
    weekday, minute, day_part = site_wall(iso)
    now = now or datetime.now(timezone.utc)
    when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    far = (when - now).total_seconds() >= 6 * 86400
    _, mo, d = (int(x) for x in day_part.split("-"))
    return f"{DAYS[weekday]}{f' {d} {MONTHS[mo - 1]}' if far else ''} {fmt_hhmm(minute)}"


def now_text(recording_now: bool, next_change: str | None, now: datetime | None = None) -> str:
    """'Recording now, until Mon 18:00' / 'Off now, recording from Tue 08:00' / 'Recording all the time'."""
    if not next_change:
        return "Recording all the time" if recording_now else "Never records"
    when = fmt_change(next_change, now)
    return f"Recording now, until {when}" if recording_now else f"Off now, recording from {when}"


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]
