"""Events: create / merge / end, tell the recording node, node uploads and catch-up, upkeep
(docs/EVENT_RECORDING_PLAN.md §4).

The node decides which held chunks to keep (E3). Central only stores events and passes every change on: pushed to
the camera's node right away (best effort) and served to the node's catch-up poll (reliable).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException

from app.assignments.models import CameraAssignment
from app.cameras.models import Camera
from app.events.models import Event
from app.events.schemas import EventCreate, EventOut
from app.nodes.client import REACHABLE_STATES, call_node
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("central.events")

USER_TYPES = ("manual", "api")  # closed by central after EVENT_MAX_SECONDS; node types are closed by the node
PUSH_TIMEOUT_SECONDS = 3.0
WINDOWS_LIMIT = 1000


def out(e: Event, merged: bool = False) -> EventOut:
    cam: Camera = e.camera  # type: ignore[assignment]
    return EventOut(id=e.id, camera_id=e.camera_id, camera_name=cam.name, type=e.type, source=e.source,  # type: ignore[attr-defined]
                    start_time=e.start_time, end_time=e.end_time, label=e.label, data=e.data,
                    pre_seconds=cam.event_pre_seconds, post_seconds=cam.event_post_seconds, merged=merged,
                    created_at=e.created_at, updated_at=e.updated_at)


def window(e: Event) -> dict:
    return {"id": e.id, "camera_id": e.camera_id, "type": e.type,  # type: ignore[attr-defined]
            "start_time": e.start_time.isoformat(), "end_time": e.end_time.isoformat() if e.end_time else None,
            "updated_at": e.updated_at.isoformat()}


async def create(camera: Camera, body: EventCreate, source: str, now: datetime | None = None) -> tuple[Event, bool]:
    """Save a manual / API event, or extend the camera's last event of the same type and label when the new one
    starts within its post-event seconds (E5: a repeated trigger is one event, not hundreds)."""
    now = now or utcnow()
    start = body.start_time or now
    end = None if body.ongoing else start + timedelta(seconds=body.duration_seconds)
    last = await Event.filter(camera_id=camera.id, type=body.type, start_time__lte=start).order_by("-start_time").first()
    if last is not None and (body.label is None or body.label == last.label):
        reach = None if last.end_time is None else last.end_time + timedelta(seconds=camera.event_post_seconds)
        if reach is None or reach >= start:
            if last.end_time is not None:
                last.end_time = None if end is None else max(last.end_time, end)
                await last.save(update_fields=["end_time", "updated_at"])
            return last, True
    return await Event.create(camera_id=camera.id, type=body.type, source=source, start_time=start, end_time=end,
                              label=body.label, data=body.data), False


async def end(e: Event, at: datetime | None = None) -> Event:
    if e.end_time is None:
        e.end_time = max(at or utcnow(), e.start_time)
        await e.save(update_fields=["end_time", "updated_at"])
    return e


async def push_to_node(e: Event) -> bool:
    """Tell the node that records the camera now (so it can keep video and show RECORDING). Never raises: the
    node's catch-up poll picks up anything a push missed."""
    a = await CameraAssignment.get_or_none(camera_id=e.camera_id).prefetch_related("node")  # type: ignore[attr-defined]
    if a is None or a.node is None or a.node.state not in REACHABLE_STATES:
        return False
    try:
        await call_node(a.node, "/api/v1/events", window(e), timeout=PUSH_TIMEOUT_SECONDS)
        return True
    except HTTPException as exc:
        logger.debug("Event %s push to node %s failed: %s", e.id, a.node.name, exc.detail)
        return False


def push_soon(e: Event) -> None:
    """Push without making the caller wait for the node."""
    task = asyncio.create_task(push_to_node(e))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


_pending: set[asyncio.Task] = set()


async def node_windows(node_id: int, since: datetime | None, now: datetime | None = None) -> list[Event]:
    """Events of this node's cameras changed since `since` (default: the last EVENT_MAX_SECONDS + 10 min)."""
    now = now or utcnow()
    since = since or now - timedelta(seconds=settings.EVENT_MAX_SECONDS + 600)
    owned = await CameraAssignment.filter(node_id=node_id).values_list("camera_id", flat=True)
    if not owned:
        return []
    return await (Event.filter(camera_id__in=list(owned), updated_at__gte=since)
                  .order_by("updated_at", "id").limit(WINDOWS_LIMIT))


async def upsert_from_node(node_id: int, items) -> dict[str, int]:
    """Node-made events (video loss; ONVIF later): insert, or update the end of one uploaded before."""
    owned = set(await CameraAssignment.filter(node_id=node_id).values_list("camera_id", flat=True))
    node = await a_node_name(node_id)
    ids: dict[str, int] = {}
    for it in items:
        existing = await Event.get_or_none(node_key=it.key)
        if existing is not None:
            if existing.end_time != it.end_time or existing.label != it.label:
                existing.end_time, existing.label = it.end_time, it.label
                if it.data is not None:
                    existing.data = it.data
                await existing.save(update_fields=["end_time", "label", "data", "updated_at"])
            ids[it.key] = existing.id
            continue
        if it.camera_id not in owned:
            continue  # moved to another node meanwhile; that node reports its own events
        e = await Event.create(camera_id=it.camera_id, type=it.type, source=f"node:{node}", start_time=it.start_time,
                               end_time=it.end_time, label=it.label, data=it.data, node_key=it.key)
        ids[it.key] = e.id
    return ids


async def a_node_name(node_id: int) -> str:
    from app.nodes.models import MediaNode

    node = await MediaNode.get_or_none(id=node_id)
    return node.name if node else str(node_id)


async def event_upkeep_tick(now: datetime | None = None) -> None:
    """Close manual / API events nobody ended (EVENT_MAX_SECONDS), delete marks older than EVENT_RETENTION_DAYS."""
    now = now or utcnow()
    limit = timedelta(seconds=settings.EVENT_MAX_SECONDS)
    for e in await Event.filter(end_time__isnull=True, type__in=USER_TYPES, start_time__lt=now - limit):
        e.end_time = e.start_time + limit
        await e.save(update_fields=["end_time", "updated_at"])
        logger.info("Event %s (camera %s, %s) closed after %ss", e.id, e.camera_id, e.type, settings.EVENT_MAX_SECONDS)  # type: ignore[attr-defined]
    removed = await Event.filter(start_time__lt=now - timedelta(days=settings.EVENT_RETENTION_DAYS)).delete()
    if removed:
        logger.info("Deleted %s event mark(s) older than %s days", removed, settings.EVENT_RETENTION_DAYS)
