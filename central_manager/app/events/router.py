"""Events: timeline marks, and the triggers of event recording (docs/EVENT_RECORDING_PLAN.md §4.3)."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.auth import scope
from app.auth.principal import current
from app.bookmarks.schemas import _utc
from app.cameras.models import Camera
from app.events import services
from app.events.models import Event
from app.events.schemas import EventCreate, EventOut, EventWindowsOut, NodeEventsIn, NodeEventsOut
from app.nodes.models import MediaNode
from utilities.common import utcnow
from utilities.pagination import Page

router = APIRouter(prefix="/api/v1", tags=["Events"])

# Type groups for the Events page filter (docs/ONVIF_ANALYTICS_EVENTS_PLAN.md A9)
TYPE_GROUPS = {
    "camera": ("motion", "tamper", "digital_input", "video_loss", "video_restored", "onvif"),
    "analytics": ("line_crossing", "intrusion", "loitering", "object_left", "person", "face", "counting",
                  "audio_alarm"),
    "operator": ("manual", "api"),
}
internal_router = APIRouter(prefix="/internal/v1/nodes", tags=["Internal (media nodes)"])


async def _get(event_id: int) -> Event:
    e = await Event.get_or_none(id=event_id).prefetch_related("camera")
    if e is None or not await scope.camera_visible(e.camera_id):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return e


@router.post("/cameras/{camera_id}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED,
             summary="Mark an event (operator button or another system); extends a recent one of the same type")
async def create_event(camera_id: int, body: EventCreate):
    camera = await Camera.get_or_none(id=camera_id)
    if camera is None or not await scope.camera_visible(camera_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    p = current()
    e, merged = await services.create(camera, body, f"{'user' if body.type == 'manual' else 'api'}:{p.username}")
    services.push_soon(e)
    return services.out(await _get(e.id), merged)


@router.get("/events", response_model=Page[EventOut], summary="List events (paged; timeline marks and the Events page)")
async def list_events(
    camera_id: int | None = None,
    type: str | None = Query(default=None, description="One type or several, comma separated"),
    start: datetime | None = Query(default=None, description="Only events overlapping [start, end)"),
    end: datetime | None = None,
    group: Literal["camera", "analytics", "operator"] | None = Query(default=None, description="A type group"),
    q: str | None = Query(default=None, max_length=64, description="Label contains (case-insensitive): rule, object"),
    order: Literal["asc", "desc"] = Query(default="desc", description="By start time; desc = newest first"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    qs = Event.all()
    if (visible := await scope.camera_ids_subquery()) is not None:
        qs = qs.filter(camera_id__in=visible)
    if camera_id is not None:
        qs = qs.filter(camera_id=camera_id)
    if type:
        types = [t.strip() for t in type.split(",") if t.strip()]
        qs = qs.filter(type__in=types)
    if group:
        qs = qs.filter(type__in=list(TYPE_GROUPS[group]))
    if q and q.strip():
        qs = qs.filter(label__icontains=q.strip())
    start, end = _utc(start), _utc(end)
    if start is not None and end is not None and end <= start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "end must be after start")
    if end is not None:
        qs = qs.filter(start_time__lt=end)
    if start is not None:
        from tortoise.expressions import Q

        qs = qs.filter(Q(end_time__gte=start) | Q(end_time__isnull=True))
    ordering = ("start_time", "id") if order == "asc" else ("-start_time", "-id")
    total = await qs.count()
    rows = await qs.order_by(*ordering).offset(offset).limit(limit).prefetch_related("camera")
    return Page(items=[services.out(e) for e in rows], total=total, limit=limit, offset=offset)


@router.get("/events/{event_id}", response_model=EventOut)
async def get_event(event_id: int):
    return services.out(await _get(event_id))


@router.post("/events/{event_id}/end", response_model=EventOut, summary="End an ongoing event (now)")
async def end_event(event_id: int):
    e = await _get(event_id)
    if e.end_time is None:
        await services.end(e)
        services.push_soon(e)
    return services.out(e)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete an event mark (video already kept for it stays)")
async def delete_event(event_id: int):
    e = await _get(event_id)
    await e.delete()


# ================================================================ internal API (called by media nodes)


async def _node(node_id: int) -> MediaNode:
    node = await MediaNode.get_or_none(id=node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    return node


@internal_router.post("/{node_id}/events", response_model=NodeEventsOut, summary="Events the node detected")
async def upload_node_events(node_id: int, body: NodeEventsIn):
    await _node(node_id)
    return NodeEventsOut(ids=await services.upsert_from_node(node_id, body.items))


@internal_router.get("/{node_id}/events", response_model=EventWindowsOut,
                     summary="Event changes for this node's cameras since a time (the node's catch-up)")
async def node_event_windows(node_id: int, since: datetime | None = None):
    await _node(node_id)
    now = utcnow()
    rows = await services.node_windows(node_id, _utc(since), now)
    return EventWindowsOut(items=[services.window(e) for e in rows], now=now)
