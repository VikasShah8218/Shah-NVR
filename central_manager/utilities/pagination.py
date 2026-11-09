"""One shape for every paged list: `{items, total, limit, offset}` (docs/PAGINATION_PLAN.md).

Offset paging is enough for our sizes (≤10k cameras) and gives the UI "page 3 of 20". Every caller must order the
queryset on a unique key (e.g. `name, id`), otherwise rows can repeat or vanish between pages.
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from tortoise.queryset import QuerySet

T = TypeVar("T")

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams:
    """FastAPI dependency: `?limit=50&offset=0`."""

    def __init__(
        self,
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Rows per page"),
        offset: int = Query(0, ge=0, description="Rows to skip"),
    ):
        self.limit = limit
        self.offset = offset


async def paginate(
    qs: QuerySet,
    params: PageParams,
    to_out: Callable[[Sequence[Any]], Awaitable[list[T]]] | Callable[[Sequence[Any]], list[T]],
) -> Page[T]:
    """Count the filtered queryset, fetch one page and convert it in one go (`to_out` gets the whole page,
    so it can batch its own lookups instead of querying per row)."""
    total = await qs.count()
    rows = await qs.offset(params.offset).limit(params.limit)
    items = to_out(rows)
    if hasattr(items, "__await__"):
        items = await items
    return Page(items=items, total=total, limit=params.limit, offset=params.offset)


def page_of(items: list[T], params: PageParams) -> Page[T]:
    """Page a list that is already in memory (computed rows, e.g. alerts)."""
    return Page(items=items[params.offset:params.offset + params.limit], total=len(items),
                limit=params.limit, offset=params.offset)
