"""Event recording on the node (docs/EVENT_RECORDING_PLAN.md §5, §9): held chunks, keep / delete at the window
edges, catch-up, upload of node events, video loss, EVENT_STANDBY status, short chunks for event cameras."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from tortoise import Tortoise

import app.recordings.services as rec
from app.events import services as ev
from app.events.models import EventWindow
from app.mediamtx import services as mtx_services
from app.node import services as node_services
from app.node.models import KeyValue
from app.node.utils import runtime
from app.recordings.models import LocalSegment

T0 = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)  # a Tuesday
EVENTS = {"pre": 10, "post": 30, "marking": True, "max": 300}
NIGHT_EVENT = {"mode": "schedule", "events": EVENTS, "blocks": [
    {"days": list(range(7)), "start": "08:00", "end": "20:00", "mode": "continuous"},
    {"days": list(range(7)), "start": "20:00", "end": "08:00", "mode": "event"}]}


def _cam(cid, recording):
    return {"camera_id": cid, "camera_name": f"cam {cid}", "generation": 1, "recording": recording, "streams": [
        {"profile": "main", "path_name": f"cam-{cid}/main", "source_url": "rtsp://sim/x", "record": True,
         "rtsp_transport": "tcp"}]}


@pytest.fixture
def node(monkeypatch):
    saved = (runtime.assignments, runtime.site_timezone, runtime.node_id, runtime.mediamtx_running)
    runtime.assignments = {1: _cam(1, {"mode": "event", "events": EVENTS}), 2: _cam(2, {"mode": "always"}),
                           3: _cam(3, NIGHT_EVENT)}
    runtime.site_timezone = "UTC"
    runtime.node_id = 7
    ev._down_since.clear(), ev._open_loss.clear(), ev._seen_ready.clear()
    yield
    runtime.assignments, runtime.site_timezone, runtime.node_id, runtime.mediamtx_running = saved


def run_db(tmp_path, coro_fn):
    async def run():
        await Tortoise.init(db_url=f"sqlite://{(tmp_path / 'node.sqlite3').as_posix()}",
                            modules={"models": ["app.node.models", "app.recordings.models", "app.events.models"]})
        await Tortoise.generate_schemas()
        try:
            return await coro_fn()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(run())


async def _chunk(cid, start, seconds=10, held=True):
    return await LocalSegment.create(
        id=uuid4(), camera_id=cid, profile="main", rel_path=f"cam-{cid}/main/x/{start:%H-%M-%S}.mp4",
        start_time=start, end_time=start + timedelta(seconds=seconds), duration_ms=seconds * 1000, size_bytes=1,
        init_size=1, parts=[], tracks={}, held=held)


def test_chunk_held_follows_the_mode(node):
    assert ev.chunk_held(1, T0, T0 + timedelta(seconds=10)) is True  # event mode
    assert ev.chunk_held(2, T0, T0 + timedelta(seconds=10)) is False  # always
    night = T0.replace(hour=21)
    assert ev.chunk_held(3, night, night + timedelta(seconds=10)) is True
    assert ev.chunk_held(3, T0, T0 + timedelta(seconds=10)) is False  # day: continuous
    # a chunk running into the continuous block (07:59:55 -> 08:00:05) is kept whole
    edge = T0.replace(hour=7, minute=59, second=55)
    assert ev.chunk_held(3, edge, edge + timedelta(seconds=10)) is False
    assert ev.chunk_held(99, T0, T0) is False  # unknown camera


def test_short_chunks_for_event_cameras(node, monkeypatch):
    monkeypatch.setattr(mtx_services, "storage", SimpleNamespace(target=lambda: SimpleNamespace(path="D:/rec")))
    monkeypatch.setattr(mtx_services, "utcnow", lambda: T0)
    d = mtx_services.desired_paths()
    assert d["cam-1/main"]["record"] is True and d["cam-1/main"]["recordSegmentDuration"] == "10s"
    assert d["cam-3/main"]["recordSegmentDuration"] == "10s"  # can be in event mode at night
    assert d["cam-2/main"]["recordSegmentDuration"] == "60s"
    assert mtx_services.same_value("recordSegmentDuration", "1m0s", "60s")
    assert mtx_services.same_value("recordSegmentDuration", "60000ms", "60s")
    assert not mtx_services.same_value("recordSegmentDuration", "1m0s", "10s")
    assert not mtx_services.same_value("recordSegmentDuration", None, "10s")


def test_keep_and_delete_around_an_event(tmp_path, node, monkeypatch):
    deleted = []

    async def fake_delete(items):
        deleted.extend(i for i, _k, _r in items)
        return [i for i, _k, _r in items]

    monkeypatch.setattr(rec, "_delete_local", fake_delete)

    async def body():
        # chunks every 10 s from 09:58 to 10:02; event (a moment) at 10:00:00, pre 10 s, post 30 s
        chunks = [await _chunk(1, T0 + timedelta(seconds=s)) for s in range(-120, 120, 10)]
        await ev.apply_window({"id": 5, "camera_id": 1, "type": "manual", "start_time": T0.isoformat(),
                               "end_time": T0.isoformat()})
        now = T0 + timedelta(seconds=125)
        kept, dropped = await ev.decide_held(now)
        released = {str(s.id) for s in await LocalSegment.filter(held=False)}
        keep_starts = sorted((s.start_time - T0).total_seconds() for s in chunks if str(s.id) in released)
        # [09:59:50, 10:00:30] overlaps the chunks starting at -10, 0, 10, 20 (the one at 30 starts at the edge)
        assert keep_starts == [-10, 0, 10, 20]
        # deleted: ended before now - pre - grace = 10:01:25 and not kept
        drop_starts = sorted((s.start_time - T0).total_seconds() for s in chunks if str(s.id) in deleted)
        assert drop_starts == [s for s in range(-120, 80, 10) if s not in (-10, 0, 10, 20)]
        assert kept == 4 and dropped == len(drop_starts)
        # still held: the newest chunks may still be needed by a late event
        still = await LocalSegment.filter(held=True).exclude(id__in=deleted).count()
        assert still == len(chunks) - 4 - len(drop_starts)

    run_db(tmp_path, body)


def test_open_event_keeps_until_it_ends(tmp_path, node, monkeypatch):
    monkeypatch.setattr(rec, "_delete_local", lambda items: asyncio.sleep(0, [i for i, _k, _r in items]))

    async def body():
        await ev.apply_window({"id": 6, "camera_id": 1, "type": "api", "start_time": T0.isoformat(), "end_time": None})
        late = await _chunk(1, T0 + timedelta(seconds=200))
        assert await ev.decide_held(T0 + timedelta(seconds=215)) == (1, 0)  # open: counts up to now
        assert await ev.active_camera_ids(T0 + timedelta(seconds=215)) == {1}
        # capped at max (300 s) + post (30 s)
        beyond = await _chunk(1, T0 + timedelta(seconds=400))
        assert (await ev.decide_held(T0 + timedelta(seconds=500)))[0] == 0
        assert await ev.active_camera_ids(T0 + timedelta(seconds=500)) == set()
        assert (await LocalSegment.get(id=late.id)).held is False and not await LocalSegment.exists(id=beyond.id, held=False)

    run_db(tmp_path, body)


def test_held_chunks_are_not_uploaded(tmp_path, node, monkeypatch):
    sent = []

    async def upload_segments(node_id, items):
        sent.extend(items)
        return {"accepted": len(items)}

    monkeypatch.setattr(rec, "central", SimpleNamespace(upload_segments=upload_segments))

    async def body():
        a = await _chunk(1, T0, held=True)
        b = await _chunk(2, T0, held=False)
        await rec.upload_tick()
        assert [i["id"] for i in sent] == [str(b.id)]
        assert (await LocalSegment.get(id=a.id)).uploaded is False

    run_db(tmp_path, body)


def test_catch_up_and_upload(tmp_path, node, monkeypatch):
    calls = []

    async def event_windows(node_id, since):
        calls.append(since)
        return {"items": [{"id": 9, "camera_id": 1, "type": "manual", "start_time": T0.isoformat(),
                           "end_time": T0.isoformat(), "updated_at": T0.isoformat()}],
                "now": (T0 + timedelta(seconds=5)).isoformat()}

    async def upload_events(node_id, items):
        calls.append(items)
        return {"ids": {i["key"]: 100 + n for n, i in enumerate(items)}}

    monkeypatch.setattr(ev, "central", SimpleNamespace(event_windows=event_windows, upload_events=upload_events))

    async def body():
        assert await ev.catch_up() == 1
        assert calls[0] is None
        await ev.catch_up()
        assert calls[1] == (T0 + timedelta(seconds=3)).isoformat()  # last `now` minus a little overlap
        assert (await EventWindow.get(key="c9")).central_id == 9

        w = await ev.add_event(1, "video_loss", T0)
        assert await ev.upload_events() == 1
        assert (await EventWindow.get(id=w.id)).central_id == 100
        await ev.end_event(await EventWindow.get(id=w.id), T0 + timedelta(seconds=40))
        assert await ev.upload_events() == 1  # the end goes up too
        assert calls[-1][0]["end_time"] == (T0 + timedelta(seconds=40)).isoformat()

        runtime.assignments[2]["recording"] = {"mode": "always", "events": {**EVENTS, "marking": False}}
        await ev.add_event(2, "video_loss", T0)
        assert await ev.upload_events() == 0  # marking off: keeps video, no mark

    run_db(tmp_path, body)


def test_catch_up_only_with_event_cameras(tmp_path, node, monkeypatch):
    monkeypatch.setattr(ev, "central", SimpleNamespace(event_windows=None))
    runtime.assignments = {2: _cam(2, {"mode": "always"})}

    async def body():
        assert await ev.catch_up() == 0  # never called central
        assert await KeyValue.get_value(ev.KV_EVENTS_SINCE) is None

    run_db(tmp_path, body)


def test_video_loss(tmp_path, node):
    async def body():
        await ev.watch_video_loss(1, False, T0)  # never seen up since start: no event
        assert await EventWindow.all().count() == 0
        await ev.watch_video_loss(1, True, T0)
        await ev.watch_video_loss(1, False, T0 + timedelta(seconds=10))
        await ev.watch_video_loss(1, False, T0 + timedelta(seconds=20))  # 10 s down: not yet
        assert await EventWindow.all().count() == 0
        await ev.watch_video_loss(1, False, T0 + timedelta(seconds=30))
        w = await EventWindow.get(type="video_loss")
        assert w.start_time == T0 + timedelta(seconds=10) and w.end_time is None and w.uploaded is False
        await ev.watch_video_loss(1, False, T0 + timedelta(seconds=60))
        assert await EventWindow.all().count() == 1  # one event per outage
        await ev.watch_video_loss(1, True, T0 + timedelta(seconds=90))
        assert (await EventWindow.get(id=w.id)).end_time == T0 + timedelta(seconds=90)

    run_db(tmp_path, body)


def test_status_event_standby(tmp_path, node, monkeypatch):
    sent = []

    async def list_runtime_paths():
        return {f"cam-{c}/main": {"ready": True, "tracks": ["H264"]} for c in (1, 2, 3)}

    async def stream_status(node_id, items):
        sent.extend(items)

    import app.mediamtx.utils as mtx_utils
    monkeypatch.setattr(mtx_utils, "mtx", SimpleNamespace(list_runtime_paths=list_runtime_paths))
    monkeypatch.setattr(node_services, "central", SimpleNamespace(stream_status=stream_status))
    monkeypatch.setattr(node_services, "utcnow", lambda: T0)
    runtime.mediamtx_running = True

    async def body():
        await node_services.stream_status_tick()
        by = {i["camera_id"]: i["status"] for i in sent}
        assert by == {1: "EVENT_STANDBY", 2: "RECORDING", 3: "RECORDING"}
        sent.clear()
        await ev.apply_window({"id": 1, "camera_id": 1, "type": "manual", "start_time": T0.isoformat(),
                               "end_time": T0.isoformat()})
        await node_services.stream_status_tick()
        assert {i["camera_id"]: i["status"] for i in sent}[1] == "RECORDING"  # inside the event window

    run_db(tmp_path, body)


def test_site_timezone_survives_a_restart(tmp_path, node, monkeypatch):
    """Bug found in the live run 2026-11-17: KeyValue is a JSON field, a bare "Asia/Kolkata" was refused."""
    async def assignments(node_id):
        return {"cameras": [], "site_timezone": "Asia/Kolkata"}

    monkeypatch.setattr(node_services, "central", SimpleNamespace(assignments=assignments))

    async def body():
        await node_services.refresh_assignments()
        runtime.site_timezone = "UTC"
        await node_services.load_local_state()
        assert runtime.site_timezone == "Asia/Kolkata"

    run_db(tmp_path, body)
