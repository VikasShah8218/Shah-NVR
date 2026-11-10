"""Paged lists (docs/PAGINATION_PLAN.md): cameras (filters, options, ids), assignments, exports, backfill jobs,
bookmarks and the server-side camera alerts. Runs the real app on an in-memory SQLite database."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

STREAM = [{"profile": "main", "source_url": "rtsp://1.2.3.4/x", "record": True}]


def _client():
    import main

    return TestClient(main.app)


def _seed(client, names):
    return [client.post("/api/v1/cameras", json={"name": n, "streams": STREAM}).json()["id"] for n in names]


def test_camera_pages_are_stable_and_counted():
    with _client() as client:
        _seed(client, [f"Cam {i:02d}" for i in range(12)] + ["Gate"])
        first = client.get("/api/v1/cameras", params={"limit": 5}).json()
        assert first["total"] == 13 and first["limit"] == 5 and first["offset"] == 0
        assert [c["name"] for c in first["items"]] == [f"Cam {i:02d}" for i in range(5)]
        last = client.get("/api/v1/cameras", params={"limit": 5, "offset": 10}).json()
        assert [c["name"] for c in last["items"]] == ["Cam 10", "Cam 11", "Gate"]
        assert last["items"][0]["streams"][0]["profile"] == "main"  # full camera rows (batched)
        assert client.get("/api/v1/cameras", params={"limit": 201}).status_code == 422


def test_camera_search_filters_and_ids():
    with _client() as client:
        gate, yard, door = _seed(client, ["North Gate", "Yard", "Back door"])
        client.patch(f"/api/v1/cameras/{yard}", json={"enabled": False})
        names = lambda **p: [c["name"] for c in client.get("/api/v1/cameras", params=p).json()["items"]]
        assert names(q="gate") == ["North Gate"]
        assert names(q=str(door)) == ["Back door"]  # exact id
        assert names(enabled=False) == ["Yard"]
        assert names(sort="id") == ["North Gate", "Yard", "Back door"]
        assert names(ids=f"{door},{gate}") == ["Back door", "North Gate"]
        assert names(status="DISABLED") == ["Yard"]
        assert client.get("/api/v1/cameras", params={"ids": "1,x"}).status_code == 422


def test_camera_options_are_small_rows():
    with _client() as client:
        (gate,) = _seed(client, ["Gate"])
        client.post(f"/api/v1/cameras/{gate}/streams", json={"profile": "sub", "source_url": "rtsp://1.2.3.4/y"})
        page = client.get("/api/v1/cameras/options", params={"q": "ga"}).json()
        assert page["total"] == 1
        assert page["items"] == [{"id": gate, "name": "Gate", "enabled": True, "has_ptz": False,
                                  "profiles": ["main", "sub"], "status": "UNASSIGNED", "node_id": None}]


def test_alerts_are_paged_danger_first_with_counts():
    with _client() as client:
        ids = _seed(client, ["B cam", "A cam", "C cam"])  # no nodes: all three are unassigned (danger)
        client.patch(f"/api/v1/cameras/{ids[2]}", json={"enabled": False})  # disabled: no alert
        page = client.get("/api/v1/cluster/alerts", params={"limit": 1}).json()
        assert page["total"] == 2 and page["counts"] == {"danger": 2, "warning": 0}
        assert page["items"][0]["title"] == "A cam is not assigned to any node"
        assert page["items"][0]["kind"] == "unassigned" and page["items"][0]["level"] == "danger"
        assert client.get("/api/v1/cluster/alerts", params={"level": "warning"}).json()["items"] == []
        assert client.get("/api/v1/cluster/health").json()["record_streams"] == 2  # disabled camera not counted


async def _assigned_camera_alerts():
    """Stream, ONVIF and clock rules need an assigned camera: build one directly in the database."""
    from app.assignments.models import CameraAssignment
    from app.cameras.models import Camera, CameraStream, StreamStatus
    from app.cluster.alerts import camera_alerts
    from app.nodes.models import MediaNode

    node = await MediaNode.create(name="n1", api_url="http://n1:7100", media_host="n1")
    cams = {}
    for name, status, reachable, offset in (("Ok", StreamStatus.RECORDING, True, 2.0),
                                            ("Down", StreamStatus.NOT_RECORDING, None, None),
                                            ("Conn", StreamStatus.CONNECTING, False, 99.0),
                                            ("Skew", StreamStatus.RECORDING, True, -125.0)):
        cam = await Camera.create(name=name, onvif_reachable=reachable, clock_offset_seconds=offset,
                                  onvif_checked_at=datetime.now(timezone.utc) - timedelta(minutes=3))
        await CameraStream.create(camera=cam, profile="main", source_url="rtsp://x", status=status)
        await CameraAssignment.create(camera=cam, node=node, generation=1)
        cams[name] = cam
    return [(a.level, a.kind, a.title) for a in await camera_alerts()]


def test_stream_onvif_and_clock_rules():
    import asyncio

    from tortoise import Tortoise

    from database.config import APP_MODELS

    async def go():
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": APP_MODELS})
        await Tortoise.generate_schemas()
        try:
            return await _assigned_camera_alerts()
        finally:
            await Tortoise.close_connections()

    assert asyncio.run(go()) == [
        ("danger", "stream", "Down (main) is not recording"),
        ("warning", "onvif", "Conn: ONVIF not answering"),  # unreachable wins over the clock
        ("warning", "stream", "Conn (main) is connecting"),
        ("warning", "clock", "Skew: camera clock −2 min 5 s off"),
    ]


def test_other_lists_return_pages():
    with _client() as client:
        (cam,) = _seed(client, ["Gate"])
        for url in ("/api/v1/assignments", f"/api/v1/assignments/{cam}/history", "/api/v1/exports",
                    f"/api/v1/cameras/{cam}/backfill/jobs", "/api/v1/bookmarks"):
            body = client.get(url, params={"limit": 10, "offset": 0}).json()
            assert set(body) == {"items", "total", "limit", "offset"}, url
            assert body["total"] == len(body["items"]) == 0 or url.endswith("assignments"), url
        start = datetime(2026, 11, 10, tzinfo=timezone.utc)
        for i in range(3):
            client.post("/api/v1/bookmarks", json={"camera_id": cam, "note": f"n{i}",
                                                    "start_time": (start + timedelta(minutes=i)).isoformat()})
        page = client.get("/api/v1/bookmarks", params={"order": "desc", "limit": 2, "offset": 2}).json()
        assert page["total"] == 3 and [b["note"] for b in page["items"]] == ["n0"]
