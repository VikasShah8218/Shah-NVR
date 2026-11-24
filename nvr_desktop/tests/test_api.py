from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.core.api import node as node_api
from app.core.api.central import CentralApi
from app.core.api.errors import ApiError, error_message

BASE = "http://central.test"

CAMERA = {
    "id": 1, "name": "Gate", "description": None, "username": "admin", "has_password": True, "enabled": True,
    "retention_days": 7, "created_at": "2026-10-14T00:00:00Z", "updated_at": "2026-10-14T00:00:00Z",
    "streams": [{"id": 1, "profile": "main", "source_url": "rtsp://x/main", "record": True, "rtsp_transport": "tcp",
                 "status": "RECORDING", "bytes_received": 10}],
    "assignment": {"node_id": 2, "node_name": "node-2", "generation": 3, "lease_expires_at": None},
}


@respx.mock
def test_cameras_are_parsed_into_models():
    route = respx.get(f"{BASE}/api/v1/cameras").mock(return_value=httpx.Response(
        200, json={"items": [CAMERA], "total": 41, "limit": 25, "offset": 25}))
    cameras, total = CentralApi(BASE).cameras(q=" gate ", enabled=True, limit=25, offset=25)
    assert total == 41 and cameras[0].name == "Gate"
    assert dict(route.calls.last.request.url.params) == {"q": "gate", "enabled": "true", "limit": "25", "offset": "25"}
    assert cameras[0].assignment.node_name == "node-2"
    qml = cameras[0].to_qml()  # JSON-safe dict for QML
    assert qml["created_at"].startswith("2026-10-14T00:00:00") and qml["streams"][0]["status"] == "RECORDING"


@respx.mock
def test_fastapi_errors_become_readable_messages():
    respx.delete(f"{BASE}/api/v1/cameras/1").mock(
        return_value=httpx.Response(409, json={"detail": "Camera has recordings; disable it instead"}))
    with pytest.raises(ApiError) as err:
        CentralApi(BASE).delete_camera(1)
    assert err.value.status == 409
    assert str(err.value) == "Camera has recordings; disable it instead"


def test_validation_error_detail_list():
    response = httpx.Response(422, json={"detail": [{"loc": ["body", "name"], "msg": "Field required"}]})
    assert error_message(response) == "name: Field required"
    assert error_message(httpx.Response(500, text="oops")) == "Request failed (HTTP 500)"


@respx.mock
def test_unreachable_central():
    respx.get(f"{BASE}/api/v1/nodes").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ApiError) as err:
        CentralApi(BASE).nodes()
    assert err.value.status == 0 and "unreachable" in str(err.value)


@respx.mock
def test_requests_send_expected_bodies_and_params():
    move = respx.put(f"{BASE}/api/v1/assignments/1").mock(return_value=httpx.Response(200, json={
        "camera_id": 1, "camera_name": "Gate", "node_id": 3, "node_name": "node-3", "generation": 4,
        "lease_expires_at": None, "reason": "manual", "updated_at": "2026-10-14T00:00:00Z"}))
    delete = respx.delete(f"{BASE}/api/v1/nodes/5").mock(return_value=httpx.Response(204))
    api = CentralApi(BASE)
    assert api.move_camera(1, 3).node_name == "node-3"
    assert move.calls.last.request.content == b'{"node_id":3}'
    api.delete_node(5, force=True)
    assert delete.calls.last.request.url.params["force"] == "true"
    with pytest.raises(ValueError):
        api.node_action(1, "explode")


def test_playlist_url():
    start = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc)
    url = CentralApi(BASE + "/").playlist_url(7, "main", start, end)
    assert url.startswith(f"{BASE}/api/v1/playback/7/index.m3u8?profile=main&start=2026-10-14T00%3A00%3A00%2B00%3A00")


