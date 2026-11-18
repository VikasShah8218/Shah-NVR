"""Event recording on the node (docs/EVENT_RECORDING_PLAN.md §5).

In event mode MediaMTX keeps recording; the scanner marks those chunks `held` (not uploaded). Every
EVENT_INTERVAL_SECONDS `event_tick`:
  1. catches up on central's events for our cameras (central also pushes each one to POST /api/v1/events);
  2. releases held chunks that overlap an event window [start - pre, end + post] (they upload as normal) and
     deletes held chunks no event can still need (older than pre + EVENT_GRACE_SECONDS);
  3. uploads events made here (video loss; ONVIF later) to central.
Works while central is down: windows and decisions are local (SQLite).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import uuid4

from tortoise.expressions import Q

from app.events.models import EventWindow
from app.node.models import KeyValue
from app.node.utils import CentralError, central, runtime
from app.schedules.services import event_setting, mode_now
from app.schedules.utils import may_use_events
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("node.events")

KV_EVENTS_SINCE = "events_since"
HELD_BATCH = 2000
UPLOAD_BATCH = 200
KEEP_WINDOWS = timedelta(days=1)
MAX_POST = timedelta(seconds=600)  # the API's upper limit for post-event seconds

# video loss watch: camera id -> first time seen down / open event key; cameras seen up since start
_down_since: dict[int, datetime] = {}
_open_loss: dict[int, str] = {}
_seen_ready: set[int] = set()
_loss_loaded = False


def _parse(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def window_span(w: EventWindow, ev: dict, now: datetime) -> tuple[datetime, datetime]:
    """The video an event keeps: pre seconds before it starts to post seconds after it ends (an open event counts
    up to now, at most `max` seconds)."""
    end = w.end_time or min(now, w.start_time + timedelta(seconds=ev["max"]))
    return w.start_time - timedelta(seconds=ev["pre"]), end + timedelta(seconds=ev["post"])


def chunk_held(camera_id: int, start: datetime, end: datetime) -> bool:
    """Hold a new chunk when its camera was in event mode while it was written (not when any of it fell in a
    continuous period: then the whole chunk is kept)."""
    cam = runtime.assignments.get(camera_id)
    if cam is None or mode_now(cam, start) != "event":
        return False
    return mode_now(cam, max(start, end - timedelta(seconds=1))) != "continuous"


# ---------------------------------------------------------------- windows from central


async def apply_window(item: dict) -> EventWindow:
    """An event from central (push or catch-up): insert or update its window."""
    w, created = await EventWindow.update_or_create(
        key=f"c{item['id']}",
        defaults={"camera_id": int(item["camera_id"]), "type": str(item.get("type") or "event")[:32],
                  "start_time": _parse(item["start_time"]), "end_time": _parse(item.get("end_time")),
                  "central_id": int(item["id"]), "node_made": False, "uploaded": True},
    )
    if created:
        logger.info("Event %s on camera %s (%s)", item["id"], w.camera_id, w.type)
    return w


def _needs_windows() -> bool:
    return any(may_use_events(c.get("recording")) for c in runtime.assignments.values())


async def catch_up() -> int:
    """Fetch event changes since the last poll (only while a camera of ours can be in event mode)."""
    if runtime.node_id is None or not _needs_windows():
        return 0
    since = (await KeyValue.get_value(KV_EVENTS_SINCE) or {}).get("since")  # JSON field: a dict, not a bare string
    try:
        data = await central.event_windows(runtime.node_id, since)
    except CentralError as exc:
        logger.debug("Event catch-up failed (will retry): %s", exc)
        return 0
    for item in data.get("items") or []:
        await apply_window(item)
    # a little overlap: an event saved in the same instant as `now` is fetched again, never missed
    nxt = _parse(data.get("now"))
    if nxt is not None:
        await KeyValue.set_value(KV_EVENTS_SINCE, {"since": (nxt - timedelta(seconds=2)).isoformat()})
    return len(data.get("items") or [])


# ---------------------------------------------------------------- events made on this node


async def add_event(camera_id: int, type_: str, start: datetime, end: datetime | None = None,
                    label: str | None = None, data: dict | None = None) -> EventWindow:
    """An event detected here. It keeps video like any event; it is uploaded to central when the camera's
    event marking is on."""
    marking = event_setting(runtime.assignments.get(camera_id))["marking"]
    w = await EventWindow.create(key=f"{settings.NODE_NAME}-{uuid4().hex}"[:96], camera_id=camera_id, type=type_,
                                 start_time=start, end_time=end, label=label, data=data, node_made=True,
                                 uploaded=not marking)
    logger.info("Event %s on camera %s at %s%s", type_, camera_id, start.isoformat(), "" if marking else " (marking off)")
    return w


async def end_event(w: EventWindow, at: datetime) -> None:
    if w.end_time is not None:
        return
    w.end_time = max(at, w.start_time)
    if w.node_made and event_setting(runtime.assignments.get(w.camera_id))["marking"]:
        w.uploaded = False
    await w.save()


async def upload_events() -> int:
    if runtime.node_id is None:
        return 0
    pending = await EventWindow.filter(node_made=True, uploaded=False).order_by("id").limit(UPLOAD_BATCH)
    if not pending:
        return 0
    items = [{"key": w.key, "camera_id": w.camera_id, "type": w.type, "start_time": w.start_time.isoformat(),
              "end_time": w.end_time.isoformat() if w.end_time else None, "label": w.label, "data": w.data}
             for w in pending]
    try:
        ids = (await central.upload_events(runtime.node_id, items)).get("ids") or {}
    except CentralError as exc:
        logger.debug("Event upload failed (will retry): %s", exc)
        return 0
    for w in pending:
        # only if unchanged meanwhile (an end set during the upload is sent next time)
        q = EventWindow.filter(id=w.id)
        q = q.filter(end_time=w.end_time) if w.end_time else q.filter(end_time__isnull=True)
        await q.update(uploaded=True, central_id=ids.get(w.key))
    return len(pending)


async def watch_video_loss(camera_id: int, ready: bool, now: datetime) -> None:
    """Called by the status loop for each camera with a recorded stream: a camera seen up since the node started
    and down for VIDEO_LOSS_SECONDS opens a video_loss event; it is closed when the camera is back."""
    if ready:
        _seen_ready.add(camera_id)
        _down_since.pop(camera_id, None)
        key = _open_loss.pop(camera_id, None)
        if key is not None:
            w = await EventWindow.get_or_none(key=key)
            if w is not None:
                await end_event(w, now)
                logger.info("Camera %s video is back (lost for %ss)", camera_id,
                            int((now - w.start_time).total_seconds()))
        return
    if camera_id not in _seen_ready or camera_id in _open_loss:
        return
    since = _down_since.setdefault(camera_id, now)
    if now - since >= timedelta(seconds=settings.VIDEO_LOSS_SECONDS):
        w = await add_event(camera_id, "video_loss", since)
        _open_loss[camera_id] = w.key


# ---------------------------------------------------------------- keep / delete held chunks


async def _windows_by_camera(camera_ids, oldest: datetime) -> dict[int, list[EventWindow]]:
    rows = await EventWindow.filter(Q(end_time__isnull=True) | Q(end_time__gte=oldest - MAX_POST),
                                    camera_id__in=list(camera_ids))
    out: dict[int, list[EventWindow]] = {}
    for w in rows:
        out.setdefault(w.camera_id, []).append(w)
    return out


async def active_camera_ids(now: datetime | None = None) -> set[int]:
    """Cameras inside an event window right now (their status is RECORDING, not EVENT_STANDBY)."""
    now = now or utcnow()
    rows = await EventWindow.filter(Q(end_time__isnull=True) | Q(end_time__gte=now - MAX_POST),
                                    start_time__lte=now + timedelta(seconds=60))
    active = set()
    for w in rows:
        start, end = window_span(w, event_setting(runtime.assignments.get(w.camera_id)), now)
        if start <= now <= end:
            active.add(w.camera_id)
    return active


async def decide_held(now: datetime | None = None) -> tuple[int, int]:
    """Release held chunks an event covers, delete those no event can still need. Returns (kept, deleted)."""
    from app.recordings.models import LocalSegment
    from app.recordings.services import _as_items, _delete_local

    now = now or utcnow()
    held = await LocalSegment.filter(held=True).order_by("start_time").limit(HELD_BATCH)
    if not held:
        return 0, 0
    windows = await _windows_by_camera({s.camera_id for s in held}, held[0].start_time)
    grace = timedelta(seconds=settings.EVENT_GRACE_SECONDS)
    keep, drop = [], []
    for s in held:
        ev = event_setting(runtime.assignments.get(s.camera_id))
        spans = [window_span(w, ev, now) for w in windows.get(s.camera_id, ())]
        if any(start < s.end_time and s.start_time < end for start, end in spans):
            keep.append(s)
        elif s.end_time < now - timedelta(seconds=ev["pre"]) - grace:
            drop.append(s)
    if keep:
        await LocalSegment.filter(id__in=[s.id for s in keep]).update(held=False)
    deleted = await _delete_local(_as_items(drop)) if drop else []
    if keep or deleted:
        logger.debug("Event recording: kept %s chunk(s), deleted %s", len(keep), len(deleted))
    return len(keep), len(deleted)


async def prune_windows(now: datetime | None = None) -> int:
    now = now or utcnow()
    old = now - KEEP_WINDOWS
    return await EventWindow.filter(Q(end_time__lt=old) | Q(end_time__isnull=True, start_time__lt=old - KEEP_WINDOWS),
                                    uploaded=True).delete()


async def load_open_losses() -> None:
    """Video loss events still open from before a restart: closed when their camera is seen up again."""
    global _loss_loaded
    if not _loss_loaded:
        _loss_loaded = True
        for w in await EventWindow.filter(node_made=True, type="video_loss", end_time__isnull=True):
            _open_loss.setdefault(w.camera_id, w.key)
            _seen_ready.add(w.camera_id)


async def event_tick() -> None:
    await load_open_losses()
    await catch_up()
    await decide_held()
    await upload_events()
    await prune_windows()
