"""Bookmarks: operator notes on a moment or range of a camera's recordings, searchable by text.

Used by the playback timeline (markers) and the bookmark search panel. Video is never touched here.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from tortoise.expressions import Q

from app.bookmarks.models import Bookmark
from app.bookmarks.schemas import BookmarkCreate, BookmarkOut, BookmarkUpdate, _utc
from app.cameras.models import Camera

router = APIRouter(prefix="/api/v1/bookmarks", tags=["Bookmarks"])


def _out(b: Bookmark) -> BookmarkOut:
    return BookmarkOut(
        id=b.id, camera_id=b.camera_id, camera_name=b.camera.name, profile=b.profile,  # type: ignore[attr-defined]
        start_time=b.start_time, end_time=b.end_time, note=b.note, label=b.label, color=b.color,
        author=b.author, created_at=b.created_at, updated_at=b.updated_at,
    )


async def _get(bookmark_id: int) -> Bookmark:
    b = await Bookmark.get_or_none(id=bookmark_id).prefetch_related("camera")
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bookmark not found")
    return b


@router.post("", response_model=BookmarkOut, status_code=status.HTTP_201_CREATED)
async def create_bookmark(body: BookmarkCreate):
    if not await Camera.exists(id=body.camera_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    b = await Bookmark.create(**body.model_dump())
    return _out(await _get(b.id))


@router.get("", response_model=list[BookmarkOut], summary="List / search bookmarks")
async def list_bookmarks(
    camera_id: int | None = None,
    profile: str | None = Query(default=None, description="Also includes camera-wide bookmarks (no profile)"),
    q: str | None = Query(default=None, max_length=200, description="Text search in the note and label"),
    start: datetime | None = Query(default=None, description="Only bookmarks overlapping [start, end)"),
    end: datetime | None = None,
    order: Literal["asc", "desc"] = Query(default="asc", description="By start time; desc = newest first"),
    limit: int = Query(default=200, ge=1, le=1000),
):
    qs = Bookmark.all()
    if camera_id is not None:
        qs = qs.filter(camera_id=camera_id)
    if profile:
        qs = qs.filter(Q(profile=profile) | Q(profile__isnull=True))
    if q and q.strip():
        term = q.strip()
        qs = qs.filter(Q(note__icontains=term) | Q(label__icontains=term))
    start, end = _utc(start), _utc(end)
    if start is not None and end is not None and end <= start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end must be after start")
    if end is not None:
        qs = qs.filter(start_time__lt=end)
    if start is not None:
        # A range overlaps when it ends at/after `start`; a point when it is at/after `start`.
        qs = qs.filter(Q(end_time__gte=start) | Q(end_time__isnull=True, start_time__gte=start))
    ordering = ("start_time", "id") if order == "asc" else ("-start_time", "-id")
    rows = await qs.order_by(*ordering).limit(limit).prefetch_related("camera")
    return [_out(b) for b in rows]


@router.get("/{bookmark_id}", response_model=BookmarkOut)
async def get_bookmark(bookmark_id: int):
    return _out(await _get(bookmark_id))


@router.patch("/{bookmark_id}", response_model=BookmarkOut)
async def update_bookmark(bookmark_id: int, body: BookmarkUpdate):
    b = await _get(bookmark_id)
    data = body.model_dump(exclude_unset=True)
    if "note" in data and data["note"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "note cannot be removed")
    if "start_time" in data and data["start_time"] is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "start_time cannot be removed")
    start = data.get("start_time", b.start_time)
    end = data["end_time"] if "end_time" in data else b.end_time
    if end is not None and end <= start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end_time must be after start_time")
    if data:
        await b.update_from_dict(data).save()
    return _out(await _get(bookmark_id))


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(bookmark_id: int):
    b = await _get(bookmark_id)
    await b.delete()