@respx.mock
def test_node_download_streams_to_disk(tmp_path):
    url = node_api.media_file_url("http://node.test/", "seg-1")
    assert url == "http://node.test/api/v1/media/seg-1/file.mp4"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"x" * 200_000, headers={"content-length": "200000"}))
    progress = []
    target = node_api.download(url, tmp_path / "chunk.mp4", lambda done, total: progress.append((done, total)))
    assert target.stat().st_size == 200_000
    assert progress[-1] == (200_000, 200_000)


@respx.mock
def test_node_download_error_message(tmp_path):
    url = node_api.media_file_url("http://node.test", "gone")
    respx.get(url).mock(return_value=httpx.Response(404, json={"detail": "Segment file missing"}))
    with pytest.raises(ApiError, match="Segment file missing"):
        node_api.download(url, tmp_path / "x.mp4")


@respx.mock
def test_schedules_api():
    sched = {"id": 3, "name": "Office", "description": None, "camera_count": 2, "recording_now": False,
             "next_change": "2026-11-17T08:00:00+05:30",
             "blocks": [{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "18:00", "mode": "continuous"}],
             "created_at": "2026-11-16T00:00:00Z", "updated_at": "2026-11-16T00:00:00Z"}
    respx.get(f"{BASE}/api/v1/schedules").mock(return_value=httpx.Response(200, json=[sched]))
    put = respx.put(f"{BASE}/api/v1/schedules/3").mock(return_value=httpx.Response(200, json=sched))
    apply = respx.post(f"{BASE}/api/v1/schedules/apply").mock(return_value=httpx.Response(200, json={"updated": 5}))
    respx.get(f"{BASE}/api/v1/schedules/site-time").mock(return_value=httpx.Response(
        200, json={"timezone": "Asia/Kolkata", "now": "2026-11-16T19:12:20+05:30"}))
    api = CentralApi(BASE)
    got = api.schedules()[0].to_qml()
    assert got["next_change"] == "2026-11-17T08:00:00+05:30" and got["blocks"][0]["days"] == [0, 1, 2, 3, 4]
    api.update_schedule(3, {"name": "Office 2"})
    assert put.calls.last.request.read() == b'{"name":"Office 2"}'
    assert api.apply_schedule("never", schedule_id=3, camera_ids=[2, 1, 2]) == 5
    import json
    assert json.loads(apply.calls.last.request.read()) == {"mode": "never", "schedule_id": None, "camera_ids": [1, 2],
                                                           "group_id": None, "include_subgroups": True}
    assert api.site_time().timezone == "Asia/Kolkata"
    cam = api_camera_defaults()
    assert (cam.recording_mode, cam.recording_now) == ("always", True)


@respx.mock
def test_events_api():
    import json
    ev = {"id": 7, "camera_id": 1, "camera_name": "Gate", "type": "video_loss", "source": "node:2",
          "start_time": "2026-11-18T10:00:00Z", "end_time": None, "label": None, "data": None,
          "pre_seconds": 10, "post_seconds": 30, "created_at": "2026-11-18T10:00:00Z",
          "updated_at": "2026-11-18T10:00:00Z"}
    listed = respx.get(f"{BASE}/api/v1/events").mock(return_value=httpx.Response(
        200, json={"items": [ev], "total": 1, "limit": 25, "offset": 25}))
    created = respx.post(f"{BASE}/api/v1/cameras/1/events").mock(return_value=httpx.Response(
        201, json={**ev, "id": 8, "type": "manual", "merged": True}))
    ended = respx.post(f"{BASE}/api/v1/events/7/end").mock(return_value=httpx.Response(
        200, json={**ev, "end_time": "2026-11-18T10:05:00Z"}))
    deleted = respx.delete(f"{BASE}/api/v1/events/7").mock(return_value=httpx.Response(204))
    api = CentralApi(BASE)
    start = datetime(2026, 11, 18, tzinfo=timezone.utc)
    rows, total = api.events(camera_id=1, types=["manual", "video_loss"], start=start, order="asc", limit=25,
                             offset=25)
    assert total == 1 and rows[0].end_time is None and rows[0].to_qml()["type"] == "video_loss"
    assert dict(listed.calls.last.request.url.params) == {
        "camera_id": "1", "type": "manual,video_loss", "start": "2026-11-18T00:00:00+00:00", "order": "asc",
        "limit": "25", "offset": "25"}
    assert api.create_event(1, {"type": "manual"}).merged
    assert json.loads(created.calls.last.request.read()) == {"type": "manual"}
    assert api.end_event(7).end_time is not None and ended.called
    api.delete_event(7)
    assert deleted.called


