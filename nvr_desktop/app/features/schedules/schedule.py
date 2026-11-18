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


# Minute values in the bitmap, weakest -> strongest (the server's MODES order): overlapping blocks keep the strongest.
MODE_VALUE = {"off": 0, "event": 1, "continuous": 2}
VALUE_MODE = ("off", "event", "continuous")
BRUSHES = {"on": 2, "record": 2, "continuous": 2, "event": 1, "off": 0}


def blocks_to_bitmap(blocks: list[dict]) -> bytearray:
    """One value per minute of the week: 0 off, 1 event (video kept around events), 2 record."""
    bits = bytearray(WEEK_MIN)
    for b in blocks:
        v = MODE_VALUE.get(b.get("mode") or "continuous", 0)
        if not v or block_error(b):
            continue
        s, e = parse_hhmm(b["start"]), parse_hhmm(b["end"])
        length = e - s if e > s else DAY_MIN - s + e  # e == s -> 24 h
        for d in b["days"]:
            base = d * DAY_MIN + s
            for i in range(length):
                at = (base + i) % WEEK_MIN  # Sunday night runs into Monday
                if bits[at] < v:
                    bits[at] = v
    return bits


def bitmap_to_blocks(bits: bytearray) -> list[dict]:
    """Minute bitmap -> the fewest readable blocks: runs of one mode split at midnight, except one overnight block
    (e.g. 18:00-08:00) when the run ends the next morning; equal times and mode on several days share one block."""
    # walk the circular week from a mode change (an "off" minute if any), so no run is cut at the array end
    try:
        origin = bits.index(0)
    except ValueError:
        origin = next((i for i in range(WEEK_MIN) if bits[i] != bits[i - 1]), -1)
        if origin < 0:
            return [block(ALL_WEEK, "00:00", "24:00", VALUE_MODE[bits[0]])]
    chunks: list[tuple[int, int, int, int]] = []
    i = 0
    while i < WEEK_MIN:
        at = (origin + i) % WEEK_MIN
        v = bits[at]
        if not v:
            i += 1
            continue
        length = 0
        while length < WEEK_MIN - i and bits[(at + length) % WEEK_MIN] == v:
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
            chunks.append((day, t, end, v))
            s = (s + take) % WEEK_MIN
            left -= take
    by_times: dict[tuple[int, int, int], list[int]] = {}
    for day, s, e, v in chunks:
        by_times.setdefault((s, e, v), []).append(day)
    out = [block(sorted(set(days)), fmt_hhmm(s), fmt_hhmm(e), VALUE_MODE[v]) for (s, e, v), days in by_times.items()]
    return sorted(out, key=lambda b: (b["days"][0], b["start"]))


def paint(blocks: list[dict], d0: int, d1: int, q0: int, q1: int, brush="on") -> list[dict]:
    """The grid's drag: set days d0..d1 x 15-min slots q0..q1 (inclusive) to the brush: "on" / "record" (2),
    "event" (1) or "off" (0); a bool means record / off."""
    value = (2 if brush else 0) if isinstance(brush, bool) else BRUSHES.get(brush, 0)
    bits = blocks_to_bitmap(blocks)
    d0, d1 = sorted((max(0, min(6, d0)), max(0, min(6, d1))))
    q0, q1 = sorted((max(0, min(SLOTS - 1, q0)), max(0, min(SLOTS - 1, q1))))
    for d in range(d0, d1 + 1):
        a, b = d * DAY_MIN + q0 * SLOT_MIN, d * DAY_MIN + (q1 + 1) * SLOT_MIN
        bits[a:b] = bytes([value]) * (b - a)
    return bitmap_to_blocks(bits)


def day_runs(bits: bytearray, day: int) -> list[tuple[int, int, int]]:
    """Runs of one day as (start_min, end_min, value) for drawing (value 2 record, 1 event)."""
    runs, start, cur = [], -1, 0
    base = day * DAY_MIN
    for m in range(DAY_MIN + 1):
        v = bits[base + m] if m < DAY_MIN else 0
        if v != cur:
            if cur:
                runs.append((start, m, cur))
            start, cur = m, v
    return runs


def week_rows(blocks: list[dict]) -> list[list[dict]]:
    """Per day, the runs as [{"start": min, "end": min, "event": bool}] (what WeekGrid / WeekStrip draw)."""
    bits = blocks_to_bitmap(blocks)
    return [[{"start": s, "end": e, "event": v == 1} for s, e, v in day_runs(bits, d)] for d in range(7)]


def _hours(blocks: list[dict], value: int) -> float:
    return blocks_to_bitmap(blocks).count(value) / 60


def recorded_hours(blocks: list[dict]) -> float:
    return _hours(blocks, 2)


def event_hours(blocks: list[dict]) -> float:
    return _hours(blocks, 1)


def uses_events(blocks: list[dict]) -> bool:
    return any(b.get("mode") == "event" for b in blocks)


def days_label(days: list[int]) -> str:
    d = sorted(days)
    if len(d) == 7:
        return "Every day"
    consecutive = len(d) > 2 and all(x == d[0] + i for i, x in enumerate(d))
    return f"{DAYS[d[0]]}–{DAYS[d[-1]]}" if consecutive else ", ".join(DAYS[x] for x in d)


def block_label(b: dict) -> str:
    mode = {"event": " · event", "off": " · off"}.get(b.get("mode") or "continuous", "")
    all_day = b["start"] == "00:00" and b["end"] in ("24:00", "00:00")
    if all_day:
        return f"{days_label(b['days'])} all day{mode}"
    next_day = " (next day)" if parse_hhmm(b["end"]) <= parse_hhmm(b["start"]) else ""
    return f"{days_label(b['days'])} {b['start']}–{b['end']}{next_day}{mode}"


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


def state_of(value) -> str:
    """The recording state now: "continuous" / "event" / "off" (a bool from an older central = continuous / off)."""
    if isinstance(value, bool):
        return "continuous" if value else "off"
    return value if value in VALUE_MODE else "off"


def now_text(state, next_change: str | None, now: datetime | None = None) -> str:
    """'Recording now, until Mon 18:00' / 'Event recording now, until Tue 08:00' / 'Off now, until Tue 08:00' /
    'Recording all the time'. `state` is the mode now (True / False = continuous / off, for older callers)."""
    mode = state_of(state)
    if not next_change:
        return {"continuous": "Recording all the time", "event": "Keeps video around events, all the time"}.get(
            mode, "Never records")
    when = fmt_change(next_change, now)
    return {"continuous": f"Recording now, until {when}", "event": f"Event recording now, until {when}"}.get(
        mode, f"Off now, until {when}")


def lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]
