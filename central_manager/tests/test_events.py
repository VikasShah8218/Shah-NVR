"""Events API (docs/EVENT_RECORDING_PLAN.md §4, §9): event recording settings on cameras, mark / merge / end / list,
node upload + catch-up, the node push, upkeep (auto close, retention), Event-mode status. Real app on in-memory SQLite."""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

STREAM = [{"profile": "main", "source_url": "rtsp://1.2.3.4/x", "record": True}]


def _client():
    import main

    return TestClient(main.app)


def _camera(c, name, **extra):
    r = c.post("/api/v1/cameras", json={"name": name, "streams": STREAM, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _node(c, name="n1"):
    return c.post("/internal/v1/nodes/register",
                  json={"name": name, "api_url": f"http://{name}:7100", "media_host": name}).json()["node_id"]


def _assign(c, cam_id, node_id):
    r = c.put(f"/api/v1/assignments/{cam_id}", json={"node_id": node_id})
    assert r.status_code == 200, r.text


def test_camera_event_settings_and_payload():
    with _client() as c:
        cam = _camera(c, "Gate", recording_mode="event", event_pre_seconds=5, event_post_seconds=60)
        assert (cam["recording_mode"], cam["recording_state"], cam["recording_now"]) == ("event", "event", False)
        assert (cam["event_pre_seconds"], cam["event_post_seconds"], cam["event_marking"]) == (5, 60, True)
        plain = _camera(c, "Plain")
        assert plain["recording_state"] == "continuous" and plain["event_pre_seconds"] == 10
        assert c.post("/api/v1/cameras", json={"name": "x", "streams": STREAM, "event_pre_seconds": 61}).status_code == 422
        r = c.patch(f"/api/v1/cameras/{cam['id']}", json={"event_marking": False, "event_pre_seconds": None})
        assert r.json()["event_marking"] is False and r.json()["event_pre_seconds"] == 5  # null = unchanged

        node = _node(c)
        _assign(c, cam["id"], node)
        rec = {x["camera_id"]: x["recording"] for x in c.get(f"/internal/v1/nodes/{node}/assignments").json()["cameras"]}
        assert rec[cam["id"]] == {"mode": "event", "events": {"pre": 5, "post": 60, "marking": False, "max": 300}}

        # bulk apply sets the mode and the event seconds
        r = c.post("/api/v1/schedules/apply", json={"mode": "event", "camera_ids": [plain["id"]], "event_post_seconds": 90})
        assert r.json() == {"updated": 1}
        p = c.get(f"/api/v1/cameras/{plain['id']}").json()
        assert (p["recording_mode"], p["event_post_seconds"], p["event_pre_seconds"]) == ("event", 90, 10)

        # an event block in a schedule
        s = c.post("/api/v1/schedules", json={"name": "Nights", "blocks": [
            {"days": list(range(7)), "start": "00:00", "end": "00:00", "mode": "event"}]}).json()
        assert s["state_now"] == "event" and s["recording_now"] is False


def test_mark_merge_end_list():
    with _client() as c:
        cam = _camera(c, "Door", event_post_seconds=30)
        other = _camera(c, "Yard")
        t0 = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)
        url = f"/api/v1/cameras/{cam['id']}/events"

        a = c.post(url, json={"start_time": t0.isoformat(), "label": "Door forced"})
        assert a.status_code == 201, a.text
        a = a.json()
        assert a["type"] == "manual" and a["source"] == "user:local" and a["merged"] is False
        assert a["start_time"] == a["end_time"]  # a moment
        assert (a["pre_seconds"], a["post_seconds"]) == (10, 30)

        # 20 s later, same type and label: extends the first one
        b = c.post(url, json={"start_time": (t0 + timedelta(seconds=20)).isoformat(), "label": "Door forced"}).json()
        assert b["id"] == a["id"] and b["merged"] is True
        assert b["end_time"].startswith("2026-11-17T10:00:20")
        # another label = a new event; 2 minutes later = a new event
        assert c.post(url, json={"start_time": (t0 + timedelta(seconds=25)).isoformat(), "label": "Other"}).json()["id"] != a["id"]
        late = c.post(url, json={"start_time": (t0 + timedelta(minutes=2)).isoformat(), "label": "Door forced"}).json()
        assert late["id"] != a["id"]

        # an ongoing API event, ended later
        ongoing = c.post(f"/api/v1/cameras/{other['id']}/events", json={"type": "api", "ongoing": True, "data": {"door": 3}}).json()
        assert ongoing["end_time"] is None and ongoing["source"] == "api:local" and ongoing["data"] == {"door": 3}
        ended = c.post(f"/api/v1/events/{ongoing['id']}/end").json()
        assert ended["end_time"] is not None
        assert c.post(f"/api/v1/cameras/{other['id']}/events", json={"ongoing": True, "duration_seconds": 5}).status_code == 422
        assert c.post("/api/v1/cameras/999/events", json={}).status_code == 404

        page = c.get("/api/v1/events", params={"camera_id": cam["id"]}).json()
        assert page["total"] == 3 and page["items"][0]["id"] == late["id"]  # newest first
        page = c.get("/api/v1/events", params={"camera_id": cam["id"], "order": "asc",
                                                "start": (t0 + timedelta(seconds=21)).isoformat(),
                                                "end": (t0 + timedelta(minutes=1)).isoformat()}).json()
        assert [e["label"] for e in page["items"]] == ["Other"]
        assert c.get("/api/v1/events", params={"type": "api,video_loss"}).json()["total"] == 1

        assert c.delete(f"/api/v1/events/{late['id']}").status_code == 204
        assert c.get(f"/api/v1/events/{late['id']}").status_code == 404


def test_node_upload_catch_up_and_push(monkeypatch):
    from app.events import services

    pushed = []

    async def fake_call(node, path, json=None, **kw):
        pushed.append((node.name, path, json))
        return {}

    monkeypatch.setattr(services, "call_node", fake_call)
    with _client() as c:
        node = _node(c)
        cam = _camera(c, "Gate", recording_mode="event")
        stranger = _camera(c, "Elsewhere")
        _assign(c, cam["id"], node)

        since = c.get(f"/internal/v1/nodes/{node}/events").json()
        assert since["items"] == []

        e = c.post(f"/api/v1/cameras/{cam['id']}/events", json={}).json()
        assert pushed and pushed[-1][1] == "/api/v1/events" and pushed[-1][2]["id"] == e["id"]
        # catch-up: everything changed since the last poll, for this node's cameras only
        c.post(f"/api/v1/cameras/{stranger['id']}/events", json={})
        items = c.get(f"/internal/v1/nodes/{node}/events", params={"since": since["now"]}).json()["items"]
        assert [i["id"] for i in items] == [e["id"]]

        t0 = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
        body = {"items": [{"key": "n1-1", "camera_id": cam["id"], "type": "video_loss", "start_time": t0.isoformat()},
                          {"key": "n1-2", "camera_id": stranger["id"], "type": "video_loss", "start_time": t0.isoformat()}]}
        ids = c.post(f"/internal/v1/nodes/{node}/events", json=body).json()["ids"]
        assert list(ids) == ["n1-1"]  # the camera this node does not own is skipped
        body["items"][0]["end_time"] = (t0 + timedelta(minutes=3)).isoformat()
        again = c.post(f"/internal/v1/nodes/{node}/events", json=body).json()["ids"]
        assert again == ids  # idempotent: same event, now closed
        ev = c.get(f"/api/v1/events/{ids['n1-1']}").json()
        assert ev["source"] == "node:n1" and ev["end_time"].startswith("2026-11-17T09:03")


def test_upkeep_closes_and_prunes():
    from app.events.models import Event
    from app.events.services import event_upkeep_tick

    with _client() as c:
        cam = _camera(c, "Gate")
        now = datetime.now(timezone.utc)
        open_api = c.post(f"/api/v1/cameras/{cam['id']}/events",
                          json={"type": "api", "ongoing": True, "start_time": (now - timedelta(minutes=10)).isoformat()}).json()
        old = c.post(f"/api/v1/cameras/{cam['id']}/events", json={"start_time": (now - timedelta(days=100)).isoformat(),
                                                                   "label": "old"}).json()
        fresh_open = c.post(f"/api/v1/cameras/{cam['id']}/events", json={"type": "api", "ongoing": True, "label": "x"}).json()

        async def run():
            await event_upkeep_tick()
            return {e.id: e for e in await Event.all()}

        rows = c.portal.call(run)
        assert old["id"] not in rows
        assert rows[open_api["id"]].end_time is not None  # closed after EVENT_MAX_SECONDS
        assert rows[fresh_open["id"]].end_time is None


def test_event_standby_is_not_an_alert():
    with _client() as c:
        node = _node(c)
        cam = _camera(c, "Gate", recording_mode="event")
        _assign(c, cam["id"], node)
        c.post(f"/internal/v1/nodes/{node}/stream-status",
               json={"items": [{"camera_id": cam["id"], "profile": "main", "status": "EVENT_STANDBY"}]})
        assert c.get(f"/api/v1/cameras/{cam['id']}").json()["streams"][0]["status"] == "EVENT_STANDBY"
        alerts = c.get("/api/v1/cluster/alerts").json()
        assert not [a for a in alerts["items"] if a["camera_id"] == cam["id"]]
