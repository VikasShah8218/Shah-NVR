from datetime import datetime, timedelta, timezone

from app.core.format import format_bytes, format_duration, format_mbps, format_percent, parse_iso, ratio, time_ago


def test_format_bytes():
    assert format_bytes(None) == "—"
    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(5 * 1024**3) == "5.0 GB"


def test_format_mbps():
    assert format_mbps(None) == "—"
    assert format_mbps(2.345) == "2.35 Mb/s"
    assert format_mbps(42.0) == "42.0 Mb/s"
    assert format_mbps(1500) == "1.50 Gb/s"


def test_format_percent_and_ratio():
    assert format_percent(None) == "—"
    assert format_percent(42.4) == "42%"
    assert ratio(None, 10) is None
    assert ratio(5, 0) is None
    assert ratio(5, 10) == 50
    assert ratio(20, 10) == 100  # clamped


def test_format_duration():
    assert format_duration(None) == "—"
    assert format_duration(45_000) == "45s"
    assert format_duration(125_000) == "2m 5s"
    assert format_duration(3_720_000) == "1h 2m"


def test_time_ago():
    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    assert time_ago(None, now) == "never"
    assert time_ago((now - timedelta(seconds=1)).isoformat(), now) == "1 second ago"
    assert time_ago((now - timedelta(minutes=3)).isoformat(), now) == "3 minutes ago"
    assert time_ago((now - timedelta(days=2)).isoformat(), now) == "2 days ago"


def test_parse_iso_accepts_z_suffix():
    assert parse_iso("2026-10-14T00:00:00Z") == datetime(2026, 10, 14, tzinfo=timezone.utc)
    assert parse_iso(None) is None
