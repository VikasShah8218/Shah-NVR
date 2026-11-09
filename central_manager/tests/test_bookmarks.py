import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from tortoise import Tortoise

from app.bookmarks.models import Bookmark
from app.bookmarks.router import create_bookmark, delete_bookmark, get_bookmark, list_bookmarks, update_bookmark
from app.bookmarks.schemas import BookmarkCreate, BookmarkUpdate
from app.cameras.models import Camera
from database.config import APP_MODELS

T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def run(fn):
    async def wrapper():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            await fn()
        finally:
            await Tortoise.close_connections()

    asyncio.run(wrapper())


async def search(**kw):
    """list_bookmarks with its Query() defaults filled in (called directly, not through HTTP)."""
    args = {"camera_id": None, "profile": None, "q": None, "start": None, "end": None, "order": "asc", "limit": 200,
            "offset": 0}
    args.update(kw)
    return (await list_bookmarks(**args)).items


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_create_get_update_delete():
    async def go():
        cam = await Camera.create(name="Gate")
        b = await create_bookmark(BookmarkCreate(camera_id=cam.id, start_time=at(0), note="  Truck at gate  "))
        assert b.note == "Truck at gate" and b.camera_name == "Gate" and b.end_time is None

        got = await get_bookmark(b.id)
        assert got.id == b.id

        upd = await update_bookmark(b.id, BookmarkUpdate(end_time=at(2), label="vehicle", color="#ff8800"))
        assert upd.end_time == at(2) and upd.label == "vehicle" and upd.note == "Truck at gate"

        # end_time=null turns the range back into a point
        point = await update_bookmark(b.id, BookmarkUpdate.model_validate({"end_time": None}))
        assert point.end_time is None

        await delete_bookmark(b.id)
        with pytest.raises(HTTPException) as exc:
            await get_bookmark(b.id)
        assert exc.value.status_code == 404
    run(go)


def test_unknown_camera_is_404():
    async def go():
        with pytest.raises(HTTPException) as exc:
            await create_bookmark(BookmarkCreate(camera_id=999, start_time=at(0), note="x"))
        assert exc.value.status_code == 404
    run(go)


def test_validation():
    with pytest.raises(ValidationError):
        BookmarkCreate(camera_id=1, start_time=at(5), end_time=at(5), note="x")  # end must be after start
    with pytest.raises(ValidationError):
        BookmarkCreate(camera_id=1, start_time=at(0), note="   ")  # blank note
    with pytest.raises(ValidationError):
        BookmarkCreate(camera_id=1, start_time=at(0), note="x", color="red")  # not #rrggbb
    # naive datetimes are treated as UTC
    naive = BookmarkCreate(camera_id=1, start_time=datetime(2026, 11, 9, 12, 0), note="x")
    assert naive.start_time == T0


def test_update_rejects_end_before_start_and_removing_required_fields():
    async def go():
        cam = await Camera.create(name="Gate")
        b = await create_bookmark(BookmarkCreate(camera_id=cam.id, start_time=at(10), note="x"))
        with pytest.raises(HTTPException) as exc:
            await update_bookmark(b.id, BookmarkUpdate(end_time=at(5)))
        assert exc.value.status_code == 422
        with pytest.raises(HTTPException):
            await update_bookmark(b.id, BookmarkUpdate.model_validate({"note": None}))
        with pytest.raises(HTTPException):
            await update_bookmark(b.id, BookmarkUpdate.model_validate({"start_time": None}))
    run(go)


def test_time_window_overlap():
    async def go():
        cam = await Camera.create(name="Gate")
        mk = lambda s, e=None, n="x": create_bookmark(  # noqa: E731
            BookmarkCreate(camera_id=cam.id, start_time=at(s), end_time=at(e) if e is not None else None, note=n))
        await mk(-30, n="point before")
        await mk(-10, 5, n="range overlapping start")
        await mk(10, n="point inside")
        await mk(50, 70, n="range overlapping end")
        await mk(90, n="point after")
        notes = [b.note for b in await search(camera_id=cam.id, start=at(0), end=at(60))]
        assert notes == ["range overlapping start", "point inside", "range overlapping end"]

        with pytest.raises(HTTPException):
            await search(start=at(10), end=at(5))
    run(go)


def test_text_search_profile_and_camera_filters():
    async def go():
        gate, yard = await Camera.create(name="Gate"), await Camera.create(name="Yard")
        await create_bookmark(BookmarkCreate(camera_id=gate.id, start_time=at(0), note="Red TRUCK arrives"))
        await create_bookmark(BookmarkCreate(camera_id=gate.id, start_time=at(1), note="person", label="truck driver",
                                             profile="sub"))
        await create_bookmark(BookmarkCreate(camera_id=gate.id, start_time=at(2), note="person", profile="main"))
        await create_bookmark(BookmarkCreate(camera_id=yard.id, start_time=at(3), note="truck leaves"))

        assert len(await search(q="truck")) == 3  # case-insensitive, note and label
        assert len(await search(q="truck", camera_id=gate.id)) == 2
        # profile=main: main-only plus camera-wide (no profile); sub-only excluded
        main = [b.note for b in await search(camera_id=gate.id, profile="main")]
        assert main == ["Red TRUCK arrives", "person"]
        assert len(await search(limit=2)) == 2
        # newest first + limit returns the latest, not the oldest
        newest = await search(order="desc", limit=2)
        assert [b.note for b in newest] == ["truck leaves", "person"]
    run(go)


def test_bookmarks_are_deleted_with_their_camera():
    async def go():
        cam = await Camera.create(name="Gate")
        await create_bookmark(BookmarkCreate(camera_id=cam.id, start_time=at(0), note="x"))
        await cam.delete()
        assert await Bookmark.all().count() == 0
    run(go)
