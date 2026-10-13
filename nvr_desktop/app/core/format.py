"""Human-readable formatting. Port of nvr_client/src/lib/format.ts + lib/time.ts.

Pure functions (unit-tested) plus `Formatter`, the QML singleton `Fmt` that exposes them.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Slot

_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


def format_bytes(value: float | None, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    if value == 0:
        return "0 B"
    i = min(len(_UNITS) - 1, int(math.floor(math.log(abs(value), 1024))))
    return f"{value / 1024 ** i:.{0 if i == 0 else digits}f} {_UNITS[i]}"


def format_mbps(mbps: float | None) -> str:
    if mbps is None:
        return "—"
    if mbps >= 1000:
        return f"{mbps / 1000:.2f} Gb/s"
    return f"{mbps:.{2 if mbps < 10 else 1}f} Mb/s"


def format_percent(value: float | None, digits: int = 0) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


def format_duration(ms: float | None) -> str:
    if ms is None:
        return "—"
    total = round(ms / 1000)
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def ratio(used: float | None, total: float | None) -> float | None:
    if used is None or not total:
        return None
    return max(0.0, min(100.0, used / total * 100))


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def time_ago(iso: str | None, now: datetime | None = None) -> str:
    """'5 seconds ago', '3 minutes ago'... (date-fns formatDistanceToNowStrict style)."""
    when = parse_iso(iso)
    if when is None:
        return "never"
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - when).total_seconds()))
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)):
        if seconds >= size or unit == "second":
            n = seconds // size
            return f"{n} {unit}{'' if n == 1 else 's'} ago"
    return "just now"


def _local(value: str | float | None) -> datetime | None:
    """ISO string or epoch milliseconds -> local datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000)
    parsed = parse_iso(value)
    return parsed.astimezone() if parsed else None


def fmt_time(value) -> str:
    d = _local(value)
    return d.strftime("%H:%M:%S") if d else "—"


def fmt_date_time(value) -> str:
    d = _local(value)
    return d.strftime("%d %b %Y, %H:%M:%S") if d else "—"


def fmt_day(value) -> str:
    d = _local(value)
    return d.strftime("%d %b %Y") if d else "—"


class Formatter(QObject):
    """QML singleton `Fmt`: Fmt.bytes(x), Fmt.timeAgo(iso)..."""

    @Slot("QVariant", result=str)
    def bytes(self, value) -> str:
        return format_bytes(None if value is None else float(value))

    @Slot("QVariant", result=str)
    def mbps(self, value) -> str:
        return format_mbps(None if value is None else float(value))

    @Slot("QVariant", result=str)
    def percent(self, value) -> str:
        return format_percent(None if value is None else float(value))

    @Slot("QVariant", result=str)
    def duration(self, ms) -> str:
        return format_duration(None if ms is None else float(ms))

    @Slot("QVariant", result=str)
    def timeAgo(self, iso) -> str:
        return time_ago(iso or None)

    @Slot("QVariant", result=str)
    def time(self, value) -> str:
        return fmt_time(value)

    @Slot("QVariant", result=str)
    def dateTime(self, value) -> str:
        return fmt_date_time(value)

    @Slot("QVariant", result=str)
    def day(self, value) -> str:
        return fmt_day(value)

    @Slot("QVariant", "QVariant", result="QVariant")
    def ratio(self, used, total):
        return ratio(None if used is None else float(used), None if total is None else float(total))
