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
    respx.get(f"{BASE}/api/v1/cameras").mock(return_value=httpx.Response(200, json=[CAMERA]))
    cameras = CentralApi(BASE).cameras()
    assert cameras[0].name == "Gate"
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
