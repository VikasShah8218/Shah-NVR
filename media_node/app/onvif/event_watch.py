"""Camera events from ONVIF PullPoint: one task per camera with camera events on (docs/ONVIF_EVENTS_PLAN.md §5.3).

A camera's task: clock offset -> GetEventProperties -> pick one topic per kind -> subscribe (topic filter when the
camera takes it) -> pull with a 10 s wait, renew every 30 s. Edges become node events (`app.events.services`), which
keep video in event mode and are uploaded to central like video loss.

Rules:
- a wrong login stops the camera's task until its settings change or 30 min pass (D4: accounts lock);
- a start within `post` seconds of the last end of the same thing reopens that event (D7: flapping motion);
- an event still on after `max` seconds is closed and a new one opened at once (D7: busy scenes keep recording);
- event time = camera time minus its clock offset, or our receive time if that is more than 5 s off (D8).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.events.models import EventWindow
from app.events.services import add_event, end_event
from app.node.utils import runtime
from app.onvif.event_topics import KINDS, Edge, EdgeTracker, kind_topics, offered_kinds, topic_filter, topics_text
from app.onvif.events import EventClient, InvalidFilter, Subscription
from app.onvif.services import OnvifDevice
from app.onvif.soap import NotAuthorized, NotSupported, OnvifError, Unreachable
from app.schedules.services import event_setting
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("node.onvif.events")

NODE_TYPES = KINDS + ("onvif",)
TERMINATION_SECONDS = 60
AUTH_RETRY_SECONDS = 1800
NO_TOPICS_RETRY_SECONDS = 600
TIME_TOLERANCE = timedelta(seconds=5)


@dataclass(frozen=True)
class WatchConfig:
    camera_id: int
    host: str
    port: int
    username: str
    password: str
    kinds: tuple[str, ...]
    store_other: bool


def config_of(camera_id: int, cam: dict) -> WatchConfig | None:
    ev = cam.get("onvif_events")
    if not ev or not cam.get("onvif_host"):
        return None
    kinds = tuple(k for k in (ev.get("kinds") or KINDS) if k in KINDS)
    if not kinds and not ev.get("store_other"):
        return None
    return WatchConfig(camera_id, cam["onvif_host"], int(cam.get("onvif_port") or 80), ev.get("username") or "",
                       ev.get("password") or "", kinds, bool(ev.get("store_other")))


# ---------------------------------------------------------------- status (sent to central in the heartbeat)

_status: dict[int, dict] = {}


def set_status(camera_id: int, state: str, **extra) -> None:
    old = _status.get(camera_id) or {}
    new = {"camera_id": camera_id, "state": state, "topics": extra.get("topics", old.get("topics")),
           "offered": extra.get("offered", old.get("offered")), "detail": extra.get("detail"),
           "last_event_at": old.get("last_event_at"), "since": old.get("since") if old.get("state") == state
           else utcnow().isoformat(), "sent": False}
    if {k: v for k, v in new.items() if k not in ("since", "sent")} != {k: v for k, v in old.items() if k not in ("since", "sent")}:
        _status[camera_id] = new
        if old.get("state") != state:
            logger.info("Camera %s events: %s%s", camera_id, state, f" ({extra['detail']})" if extra.get("detail") else "")


def take_status() -> list[dict]:
    return [{k: v for k, v in s.items() if k != "sent"} for s in _status.values() if not s["sent"]]


def ack_status(sent: list[dict]) -> None:
    for s in sent:
        cur = _status.get(s["camera_id"])
        if cur is not None and all(cur.get(k) == v for k, v in s.items()):
            cur["sent"] = True


def drop_status(camera_id: int) -> None:
    """Camera events switched off: central clears the status from the next assignment itself."""
    _status.pop(camera_id, None)


# ---------------------------------------------------------------- applying edges


@dataclass
class EventState:
    """The node events one camera's edges made: open ones, and the last closed one per thing (for merging)."""

    open: dict[str, EventWindow] = field(default_factory=dict)
    closed: dict[str, EventWindow] = field(default_factory=dict)


