"""Page maths shared by every paged list. Port of nvr_client/src/lib/pager.ts (same tests, same results).

Pages are 1-based in the UI; the API takes `limit` + `offset` and answers `{items, total, limit, offset}`.
"""

from __future__ import annotations

import math
from typing import TypeVar

T = TypeVar("T")

PAGE_SIZES = (25, 50, 100)
DEFAULT_PAGE_SIZE = 50


def page_count(total: int, size: int) -> int:
    return max(1, math.ceil(max(0, total) / size))


def offset_for(page: int, size: int) -> int:
    return (max(1, int(page)) - 1) * size


def clamp_page(page: int, total: int, size: int) -> int:
    """Keep `page` inside 1..page_count (the list can shrink while we look at it)."""
    return min(max(1, int(page) or 1), page_count(total, size))


def range_label(page: int, size: int, total: int) -> str:
    """"101–150 of 987", or "0 of 0" for an empty list."""
    if total <= 0:
        return "0 of 0"
    first = offset_for(clamp_page(page, total, size), size) + 1
    return f"{first}–{min(total, first + size - 1)} of {total}"


def slice_page(rows: list[T], page: int, size: int) -> list[T]:
    """One page of a list that is already in memory (e.g. the chunks of a day)."""
    p = clamp_page(page, len(rows), size)
    return rows[offset_for(p, size):offset_for(p, size) + size]
