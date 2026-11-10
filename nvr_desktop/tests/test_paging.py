"""Port of nvr_client/tests/pager.test.ts: both clients page the same way."""

from app.core.paging import clamp_page, offset_for, page_count, range_label, slice_page


def test_page_count_is_at_least_one_and_rounds_up():
    assert [page_count(t, 50) for t in (0, 50, 51, 987)] == [1, 1, 2, 20]


def test_offset_from_a_one_based_page():
    assert [offset_for(p, 50) for p in (1, 3, 0)] == [0, 100, 0]


def test_page_is_clamped_when_the_list_shrinks():
    assert clamp_page(5, 120, 50) == 3 and clamp_page(0, 120, 50) == 1 and clamp_page(2, 0, 50) == 1


def test_range_label():
    assert range_label(3, 50, 987) == "101–150 of 987"
    assert range_label(20, 50, 987) == "951–987 of 987"
    assert range_label(1, 50, 0) == "0 of 0"


def test_in_memory_slice():
    rows = list(range(7))
    assert slice_page(rows, 2, 3) == [3, 4, 5] and slice_page(rows, 9, 3) == [6]
