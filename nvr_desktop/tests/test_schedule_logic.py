"""Schedule helpers (port of nvr_client/src/lib/schedule.ts): same cases as nvr_client/tests/schedule.test.ts."""

from datetime import datetime, timezone

from app.features.schedules import schedule as s

b = s.block


def test_templates_round_trip():
    for t in s.TEMPLATES:
        assert s.bitmap_to_blocks(s.blocks_to_bitmap(t["blocks"])) == t["blocks"], t["key"]


def test_overnight_wraps_sunday_into_monday():
    blocks = [b([6], "22:00", "06:00")]
    bits = s.blocks_to_bitmap(blocks)
    assert s.recorded_hours(blocks) == 8
    assert s.day_runs(bits, 6) == [(1320, 1440)] and s.day_runs(bits, 0) == [(0, 360)]
    assert s.bitmap_to_blocks(bits) == blocks


def test_24h_and_long_runs_split_at_midnight():
    assert s.recorded_hours([b([2], "08:00", "08:00")]) == 24
    weekend = [b([4], "18:00", "24:00"), b([5, 6], "00:00", "24:00"), b([0], "00:00", "08:00")]
    assert s.bitmap_to_blocks(s.blocks_to_bitmap(weekend)) == [b([0], "00:00", "08:00"), b([4], "18:00", "24:00"),
                                                                b([5, 6], "00:00", "24:00")]


def test_off_blocks_add_nothing_and_exact_minutes_survive_painting():
    blocks = [b([0], "18:03", "18:05"), b([1], "00:00", "24:00", "off")]
    assert s.recorded_hours(blocks) * 60 == 2
    painted = s.paint(blocks, 5, 6, 40, 55, True)  # Sat-Sun 10:00-14:00
    assert painted == [b([0], "18:03", "18:05"), b([5, 6], "10:00", "14:00")]
    assert s.paint(painted, 6, 5, 55, 40, False) == [b([0], "18:03", "18:05")]  # reversed drag, paint off


def test_paint_office_hours_from_empty():
    assert s.paint([], 0, 4, 32, 71, True) == [b([0, 1, 2, 3, 4], "08:00", "18:00")]
    rows = s.week_rows([b([0, 1, 2, 3, 4], "08:00", "18:00")])
    assert rows[0] == [{"start": 480, "end": 1080}] and rows[5] == []


def test_block_errors():
    assert s.block_error(b([], "08:00", "18:00")) == "pick at least one day"
    assert s.block_error(b([1], "8:00", "18:00")) == "use HH:MM (00:00–24:00)"
    assert s.block_error(b([1], "24:00", "18:00")) == "start cannot be 24:00"
    assert s.block_error(b([1], "08:00", "24:00")) is None
    assert s.blocks_to_bitmap([b([1], "bad", "18:00")]) == bytearray(s.WEEK_MIN)


def test_labels():
    assert s.block_label(b([0, 1, 2, 3, 4], "08:00", "18:00")) == "Mon–Fri 08:00–18:00"
    assert s.block_label(b([5, 6], "00:00", "24:00")) == "Sat, Sun all day"
    assert s.block_label(b([0, 2], "18:00", "08:00")) == "Mon, Wed 18:00–08:00 (next day)"
    assert s.blocks_summary([]) == "No blocks (never records)"
    assert s.blocks_summary([b([0], "01:00", "02:00")] * 3).endswith(" +1")


def test_site_wall_and_change_text():
    assert s.site_wall("2026-11-16T18:30:00+05:30") == (0, 1110, "2026-11-16")
    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    assert s.fmt_change("2026-11-17T08:00:00+05:30", now) == "Tue 08:00"
    assert s.fmt_change("2026-11-23T08:00:00+05:30", now) == "Mon 23 Nov 08:00"
    assert s.now_text(True, "2026-11-17T08:00:00+05:30", now) == "Recording now, until Tue 08:00"
    assert s.now_text(False, "2026-11-17T08:00:00+05:30", now) == "Off now, recording from Tue 08:00"
    assert s.now_text(True, None) == "Recording all the time" and s.now_text(False, None) == "Never records"
