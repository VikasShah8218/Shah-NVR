"""Camera events from ONVIF on central (docs/ONVIF_EVENTS_PLAN.md §6): per-camera settings (off by default), the
assignment payload (credentials only when on), group apply, heartbeat status, alerts, Detect. Real app, SQLite."""

from fastapi.testclient import TestClient

from app.nodes.models import MediaNode
from app.onvif import router as onvif

STREAM = [{"profile": "main", "source_url": "rtsp://1.2.3.4/x", "record": True}]


def _client():
    import main

    return TestClient(main.app)


def _camera(c, name, **extra):
    r = c.post("/api/v1/cameras", json={"name": name, "streams": STREAM, "username": "admin", "password": "pw",
                                        **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _node(c, name="n1"):
    return c.post("/internal/v1/nodes/register",
                  json={"name": name, "api_url": f"http://{name}:7100", "media_host": name}).json()["node_id"]


def _assign(c, cam_id, node_id):
    assert c.put(f"/api/v1/assignments/{cam_id}", json={"node_id": node_id}).status_code == 200


async def _set_host(cam_id, host):
    from app.cameras.models import Camera

    await Camera.filter(id=cam_id).update(onvif_host=host, onvif_port=80)


def _onvif_host(c, cam_id, host="192.0.2.10"):
    c.portal.call(_set_host, cam_id, host)  # the device fields come from an ONVIF probe; set them directly here


def _payload(c, node):
    return {x["camera_id"]: x["onvif_events"] for x in c.get(f"/internal/v1/nodes/{node}/assignments").json()["cameras"]}


def test_off_by_default_and_payload_only_when_on():
    with _client() as c:
        cam = _camera(c, "Gate")
        assert (cam["onvif_events_enabled"], cam["onvif_event_kinds"], cam["onvif_events_store_other"]) == (False, None, False)
        node = _node(c)
        _assign(c, cam["id"], node)
        _onvif_host(c, cam["id"])
        assert _payload(c, node)[cam["id"]] is None  # off: no credentials sent for events

        r = c.patch(f"/api/v1/cameras/{cam['id']}", json={"onvif_events_enabled": True, "onvif_event_kinds": ["motion"]})
        assert r.status_code == 200 and r.json()["onvif_events_enabled"] is True
        assert _payload(c, node)[cam["id"]] == {"kinds": ["motion"], "store_other": False, "username": "admin",
                                                "password": "pw"}
        r = c.patch(f"/api/v1/cameras/{cam['id']}", json={"onvif_event_kinds": None})  # null = all kinds
        assert _payload(c, node)[cam["id"]]["kinds"] == ["motion", "tamper", "digital_input"]
        assert c.patch(f"/api/v1/cameras/{cam['id']}", json={"onvif_event_kinds": ["fire"]}).status_code == 422

        # no ONVIF address: nothing to subscribe to
        other = _camera(c, "Manual", onvif_events_enabled=True)
        _assign(c, other["id"], node)
        assert _payload(c, node)[other["id"]] is None


def test_heartbeat_status_alert_and_switch_off():
    with _client() as c:
        cam = _camera(c, "Door", onvif_events_enabled=True)
        node = _node(c)
        _assign(c, cam["id"], node)
        _onvif_host(c, cam["id"])
        r = c.post(f"/internal/v1/nodes/{node}/heartbeat", json={"onvif_events": [
            {"camera_id": cam["id"], "state": "auth_failed", "detail": "Sender not authorized",
             "since": "2026-11-23T10:00:00Z"},
            {"camera_id": 9999, "state": "ok"}]})  # not this node's camera: ignored
        assert r.status_code == 200, r.text
        status = c.get(f"/api/v1/cameras/{cam['id']}").json()["onvif_events_status"]
        assert status["state"] == "auth_failed" and status["detail"] == "Sender not authorized"

        alerts = c.get("/api/v1/cluster/alerts").json()["items"]
        mine = [a for a in alerts if a["kind"] == "camera_events"]
        assert len(mine) == 1 and mine[0]["title"] == "Door: camera events login failed"

        c.post(f"/internal/v1/nodes/{node}/heartbeat", json={"onvif_events": [
            {"camera_id": cam["id"], "state": "ok", "topics": {"motion": "tns1:VideoSource/MotionAlarm"},
             "offered": ["motion"]}]})
        assert not [a for a in c.get("/api/v1/cluster/alerts").json()["items"] if a["kind"] == "camera_events"]

        r = c.patch(f"/api/v1/cameras/{cam['id']}", json={"onvif_events_enabled": False})
        assert r.json()["onvif_events_status"] is None
        # a late report from the node does not bring it back
        c.post(f"/internal/v1/nodes/{node}/heartbeat", json={"onvif_events": [{"camera_id": cam["id"], "state": "ok"}]})
        assert c.get(f"/api/v1/cameras/{cam['id']}").json()["onvif_events_status"] is None


def test_group_apply():
    with _client() as c:
        g = c.post("/api/v1/groups", json={"name": "Site"}).json()
        a = _camera(c, "A", group_id=g["id"])
        b = _camera(c, "B", group_id=g["id"])
        x = _camera(c, "X")
        r = c.post("/api/v1/onvif/events/apply", json={"enabled": True, "kinds": ["motion", "tamper"], "group_id": g["id"]})
        assert r.json() == {"updated": 2}
        got = {cam["name"]: (cam["onvif_events_enabled"], cam["onvif_event_kinds"])
               for cam in (c.get(f"/api/v1/cameras/{i}").json() for i in (a["id"], b["id"], x["id"]))}
        assert got == {"A": (True, ["motion", "tamper"]), "B": (True, ["motion", "tamper"]), "X": (False, None)}
        assert c.post("/api/v1/onvif/events/apply", json={"enabled": False, "camera_ids": [a["id"]]}).json() == {"updated": 1}
        assert c.post("/api/v1/onvif/events/apply", json={"enabled": True}).status_code == 422


def test_detect_asks_the_node_and_saves_what_the_camera_offers(monkeypatch):
    calls = []

    async def call_node(node, path, json=None, *, timeout=30.0, raw=False):
        calls.append((path, json))
        return {"offered": ["tamper", "digital_input"],
                "topics": {"tamper": "tns1:VideoSource/GlobalSceneChange/ImagingService",
                           "digital_input": "tns1:Device/Trigger/DigitalInput"},
                "all_topics": ["tns1:Device/Trigger/DigitalInput"]}

    async def pick_node(**kw):
        return MediaNode(id=1, name="n1", api_url="http://n1:7100", media_host="n1")

    monkeypatch.setattr(onvif, "call_node", call_node)
    monkeypatch.setattr(onvif, "pick_node", pick_node)
    with _client() as c:
        cam = _camera(c, "AXIS")
        _onvif_host(c, cam["id"], "192.0.2.41")
        r = c.post(f"/api/v1/onvif/cameras/{cam['id']}/events/probe")
        assert r.status_code == 200, r.text
        assert r.json()["offered"] == ["tamper", "digital_input"]  # AXIS without VMD: no motion
        assert calls == [("/api/v1/onvif/events/probe", {"host": "192.0.2.41", "port": 80, "username": "admin",
                                                         "password": "pw"})]
        status = c.get(f"/api/v1/cameras/{cam['id']}").json()["onvif_events_status"]
        assert status["state"] == "detected" and status["offered"] == ["tamper", "digital_input"]