@respx.mock
def test_apply_with_event_settings_and_camera_event_fields():
    import json
    from app.core.api.models import Camera, RecordingSchedule
    apply = respx.post(f"{BASE}/api/v1/schedules/apply").mock(return_value=httpx.Response(200, json={"updated": 2}))
    api = CentralApi(BASE)
    assert api.apply_schedule("event", group_id=4, events={"pre": 5, "post": 60, "marking": False}) == 2
    assert json.loads(apply.calls.last.request.read()) == {
        "mode": "event", "schedule_id": None, "camera_ids": [], "group_id": 4, "include_subgroups": True,
        "event_pre_seconds": 5, "event_post_seconds": 60, "event_marking": False}
    old = Camera.model_validate(CAMERA)  # an older central: defaults
    assert (old.recording_state, old.event_pre_seconds, old.event_post_seconds, old.event_marking) == (None, 10, 30, True)
    cam = Camera.model_validate({**CAMERA, "recording_mode": "event", "recording_state": "event", "event_marking": False})
    assert cam.recording_state == "event" and not cam.event_marking
    sched = RecordingSchedule.model_validate({"id": 1, "name": "x", "state_now": "event",
                                              "blocks": [{"days": [0], "start": "18:00", "end": "08:00", "mode": "event"}]})
    assert sched.state_now == "event" and sched.blocks[0].mode == "event"


def api_camera_defaults():
    from app.core.api.models import Camera
    return Camera.model_validate(CAMERA)  # an older central without recording fields


@respx.mock
def test_camera_events_fields_probe_and_apply():
    respx.get(f"{BASE}/api/v1/cameras/1").mock(return_value=httpx.Response(200, json={
        **CAMERA, "onvif_events_enabled": True, "onvif_event_kinds": ["motion"],
        "onvif_events_status": {"state": "ok", "offered": ["motion", "tamper"]}}))
    cam = CentralApi(BASE).camera(1)
    assert cam.onvif_events_enabled and cam.onvif_event_kinds == ["motion"] and cam.onvif_events_status["state"] == "ok"
    old = CentralApi(BASE)  # an older central without the fields still parses
    respx.get(f"{BASE}/api/v1/cameras/2").mock(return_value=httpx.Response(200, json={**CAMERA, "id": 2}))
    assert old.camera(2).onvif_events_enabled is False and old.camera(2).onvif_event_kinds is None

    respx.post(f"{BASE}/api/v1/onvif/cameras/1/events/probe").mock(return_value=httpx.Response(200, json={
        "camera_id": 1, "offered": ["motion"], "topics": {"motion": "tns1:VideoSource/MotionAlarm"},
        "all_topics": ["tns1:VideoSource/MotionAlarm", "tns1:Device/Trigger/DigitalInput"]}))
    probe = CentralApi(BASE).probe_camera_events(1)
    assert probe.offered == ["motion"] and len(probe.all_topics) == 2

    route = respx.post(f"{BASE}/api/v1/onvif/events/apply").mock(return_value=httpx.Response(200, json={"updated": 5}))
    body = {"enabled": True, "kinds": None, "group_id": 3, "include_subgroups": True}
    assert CentralApi(BASE).apply_camera_events(body) == 5
    import json
    assert json.loads(route.calls.last.request.content) == body
