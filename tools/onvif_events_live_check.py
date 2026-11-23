"""Live check of camera events from ONVIF (docs/ONVIF_EVENTS_PLAN.md §9.4) with the simulators.

Needs running: central :8100 (AUTH off), one node :7200, `camera_simulator.py --count 3` and
`onvif_simulator.py --count 3` (sim-1 tyco, sim-2 axis with its clock 10 min behind, sim-3 isin). The script adds the
three cameras through ONVIF, switches camera events on, fires motion / inputs on the simulators and checks:
  1. subscription state "ok" with the right topic per vendor; a wrong password -> auth_failed + alert, no retries
  2. Event mode: camera motion keeps video around it (pre / post) and shows as a closed `motion` event
  3. flapping motion (on/off x3 within the post time) = one event
  4. a digital input = its own event, labelled "Input DI1"; tyco noise (health / PTZ repeats) makes no events
  5. events off -> the node unsubscribes and the status is cleared
"""

import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

C = httpx.Client(base_url="http://127.0.0.1:8100/api/v1", timeout=60)
SIM_PORT = 8655
ok = True


def say(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def check(cond, msg):
    global ok
    ok &= bool(cond)
    say("PASS" if cond else "FAIL", msg)


def wait_for(fn, what, timeout=90, every=1.0):
    t = time.time()
    while time.time() - t < timeout:
        try:
            if v := fn():
                return v
        except Exception:  # noqa: BLE001 - keep polling
            pass
        time.sleep(every)
    say("timeout waiting for", what)
    return None


def sim(i, kind, state):
    r = httpx.get(f"http://127.0.0.{i + 1}:{SIM_PORT}/sim/{kind}/{state}", timeout=5)
    say("  sim:", r.text)


def cam(cid):
    return C.get(f"/cameras/{cid}").json()


def events(cid, type_=None):
    params = {"camera_id": cid, "limit": 100, **({"type": type_} if type_ else {})}
    return C.get("/events", params=params).json()["items"]


def segments(cid, since):
    r = C.get(f"/cameras/{cid}/recordings", params={
        "start": since.isoformat(), "end": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()})
    return r.json()["segments"]


# ---------------------------------------------------------------- setup
nodes = C.get("/nodes").json()
nodes = nodes.get("items", nodes) if isinstance(nodes, dict) else nodes
if not nodes:
    sys.exit("no media node registered")
node_id = nodes[0]["id"]
ids = {}
for i in (1, 2, 3):
    r = C.post("/onvif/cameras", json={"host": f"127.0.0.{i + 1}", "port": SIM_PORT, "username": "admin",
                                       "password": "admin", "name": f"ev-sim-{i}", "allow_duplicate": True,
                                       "streams": [{"profile": "main", "token": "main", "record": True}]})
    assert r.status_code == 201, r.text
    ids[i] = r.json()["id"]
    C.put(f"/assignments/{ids[i]}", json={"node_id": node_id})
A, B, W = ids[1], ids[2], ids[3]  # A: tyco, Event mode; B: axis, Always; W: isin, wrong password
say("cameras", ids)
C.patch(f"/cameras/{A}", json={"recording_mode": "event", "onvif_events_enabled": True})
C.patch(f"/cameras/{B}", json={"onvif_events_enabled": True, "onvif_event_kinds": ["motion", "tamper"]})
C.patch(f"/cameras/{W}", json={"onvif_events_enabled": True, "password": "wrong"})
start = datetime.now(timezone.utc) - timedelta(minutes=1)

# ---------------------------------------------------------------- 1. subscriptions
for cid, topic in ((A, "tns1:VideoSource/MotionAlarm"), (B, "tnsaxis:CameraApplicationPlatform/VMD/Camera1ProfileANY")):
    st = wait_for(lambda: (s := cam(cid)["onvif_events_status"]) and s.get("state") == "ok" and s, f"camera {cid} ok")
    check(st and st["topics"].get("motion") == topic, f"camera {cid} subscribed, motion topic {st and st['topics'].get('motion')}")
st = wait_for(lambda: (s := cam(W)["onvif_events_status"]) and s.get("state") == "auth_failed" and s, "auth_failed")
check(st, "wrong password -> auth_failed")
alerts = C.get("/cluster/alerts").json()["items"]
check(any(a["kind"] == "camera_events" and a["camera_id"] == W for a in alerts), "dashboard alert for the wrong password")

# ---------------------------------------------------------------- 2. motion in Event mode keeps video
check(wait_for(lambda: cam(A)["streams"][0]["status"] == "EVENT_STANDBY", "EVENT_STANDBY", 120), "camera A on event standby")
time.sleep(25)
check(segments(A, start) == [], "nothing kept before any event")
t_motion = datetime.now(timezone.utc)
sim(1, "motion", "on")
ev = wait_for(lambda: events(A, "motion"), "motion event at central", 30, 0.5)
if ev:
    lag = (datetime.now(timezone.utc) - t_motion).total_seconds()
    check(abs((datetime.fromisoformat(ev[0]["start_time"]) - t_motion).total_seconds()) < 2,
          f"motion event start within 2 s of the trigger (seen at central after {lag:.1f} s)")
else:
    check(False, "motion event reached central")
time.sleep(6)
sim(1, "motion", "off")
closed = wait_for(lambda: (e := events(A, "motion")) and e[0]["end_time"] and e, "motion closed", 30, 0.5)
check(closed and 4 <= (datetime.fromisoformat(closed[0]["end_time"]) - datetime.fromisoformat(closed[0]["start_time"])).total_seconds() <= 10,
      "motion event closed with the camera's off (about 6 s long)")
segs = wait_for(lambda: (s := segments(A, start)) and max(datetime.fromisoformat(x["end_time"]) for x in s)
                >= t_motion + timedelta(seconds=30) and s, "kept chunks", 150, 3)
if segs:
    first = min(datetime.fromisoformat(x["start_time"]) for x in segs)
    ev_start = datetime.fromisoformat(events(A, "motion")[0]["start_time"])  # the camera's time, corrected
    say(f"  kept {len(segs)} chunk(s) from {first:%H:%M:%S.%f} (motion event {ev_start:%H:%M:%S.%f})")
    check(first <= ev_start - timedelta(seconds=10), "pre-event video kept (10 s before the motion event)")
else:
    check(False, "event video reached the catalog")

# ---------------------------------------------------------------- 3. flapping motion = one event
before = len(events(B, "motion"))
for _ in range(3):
    sim(2, "motion", "on")
    time.sleep(2)
    sim(2, "motion", "off")
    time.sleep(2)
time.sleep(8)
evs = events(B, "motion")
check(len(evs) - before == 1, f"flapping motion on the AXIS-like camera = 1 event ({len(evs) - before})")
if evs:
    check(abs((datetime.fromisoformat(evs[0]["start_time"]) - datetime.now(timezone.utc)).total_seconds()) < 60,
          "camera clock 10 min behind: the event time is corrected")

# ---------------------------------------------------------------- 4. inputs, noise
sim(1, "input", "on")
di = wait_for(lambda: events(A, "digital_input"), "input event", 20, 0.5)
check(di and di[0]["label"] == "Input DI1", f"digital input event {di and di[0]['label']}")
sim(1, "input", "off")
sim(2, "input", "on")  # B uses motion + tamper only
time.sleep(5)
check(not events(B, "digital_input"), "inputs not chosen for camera B: no input event")
sim(2, "input", "off")
check(not events(A, "onvif") and not events(B, "onvif"), "health / PTZ repeats made no events")

# ---------------------------------------------------------------- 5. switch off
C.patch(f"/cameras/{B}", json={"onvif_events_enabled": False})
time.sleep(12)
check(cam(B)["onvif_events_status"] is None, "events off: status cleared")
before = len(events(B, "motion"))
sim(2, "motion", "on")
time.sleep(5)
sim(2, "motion", "off")
check(len(events(B, "motion")) == before, "events off: camera motion is ignored")

say("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
