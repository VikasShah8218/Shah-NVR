"""Recording schedule evaluator (docs/RECORDING_SCHEDULES_PLAN.md §4.2, §9)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.schedules.utils import (camera_mode, camera_next_change, mode_at, next_change, parse_hhmm,
                                 site_zone)

ROOT = Path(__file__).resolve().parents[2]
OFFICE = [{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "18:00", "mode": "continuous"}]
NIGHTS = [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "18:00", "end": "08:00", "mode": "continuous"}]
KOLKATA = site_zone("Asia/Kolkata")


def at(day: int, hhmm: str, tz=None) -> datetime:
    """2026-11-16 is a Monday: day 0 = Mon ... 6 = Sun."""
    h, m = map(int, hhmm.split(":"))
    return datetime(2026, 11, 16 + day, h, m, tzinfo=tz)


def test_same_files_on_central_and_node():
    central = (ROOT / "central_manager/app/schedules/utils.py").read_bytes()
    node = (ROOT / "media_node/app/schedules/utils.py").read_bytes()
    assert central == node, "copy central_manager/app/schedules/utils.py to media_node/app/schedules/utils.py"


@pytest.mark.parametrize("value, minutes", [("00:00", 0), ("08:30", 510), ("23:59", 1439), ("24:00", 1440)])
def test_parse_hhmm(value, minutes):
    assert parse_hhmm(value) == minutes


@pytest.mark.parametrize("value", ["8:00", "24:01", "12:60", "ab:cd", "", "12-00", "123:00"])
def test_parse_hhmm_rejects(value):
    with pytest.raises(ValueError):
        parse_hhmm(value)


@pytest.mark.parametrize("day, hhmm, mode", [
    (0, "07:59", "off"), (0, "08:00", "continuous"), (2, "17:59", "continuous"), (2, "18:00", "off"),
    (5, "12:00", "off"),  # Saturday
])
def test_office_hours(day, hhmm, mode):
    assert mode_at(OFFICE, at(day, hhmm)) == mode


@pytest.mark.parametrize("day, hhmm, mode", [
    (0, "18:00", "continuous"), (1, "03:00", "continuous"), (1, "07:59", "continuous"), (1, "08:00", "off"),
    (0, "00:30", "continuous"),  # Monday early morning comes from the Sunday-night block (week wrap)
    (3, "12:00", "off"),
])
def test_overnight_and_week_wrap(day, hhmm, mode):
    assert mode_at(NIGHTS, at(day, hhmm)) == mode


def test_sunday_only_overnight_wraps_into_monday():
    sun_night = [{"days": [6], "start": "22:00", "end": "02:00"}]
    assert mode_at(sun_night, at(6, "23:00")) == "continuous"
    assert mode_at(sun_night, at(0, "01:59")) == "continuous"
    assert mode_at(sun_night, at(0, "02:00")) == "off"
    assert mode_at(sun_night, at(5, "23:00")) == "off"


def test_full_day_end_24_and_start_equals_end():
    for blocks in ([{"days": [2], "start": "00:00", "end": "24:00"}],
                   [{"days": [2], "start": "00:00", "end": "00:00"}]):
        assert mode_at(blocks, at(2, "00:00")) == "continuous"
        assert mode_at(blocks, at(2, "23:59")) == "continuous"
        assert mode_at(blocks, at(3, "00:00")) == "off"


def test_overlap_strongest_wins_and_empty_is_off():
    blocks = [{"days": [0], "start": "00:00", "end": "24:00", "mode": "event"},
              {"days": [0], "start": "09:00", "end": "10:00", "mode": "continuous"},
              {"days": [0], "start": "09:30", "end": "11:00", "mode": "off"}]
    assert mode_at(blocks, at(0, "08:00")) == "event"
    assert mode_at(blocks, at(0, "09:45")) == "continuous"
    assert mode_at(blocks, at(0, "10:30")) == "event"
    assert mode_at([], at(0, "10:00")) == mode_at(None, at(0, "10:00")) == "off"


def test_bad_blocks_are_ignored():
    blocks = [{"days": [0], "start": "8:00", "end": "18:00"}, {"days": [9], "start": "08:00", "end": "18:00"},
              {"start": "08:00"}, {"days": [0], "start": "08:00", "end": "18:00", "mode": "maybe"},
              {"days": [1], "start": "08:00", "end": "18:00"}]
    assert mode_at(blocks, at(0, "10:00")) == "off"
    assert mode_at(blocks, at(1, "10:00")) == "continuous"


def test_next_change():
    assert next_change(OFFICE, at(0, "07:30")) == at(0, "08:00")
    assert next_change(OFFICE, at(0, "08:00")) == at(0, "18:00")
    assert next_change(OFFICE, at(4, "18:00")) == at(7, "08:00")  # Friday evening -> next Monday
    assert next_change(NIGHTS, at(6, "20:00")) == at(7, "08:00")  # across the week end
    assert next_change([{"days": list(range(7)), "start": "00:00", "end": "24:00"}], at(0, "10:00")) is None
    assert next_change([], at(0, "10:00")) is None
    # adjacent blocks with the same mode are one span
    joined = [{"days": [0], "start": "08:00", "end": "12:00"}, {"days": [0], "start": "12:00", "end": "18:00"}]
    assert next_change(joined, at(0, "09:00")) == at(0, "18:00")


def test_next_change_keeps_the_zone():
    t = next_change(OFFICE, at(0, "07:30", KOLKATA))
    assert t == at(0, "08:00", KOLKATA) and t.tzinfo is KOLKATA


def test_camera_mode_uses_the_site_zone():
    rec = {"mode": "schedule", "blocks": OFFICE}
    # Monday 03:00 UTC = 08:30 in Kolkata (+05:30)
    now = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)
    assert camera_mode(rec, now, KOLKATA) == "continuous"
    assert camera_mode(rec, now, timezone.utc) == "off"
    assert camera_next_change(rec, now, KOLKATA) == at(0, "18:00", KOLKATA)
    assert camera_mode(None, now, KOLKATA) == camera_mode({"mode": "always"}, now, KOLKATA) == "continuous"
    assert camera_mode({"mode": "never"}, now, KOLKATA) == "off"
    assert camera_next_change({"mode": "always"}, now, KOLKATA) is None


def test_dst_zone_uses_wall_clock():
    berlin = site_zone("Europe/Berlin")
    rec = {"mode": "schedule", "blocks": [{"days": list(range(7)), "start": "08:00", "end": "18:00"}]}
    # 08:30 Berlin wall clock in winter (UTC+1) and in summer (UTC+2)
    assert camera_mode(rec, datetime(2026, 1, 12, 7, 30, tzinfo=timezone.utc), berlin) == "continuous"
    assert camera_mode(rec, datetime(2026, 7, 13, 6, 30, tzinfo=timezone.utc), berlin) == "continuous"
    assert camera_mode(rec, datetime(2026, 7, 13, 5, 30, tzinfo=timezone.utc), berlin) == "off"  # 07:30 local


def test_unknown_zone_is_utc():
    assert site_zone("Mars/Base") is timezone.utc and site_zone("") is timezone.utc
