"""Recording schedules API (docs/RECORDING_SCHEDULES_PLAN.md §4, §9): CRUD + validation, camera recording fields,
bulk apply to a group, the node's assignments payload, and alerts that ignore cameras off by schedule.
Real app on in-memory SQLite."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

STREAM = [{"profile": "main", "source_url": "rtsp://1.2.3.4/x", "record": True}]
ALL_WEEK = list(range(7))


def _client():
    import main

    return TestClient(main.app)


def _schedule(c, name="Office", blocks=None, expect=201):
    blocks = blocks if blocks is not None else [{"days": [0, 1, 2, 3, 4], "start": "08:00", "end": "18:00"}]
    r = c.post("/api/v1/schedules", json={"name": name, "blocks": blocks})
    assert r.status_code == expect, r.text
    return r.json()


def _camera(c, name, **extra):
    r = c.post("/api/v1/cameras", json={"name": name, "streams": STREAM, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _never_now_blocks():
    """A block that is off right now (the 2 hours on the other side of the week)."""
    now = datetime.now().astimezone()
    other = (now + timedelta(days=3)).weekday()
    return [{"days": [other], "start": "00:00", "end": "02:00"}]


def test_crud_and_validation():
    with _client() as c:
        s = _schedule(c)
        assert s["camera_count"] == 0 and s["blocks"][0]["mode"] == "continuous" and s["blocks"][0]["days"] == [0, 1, 2, 3, 4]
        _schedule(c, "Office", expect=409)
        _schedule(c, "  ", expect=422)
        for bad in ({"days": [7], "start": "08:00", "end": "18:00"}, {"days": [1, 1], "start": "08:00", "end": "18:00"},
                    {"days": [], "start": "08:00", "end": "18:00"}, {"days": [1], "start": "8:00", "end": "18:00"},
                    {"days": [1], "start": "24:00", "end": "18:00"}, {"days": [1], "start": "08:00", "end": "24:30"},
                    {"days": [1], "start": "08:00", "end": "18:00", "mode": "motion"}):
            _schedule(c, "Bad", [bad], expect=422)
        _schedule(c, "Many", [{"days": [1], "start": "08:00", "end": "09:00"}] * 51, expect=422)

        nights = _schedule(c, "Nights", [{"days": ALL_WEEK, "start": "18:00", "end": "08:00"}])
        assert [x["name"] for x in c.get("/api/v1/schedules").json()] == ["Nights", "Office"]
        r = c.put(f"/api/v1/schedules/{nights['id']}", json={"name": "Office"})
        assert r.status_code == 409
        r = c.put(f"/api/v1/schedules/{nights['id']}", json={"name": "Night", "description": "18-08"})
        assert r.status_code == 200 and r.json()["name"] == "Night" and r.json()["blocks"] == nights["blocks"]
        assert c.get("/api/v1/schedules/999").status_code == 404
        assert c.delete(f"/api/v1/schedules/{nights['id']}").status_code == 204
        assert c.get(f"/api/v1/schedules/{nights['id']}").status_code == 404


def test_preview_and_site_time():
    with _client() as c:
        s = _schedule(c, "Always", [{"days": ALL_WEEK, "start": "00:00", "end": "24:00"}])
        assert s["recording_now"] is True and s["next_change"] is None
        p = c.get(f"/api/v1/schedules/{s['id']}/preview", params={"days": 2}).json()
        assert [x["mode"] for x in p["spans"]] == ["continuous"]
        office = _schedule(c)
        spans = c.get(f"/api/v1/schedules/{office['id']}/preview", params={"from": "2026-11-16T00:00:00", "days": 7}).json()["spans"]
        on = [(x["start"][:16], x["end"][:16]) for x in spans if x["mode"] == "continuous"]
        assert on[0] == ("2026-11-16T08:00", "2026-11-16T18:00") and len(on) == 5
        t = c.get("/api/v1/schedules/site-time").json()
        assert t["timezone"] and t["now"]


def test_camera_recording_fields():
    with _client() as c:
        s = _schedule(c, "Off now", _never_now_blocks())
        cam = _camera(c, "Gate")
        assert (cam["recording_mode"], cam["recording_schedule_id"], cam["recording_now"]) == ("always", None, True)
        assert c.patch(f"/api/v1/cameras/{cam['id']}", json={"recording_mode": "schedule"}).status_code == 422
        assert c.patch(f"/api/v1/cameras/{cam['id']}", json={"recording_mode": "schedule", "recording_schedule_id": 999}).status_code == 422
        r = c.patch(f"/api/v1/cameras/{cam['id']}", json={"recording_mode": "schedule", "recording_schedule_id": s["id"]}).json()
        assert (r["recording_mode"], r["recording_schedule_name"], r["recording_now"]) == ("schedule", "Off now", False)
        assert r["recording_next_change"] is not None
        assert c.get(f"/api/v1/schedules/{s['id']}").json()["camera_count"] == 1
        assert c.delete(f"/api/v1/schedules/{s['id']}").status_code == 409
        r = c.patch(f"/api/v1/cameras/{cam['id']}", json={"name": "Gate 1"}).json()  # untouched
        assert r["recording_schedule_id"] == s["id"]
        r = c.patch(f"/api/v1/cameras/{cam['id']}", json={"recording_mode": "never"}).json()
        assert (r["recording_mode"], r["recording_schedule_id"], r["recording_now"]) == ("never", None, False)
        assert c.delete(f"/api/v1/schedules/{s['id']}").status_code == 204
        made = _camera(c, "Yard", recording_mode="never")
        assert made["recording_mode"] == "never"
        assert c.post("/api/v1/cameras", json={"name": "X", "streams": STREAM, "recording_mode": "schedule"}).status_code == 422


def test_apply_to_group_with_subgroups():
    with _client() as c:
        s = _schedule(c)
        top = c.post("/api/v1/groups", json={"name": "Site"}).json()
        sub = c.post("/api/v1/groups", json={"name": "Gate", "parent_id": top["id"]}).json()
        a = _camera(c, "A", group_id=top["id"])
        b = _camera(c, "B", group_id=sub["id"])
        loose = _camera(c, "Loose")
        r = c.post("/api/v1/schedules/apply", json={"mode": "schedule", "schedule_id": s["id"], "group_id": top["id"],
                                                     "include_subgroups": False})
        assert r.json() == {"updated": 1}
        r = c.post("/api/v1/schedules/apply", json={"mode": "schedule", "schedule_id": s["id"], "group_id": top["id"],
                                                     "camera_ids": [loose["id"]]})
        assert r.json() == {"updated": 3}
        assert c.get(f"/api/v1/schedules/{s['id']}").json()["camera_count"] == 3
        assert c.post("/api/v1/schedules/apply", json={"mode": "always", "camera_ids": [b["id"]]}).json() == {"updated": 1}
        got = {x["name"]: (x["recording_mode"], x["recording_schedule_id"]) for x in c.get("/api/v1/cameras").json()["items"]}
        assert got == {"A": ("schedule", s["id"]), "B": ("always", None), "Loose": ("schedule", s["id"])}
        for bad in ({"mode": "schedule", "camera_ids": [a["id"]]}, {"mode": "never", "schedule_id": s["id"], "camera_ids": [1]},
                    {"mode": "never"}):
            assert c.post("/api/v1/schedules/apply", json=bad).status_code == 422
        assert c.post("/api/v1/schedules/apply", json={"mode": "schedule", "schedule_id": 999, "camera_ids": [1]}).status_code == 404


def test_assignments_payload_and_alerts():
    with _client() as c:
        node = c.post("/internal/v1/nodes/register", json={"name": "n1", "api_url": "http://n1:7100", "media_host": "n1"}).json()
        off = _schedule(c, "Off now", _never_now_blocks())
        cam = _camera(c, "Gate", recording_mode="schedule", recording_schedule_id=off["id"])
        plain = _camera(c, "Plain")
        for x in (cam, plain):
            r = c.put(f"/api/v1/assignments/{x['id']}", json={"node_id": node["node_id"]})
            assert r.status_code == 200, r.text
        data = c.get(f"/internal/v1/nodes/{node['node_id']}/assignments").json()
        assert data["site_timezone"]
        rec = {x["camera_id"]: x["recording"] for x in data["cameras"]}
        assert rec[plain["id"]] == {"mode": "always", "events": {"pre": 10, "post": 30, "marking": True, "max": 300}}
        assert rec[cam["id"]]["mode"] == "schedule" and rec[cam["id"]]["blocks"] == off["blocks"]
        assert rec[cam["id"]]["schedule_id"] == off["id"] and rec[cam["id"]]["version"]

        # both connected but not recording: only the camera that should record raises an alert
        items = [{"camera_id": x["id"], "profile": "main", "status": "STREAMING"} for x in (cam, plain)]
        assert c.post(f"/internal/v1/nodes/{node['node_id']}/stream-status", json={"items": items}).status_code == 204
        alerts = c.get("/api/v1/cluster/alerts").json()["items"]
        assert [a["camera_name"] for a in alerts if a["kind"] == "stream"] == ["Plain"]
        items = [{"camera_id": cam["id"], "profile": "main", "status": "SCHEDULED_OFF"}]
        assert c.post(f"/internal/v1/nodes/{node['node_id']}/stream-status", json={"items": items}).status_code == 204
        stream = c.get(f"/api/v1/cameras/{cam['id']}").json()["streams"][0]
        assert stream["status"] == "SCHEDULED_OFF"
