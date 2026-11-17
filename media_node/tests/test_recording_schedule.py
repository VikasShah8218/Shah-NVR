"""Recording schedules on the node (docs/RECORDING_SCHEDULES_PLAN.md §5): desired MediaMTX paths follow the camera's
recording setting, the switch is a PATCH of `record` only (no path delete/add), and the status says SCHEDULED_OFF."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.mediamtx import services as mtx_services
from app.node import services as node_services
from app.node.utils import runtime
from app.schedules import services as sched

OFFICE = {"mode": "schedule", "schedule_id": 1,
          "blocks": [{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "18:00", "mode": "continuous"}]}
MON_0730_UTC = datetime(2026, 11, 16, 7, 30, tzinfo=timezone.utc)
MON_0830_UTC = datetime(2026, 11, 16, 8, 30, tzinfo=timezone.utc)


def _cam(cid, recording=None, record_main=True):
    cam = {"camera_id": cid, "camera_name": f"cam {cid}", "generation": 1, "streams": [
        {"profile": "main", "path_name": f"cam-{cid}/main", "source_url": "rtsp://sim/x", "record": record_main,
         "rtsp_transport": "tcp"},
        {"profile": "sub", "path_name": f"cam-{cid}/sub", "source_url": "rtsp://sim/y", "record": False,
         "rtsp_transport": "tcp"}]}
    if recording is not None:
        cam["recording"] = recording
    return cam


@pytest.fixture
def node(monkeypatch):
    saved = (runtime.assignments, runtime.site_timezone, runtime.mediamtx_running, dict(runtime.ready_since))
    runtime.assignments = {1: _cam(1, OFFICE), 2: _cam(2), 3: _cam(3, {"mode": "never"})}
    runtime.site_timezone = "UTC"
    clock = {"now": MON_0730_UTC}
    monkeypatch.setattr(mtx_services, "utcnow", lambda: clock["now"])
    monkeypatch.setattr(mtx_services, "storage", SimpleNamespace(target=lambda: SimpleNamespace(path="D:/rec")))
    sched._last_state.clear()
    yield clock
    runtime.assignments, runtime.site_timezone, runtime.mediamtx_running, runtime.ready_since = saved


def test_desired_paths_follow_the_schedule(node):
    d = mtx_services.desired_paths()
    assert d["cam-1/main"]["record"] is False and d["cam-1/main"]["sourceOnDemand"] is False
    assert d["cam-1/main"]["recordPath"].startswith("D:/rec")
    assert d["cam-2/main"]["record"] is True  # no setting = always (older central)
    assert d["cam-3/main"]["record"] is False and d["cam-3/main"]["sourceOnDemand"] is False  # never
    assert d["cam-1/sub"] == {**d["cam-1/sub"], "record": False, "sourceOnDemand": True}  # live-only unchanged
    node["now"] = MON_0830_UTC
    assert mtx_services.desired_paths()["cam-1/main"]["record"] is True


def test_site_timezone_shifts_the_schedule(node):
    runtime.site_timezone = "+05:30"  # 07:30 UTC = 13:00 local
    assert mtx_services.desired_paths()["cam-1/main"]["record"] is True
    runtime.site_timezone = "Bad/Zone"  # unknown -> UTC
    assert mtx_services.desired_paths()["cam-1/main"]["record"] is False


def test_boundary_is_a_record_patch_not_a_restart(node, monkeypatch):
    calls = []
    paths = {}

    async def refresh():
        return None

    async def list_config_paths():
        return {k: dict(v) for k, v in paths.items()}

    async def add_path(name, conf):
        calls.append(("add", name))
        paths[name] = dict(conf)

    async def patch_path(name, conf):
        calls.append(("patch", name, conf))
        paths[name].update(conf)

    async def delete_path(name):
        calls.append(("delete", name))

    fake = SimpleNamespace(ping=lambda: _true(), list_config_paths=list_config_paths, add_path=add_path,
                           patch_path=patch_path, delete_path=delete_path)
    monkeypatch.setattr(mtx_services, "mtx", fake)
    monkeypatch.setattr(mtx_services, "refresh_assignments", refresh)

    asyncio.run(mtx_services._reconcile_tick())
    assert sorted(c[1] for c in calls if c[0] == "add") == sorted(mtx_services.desired_paths())
    calls.clear()
    node["now"] = MON_0830_UTC
    asyncio.run(mtx_services._reconcile_tick())
    assert calls == [("patch", "cam-1/main", {"record": True})]
    calls.clear()
    node["now"] = datetime(2026, 11, 16, 18, 0, tzinfo=timezone.utc)
    asyncio.run(mtx_services._reconcile_tick())
    assert calls == [("patch", "cam-1/main", {"record": False})]


async def _true():
    return True


def test_transition_log(node, caplog):
    caplog.set_level("INFO", logger="node.schedules")
    sched.log_transitions(MON_0730_UTC)
    text = caplog.text
    assert "Recording OFF for camera 1 (cam 1, schedule) until Mon 08:00" in text
    assert "Recording ON for camera 2" in text and "Recording OFF for camera 3 (cam 3, never)" in text
    caplog.clear()
    sched.log_transitions(MON_0730_UTC)
    assert caplog.text == ""  # only changes are logged
    sched.log_transitions(MON_0830_UTC)
    assert "Recording ON for camera 1 (cam 1, schedule) until Mon 18:00" in caplog.text


def test_status_reports_scheduled_off(node, monkeypatch):
    sent = []

    async def list_runtime_paths():
        return {n: {"ready": True, "tracks": ["H264"], "bytesReceived": 10} for n in mtx_services.desired_paths()}

    async def stream_status(node_id, items):
        sent.extend(items)

    import app.mediamtx.utils as mtx_utils
    monkeypatch.setattr(mtx_utils, "mtx", SimpleNamespace(list_runtime_paths=list_runtime_paths))
    monkeypatch.setattr(node_services, "central", SimpleNamespace(stream_status=stream_status))
    monkeypatch.setattr(node_services, "utcnow", lambda: MON_0730_UTC)
    monkeypatch.setattr(runtime, "node_id", 5)
    runtime.mediamtx_running = True
    asyncio.run(node_services.stream_status_tick())
    by = {(i["camera_id"], i["profile"]): i for i in sent}
    assert by[(1, "main")]["status"] == "SCHEDULED_OFF" and "until Mon 08:00" in by[(1, "main")]["detail"]
    assert by[(3, "main")]["status"] == "SCHEDULED_OFF" and by[(3, "main")]["detail"] == "recording mode: never"
    assert by[(2, "main")]["status"] == "RECORDING"  # just became ready: within the grace window
    assert by[(1, "sub")]["status"] == "STREAMING"


def test_first_chunk_grace_restarts_when_the_schedule_turns_on(node, monkeypatch):
    """Live run 2026-11-16: the stream had been up for minutes, so right after 08:00 it showed NOT_RECORDING."""
    from datetime import timedelta

    sent = []

    async def list_runtime_paths():
        return {n: {"ready": True, "tracks": ["H264"]} for n in mtx_services.desired_paths()}

    async def stream_status(node_id, items):
        sent.extend(items)

    import app.mediamtx.utils as mtx_utils
    monkeypatch.setattr(mtx_utils, "mtx", SimpleNamespace(list_runtime_paths=list_runtime_paths))
    monkeypatch.setattr(node_services, "central", SimpleNamespace(stream_status=stream_status))
    monkeypatch.setattr(runtime, "node_id", 5)
    runtime.mediamtx_running = True
    runtime.ready_since["cam-1/main"] = MON_0730_UTC - timedelta(hours=1)
    clock = {"now": MON_0730_UTC + timedelta(minutes=29, seconds=55)}  # 07:59:55, still off
    monkeypatch.setattr(node_services, "utcnow", lambda: clock["now"])
    asyncio.run(node_services.stream_status_tick())
    clock["now"] = MON_0830_UTC - timedelta(minutes=29, seconds=40)  # 08:00:20, on, no chunk yet
    sent.clear()
    asyncio.run(node_services.stream_status_tick())
    assert {(i["camera_id"], i["profile"]): i["status"] for i in sent}[(1, "main")] == "RECORDING"


def test_format_change():
    now = MON_0730_UTC
    assert sched.format_change(MON_0830_UTC, now) == "Mon 08:30"
    assert sched.format_change(MON_0830_UTC.replace(day=23), now) == "Mon 23 Nov 08:30"