def event_time(camera_time: datetime | None, offset: float, now: datetime) -> datetime:
    if camera_time is None:
        return now
    t = camera_time - timedelta(seconds=offset)
    return t if abs(t - now) <= TIME_TOLERANCE else now


async def apply_edge(camera_id: int, edge: Edge, at: datetime, st: EventState) -> None:
    post = timedelta(seconds=event_setting(runtime.assignments.get(camera_id))["post"])
    if edge.action == "end":
        w = st.open.pop(edge.key, None)
        if w is not None:
            await end_event(w, at)
            st.closed[edge.key] = w
        return
    last = st.closed.get(edge.key)
    if last is not None and last.end_time is not None and at - last.end_time <= post:
        # again within the post-event time: the same event goes on (D7)
        if edge.action == "start":
            await reopen_event(last)
            st.open[edge.key] = st.closed.pop(edge.key)
        else:
            await end_event(_reopened(last), at)
        return
    w = await add_event(camera_id, edge.kind, at, at if edge.action == "moment" else None, edge.label, edge.data)
    _status.get(camera_id, {}).update(last_event_at=at.isoformat(), sent=False)
    if edge.action == "start":
        st.open[edge.key] = w
    else:
        st.closed[edge.key] = w


def _reopened(w: EventWindow) -> EventWindow:
    w.end_time = None
    return w


async def reopen_event(w: EventWindow) -> None:
    w.end_time = None
    if event_setting(runtime.assignments.get(w.camera_id))["marking"]:
        w.uploaded = False
    await w.save()


async def split_long(camera_id: int, st: EventState, now: datetime) -> None:
    """Events on for longer than `max`: close at max and open the next one (D7)."""
    limit = timedelta(seconds=event_setting(runtime.assignments.get(camera_id))["max"])
    for key, w in list(st.open.items()):
        if now - w.start_time >= limit:
            at = w.start_time + limit
            await end_event(w, at)
            st.open[key] = await add_event(camera_id, w.type, at, None, w.label, w.data)
            st.closed.pop(key, None)


async def close_all(st: EventState, at: datetime) -> None:
    for w in st.open.values():
        await end_event(w, at)
    st.open.clear()


async def close_stale_events() -> int:
    """Camera events left open by a previous run of the node: closed now (the state is read again on subscribe)."""
    stale = await EventWindow.filter(node_made=True, type__in=list(NODE_TYPES), end_time__isnull=True)
    now = utcnow()
    for w in stale:
        await end_event(w, now)
    return len(stale)


# ---------------------------------------------------------------- one camera


