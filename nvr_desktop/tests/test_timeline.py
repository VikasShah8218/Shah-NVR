import time

from app.features.playback.timeline import DAY, HOUR, MIN, local_midnight, merge_ranges, parse_clock, tick_step, ticks


def seg(start, end):
    return {"start_time": start, "end_time": end}


def test_merge_ranges_joins_touching_and_close_segments():
    ranges = merge_ranges([
        seg("2026-10-14T00:01:00Z", "2026-10-14T00:02:00Z"),
        seg("2026-10-14T00:00:00Z", "2026-10-14T00:01:00Z"),     # out of order, touching
        seg("2026-10-14T00:02:01Z", "2026-10-14T00:03:00Z"),     # 1 s gap: within tolerance
        seg("2026-10-14T00:10:00Z", "2026-10-14T00:11:00Z"),     # real gap
    ])
    assert len(ranges) == 2
    assert ranges[0][1] - ranges[0][0] == 3 * MIN
    assert ranges[1][1] - ranges[1][0] == MIN


def test_tick_step():
    assert tick_step(DAY) == 2 * HOUR
    assert tick_step(HOUR) == 5 * MIN
    assert tick_step(10 * MIN) == MIN


def test_ticks_align_to_local_midnight():
    day = local_midnight(time.time() * 1000)
    marks = ticks(day, day + DAY)
    assert marks[0] == {"t": day, "label": "00:00"}
    assert [m["label"] for m in marks[:3]] == ["00:00", "02:00", "04:00"]
    assert len(marks) == 13


def test_parse_clock():
    assert parse_clock("08:30") == (8 * 60 + 30) * 60_000
    assert parse_clock(" 23:59:59 ") == ((23 * 60 + 59) * 60 + 59) * 1000
    for bad in ("24:00", "8", "aa:bb", "12:60", "1:2:3:4"):
        assert parse_clock(bad) is None
