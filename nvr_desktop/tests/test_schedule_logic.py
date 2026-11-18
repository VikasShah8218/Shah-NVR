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
    assert s.day_runs(bits, 6) == [(1320, 1440, 2)] and s.day_runs(bits, 0) == [(0, 360, 2)]
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
    assert rows[0] == [{"start": 480, "end": 1080, "event": False}] and rows[5] == []


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
    assert s.now_text(False, "2026-11-17T08:00:00+05:30", now) == "Off now, until Tue 08:00"
    assert s.now_text("event", "2026-11-17T08:00:00+05:30", now) == "Event recording now, until Tue 08:00"
    assert s.now_text("continuous", "2026-11-17T08:00:00+05:30", now) == "Recording now, until Tue 08:00"
    assert s.now_text("event", None) == "Keeps video around events, all the time"
    assert s.state_of(True) == "continuous" and s.state_of(False) == "off" and s.state_of("bogus") == "off"
    assert s.now_text(True, None) == "Recording all the time" and s.now_text(False, None) == "Never records"


# ---------------------------------------------------------------- event recording (docs/EVENT_RECORDING_PLAN.md)


def test_event_blocks_and_record_wins_over_event():
    blocks = [b([0], "00:00", "24:00", "event"), b([0], "08:00", "18:00")]  # day record, the rest event
    bits = s.blocks_to_bitmap(blocks)
    assert s.recorded_hours(blocks) == 10 and s.event_hours(blocks) == 14
    assert s.day_runs(bits, 0) == [(0, 480, 1), (480, 1080, 2), (1080, 1440, 1)]
    assert s.bitmap_to_blocks(bits) == [b([0], "00:00", "08:00", "event"), b([0], "08:00", "18:00"),
                                        b([0], "18:00", "24:00", "event")]
    assert s.week_rows(blocks)[0][0] == {"start": 0, "end": 480, "event": True}
    assert s.uses_events(blocks) and not s.uses_events([b([0], "08:00", "18:00")])


def test_event_all_week_and_overnight_round_trip():
    every = [b(s.ALL_WEEK, "00:00", "24:00", "event")]
    assert s.bitmap_to_blocks(s.blocks_to_bitmap(every)) == every
    nights = [b(s.ALL_WEEK, "18:00", "08:00", "event")]
    assert s.bitmap_to_blocks(s.blocks_to_bitmap(nights)) == nights


def test_paint_with_three_brushes():
    office = s.paint([], 0, 4, 32, 71, "on")
    assert office == [b([0, 1, 2, 3, 4], "08:00", "18:00")]
    nights = s.paint(office, 0, 0, 72, 95, "event")  # Mon 18:00-24:00 -> event
    assert nights == [b([0, 1, 2, 3, 4], "08:00", "18:00"), b([0], "18:00", "24:00", "event")]
    assert s.paint(nights, 0, 0, 72, 95, "off") == office


def test_event_labels():
    assert s.block_label(b([5, 6], "00:00", "24:00", "event")) == "Sat, Sun all day · event"
    assert s.block_label(b([0], "18:00", "08:00", "event")) == "Mon 18:00–08:00 (next day) · event"
    assert s.block_label(b([0], "08:00", "18:00", "off")) == "Mon 08:00–18:00 · off"