class CameraWatch:
    def __init__(self, cfg: WatchConfig):
        self.cfg = cfg
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name=f"onvif-events-{self.cfg.camera_id}")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def run(self) -> None:
        cfg, st, backoff = self.cfg, EventState(), 5.0
        tracker: EdgeTracker | None = None
        try:
            while True:
                try:
                    async with OnvifDevice(cfg.host, cfg.port, cfg.username, cfg.password, timeout=10) as dev:
                        tracker = await self.session(dev, st, tracker)
                    backoff = 5.0
                except NotAuthorized as exc:
                    set_status(cfg.camera_id, "auth_failed", detail=exc.message[:200])
                    await close_all(st, utcnow())
                    await asyncio.sleep(AUTH_RETRY_SECONDS)  # D4: a settings change restarts the task sooner
                    continue
                except NotSupported as exc:
                    set_status(cfg.camera_id, "unsupported", detail=exc.message[:200])
                    await close_all(st, utcnow())
                    await asyncio.sleep(NO_TOPICS_RETRY_SECONDS)
                    continue
                except _NoTopics:
                    await asyncio.sleep(NO_TOPICS_RETRY_SECONDS)
                    continue
                except OnvifError as exc:
                    set_status(cfg.camera_id, "unreachable" if isinstance(exc, Unreachable) else "error",
                               detail=exc.message[:200])
                    await close_all(st, utcnow())
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # never let one camera's surprise stop its events for good
                    logger.exception("Camera %s events failed", cfg.camera_id)
                    set_status(cfg.camera_id, "error", detail=f"{type(exc).__name__}: {exc}"[:200])
                    await close_all(st, utcnow())
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)  # lab Q4: back off 5 -> 60 s
        finally:
            await asyncio.shield(close_all(st, utcnow()))

    async def session(self, dev: OnvifDevice, st: EventState, tracker: EdgeTracker | None) -> EdgeTracker:
        """One subscription, until an error. Returns the tracker so states survive a resubscribe."""
        cfg = self.cfg
        await dev.clock()  # Q1: offset for the login and the event times
        client = EventClient(dev)
        offered = await client.properties()
        chosen = kind_topics(offered, cfg.kinds)  # every offered motion topic (an ISIN lists one it never sends)
        info = {"topics": topics_text(chosen), "offered": offered_kinds(offered)}
        if not chosen and not cfg.store_other:
            set_status(cfg.camera_id, "no_topics", detail="the camera offers none of the chosen event kinds", **info)
            raise _NoTopics
        if tracker is None or tracker.kind_of != EdgeTracker(chosen).kind_of:
            tracker = EdgeTracker(chosen, cfg.store_other)
        filt = None if cfg.store_other else topic_filter(chosen, offered)
        try:
            sub = await client.subscribe(TERMINATION_SECONDS, filt)
        except InvalidFilter:
            sub = await client.subscribe(TERMINATION_SECONDS)  # lab Q5: ISIN refuses some filters
        set_status(cfg.camera_id, "ok", **info)
        try:
            try:
                await client.sync_point(sub)  # current states as Initialized messages
            except OnvifError:
                pass
            await self.pull_loop(dev, client, sub, st, tracker)
        finally:
            try:
                await asyncio.shield(client.unsubscribe(sub))
            except (OnvifError, asyncio.CancelledError):
                pass
        return tracker

    async def pull_loop(self, dev: OnvifDevice, client: EventClient, sub: Subscription, st: EventState,
                        tracker: EdgeTracker) -> None:
        cfg = self.cfg
        renew_at = time.monotonic() + settings.ONVIF_EVENTS_RENEW_SECONDS
        while True:
            messages = await client.pull(sub, wait=settings.ONVIF_EVENTS_PULL_SECONDS)
            now = utcnow()
            for m in messages:
                edge = tracker.feed(m)
                if edge is not None:
                    await apply_edge(cfg.camera_id, edge, event_time(edge.camera_time, dev.soap.offset, now), st)
            await split_long(cfg.camera_id, st, now)
            if time.monotonic() >= renew_at:
                try:
                    await client.renew(sub, TERMINATION_SECONDS)
                except OnvifError:
                    await client.renew(sub, TERMINATION_SECONDS)  # lab Q4: retry once, then resubscribe
                renew_at = time.monotonic() + settings.ONVIF_EVENTS_RENEW_SECONDS


class _NoTopics(Exception):
    pass


# ---------------------------------------------------------------- supervisor

_watches: dict[int, CameraWatch] = {}
_started = False


def desired() -> dict[int, WatchConfig]:
    if not settings.ONVIF_EVENTS_ENABLED:
        return {}
    out = {}
    for cid, cam in list(runtime.assignments.items()):
        cfg = config_of(cid, cam)
        if cfg is not None:
            out[cid] = cfg
    return out


async def events_supervisor_tick() -> None:
    """Start / restart / stop camera tasks to match the assignments (every reconcile)."""
    global _started
    if not _started:
        _started = True
        if n := await close_stale_events():
            logger.info("Closed %s camera event(s) left open by the last run", n)
    want = desired()
    for cid in list(_watches):
        if cid not in want or _watches[cid].cfg != want[cid]:
            await _watches.pop(cid).stop()
            if cid not in want:
                drop_status(cid)
    new = [cfg for cid, cfg in want.items() if cid not in _watches]
    for i, cfg in enumerate(new):
        w = _watches[cfg.camera_id] = CameraWatch(cfg)
        w.start()
        if i and i % settings.ONVIF_EVENTS_CONCURRENCY == 0:
            await asyncio.sleep(1)  # spread the first logins of a large node


async def stop_all() -> None:
    for w in list(_watches.values()):
        await w.stop()
    _watches.clear()
