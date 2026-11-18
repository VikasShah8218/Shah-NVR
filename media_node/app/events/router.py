"""Events pushed by central (docs/EVENT_RECORDING_PLAN.md E4) and a debug list of this node's event windows."""

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.events.models import EventWindow
from app.events.services import apply_window

router = APIRouter(prefix="/api/v1/events", tags=["Events"])


class EventWindowIn(BaseModel):
    id: int
    camera_id: int
    type: str = "event"
    start_time: datetime
    end_time: datetime | None = None
    updated_at: datetime | None = None


class EventWindowOut(BaseModel):
    key: str
    camera_id: int
    type: str
    start_time: datetime
    end_time: datetime | None
    central_id: int | None
    node_made: bool
    uploaded: bool


@router.post("", summary="An event of one of this node's cameras (central pushes each change)")
async def push_event(body: EventWindowIn):
    await apply_window(body.model_dump())
    return {"ok": True}


@router.get("", response_model=list[EventWindowOut], summary="Recent event windows on this node (debug)")
async def list_windows(camera_id: int | None = None, limit: int = Query(100, ge=1, le=1000)):
    qs = EventWindow.all()
    if camera_id is not None:
        qs = qs.filter(camera_id=camera_id)
    rows = await qs.order_by("-start_time").limit(limit)
    return [EventWindowOut(**{k: getattr(w, k) for k in EventWindowOut.model_fields}) for w in rows]
