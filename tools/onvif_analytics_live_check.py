"""Live check of camera analytics events (docs/ONVIF_ANALYTICS_EVENTS_PLAN.md §9.3) with the simulators.

Needs running: central :8100 (AUTH off), one node :7200, `camera_simulator.py --count 3` and
`onvif_simulator.py --count 3` (sim-1 tyco = Pro4-like, sim-3 isin = standard rule engine). Checks:
  1. Detect lists the analytics kinds and, on the ISIN, the configured rules
  2. analytics are off until chosen; a kind not chosen makes no event
  3. ISIN: line crossings within the post time = one event "Line crossing · Gate line ×3"; intrusion = a range
  4. Pro4: the kind comes from RuleType; labels carry rule, object and confidence; face / audio / counting
  5. a burst of 50 crossings = one event (×50), not 50 rows
  6. Events search: q (label contains) and group=analytics
  7. Event mode: video is kept around a line crossing
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


def sim(i, name, state):
    r = httpx.get(f"http://127.0.0.{i + 1}:{SIM_PORT}/sim/{name}/{state}", timeout=30)
    say("  sim:", r.text)


def cam(cid):
    return C.get(f"/cameras/{cid}").json()


def events(cid=None, **params):
    p = {"limit": 200, **({"camera_id": cid} if cid else {}), **params}
    return C.get("/events", params=p).json()["items"]


def closed(cid, type_):
    return [e for e in events(cid, type=type_) if e["end_time"]]


# ---------------------------------------------------------------- setup
nodes = C.get("/nodes").json()
nodes = nodes.get("items", nodes) if isinstance(nodes, dict) else nodes
if not nodes:
    sys.exit("no media node registered")
node_id = nodes[0]["id"]
ids = {}
for i in (1, 3):
    r = C.post("/onvif/cameras", json={"host": f"127.0.0.{i + 1}", "port": SIM_PORT, "username": "admin",
                                       "password": "admin", "name": f"an-sim-{i}", "allow_duplicate": True,
                                       "streams": [{"profile": "main", "token": "main", "record": True}]})
    assert r.status_code == 201, r.text
    ids[i] = r.json()["id"]
    C.put(f"/assignments/{ids[i]}", json={"node_id": node_id})
P4, ISIN = ids[1], ids[3]
say("cameras: pro4-like", P4, "isin-like", ISIN)
start = datetime.now(timezone.utc) - timedelta(minutes=1)

# ---------------------------------------------------------------- 1. Detect
d = C.post(f"/onvif/cameras/{ISIN}/events/probe").json()
kinds = [a["kind"] for a in d.get("analytics", [])]
check({"line_crossing", "intrusion", "loitering", "face", "counting"} <= set(kinds), f"ISIN Detect analytics {kinds}")
line = next((a for a in d["analytics"] if a["kind"] == "line_crossing"), {})
check([r["name"] for r in line.get("rules", [])] == ["Gate line"], f"ISIN Detect rules for line crossing {line.get('rules')}")
d4 = C.post(f"/onvif/cameras/{P4}/events/probe").json()
k4 = [a["kind"] for a in d4.get("analytics", [])]
check({"line_crossing", "intrusion", "face", "audio_alarm", "counting"} <= set(k4), f"Pro4 Detect analytics {k4}")

# ---------------------------------------------------------------- 2. switch on (some kinds only)
C.patch(f"/cameras/{ISIN}", json={"recording_mode": "event", "onvif_events_enabled": True,
                                  "onvif_event_kinds": ["motion", "line_crossing", "intrusion"]})
C.patch(f"/cameras/{P4}", json={"onvif_events_enabled": True, "onvif_event_kinds": [
    "line_crossing", "intrusion", "face", "audio_alarm", "counting"]})
for cid in (ISIN, P4):
    st = wait_for(lambda: (s := cam(cid)["onvif_events_status"]) and s.get("state") == "ok" and s, f"{cid} ok")
    check(st and "line_crossing" in (st.get("topics") or {}), f"camera {cid} subscribed with analytics topics")
check(wait_for(lambda: cam(ISIN)["streams"][0]["status"] == "EVENT_STANDBY", "EVENT_STANDBY", 120), "ISIN on event standby")
time.sleep(5)

# ---------------------------------------------------------------- 3. ISIN
for _ in range(3):
    sim(3, "line", "on")
    time.sleep(2)
ev = wait_for(lambda: [e for e in events(ISIN, type="line_crossing") if "×3" in (e["label"] or "")], "line ×3", 60)
check(ev and ev[0]["label"] == "Line crossing · Gate line ×3" and len(events(ISIN, type="line_crossing")) == 1,
      f"3 crossings within post = 1 event: {[e['label'] for e in events(ISIN, type='line_crossing')]}")
t_line = datetime.now(timezone.utc)
sim(3, "intrusion", "on")
time.sleep(5)
sim(3, "intrusion", "off")
rng = wait_for(lambda: closed(ISIN, "intrusion"), "intrusion range", 60)
if rng:
    secs = (datetime.fromisoformat(rng[0]["end_time"]) - datetime.fromisoformat(rng[0]["start_time"])).total_seconds()
    check(rng[0]["label"] == "Intrusion · Parking" and 3 <= secs <= 9, f"intrusion range {rng[0]['label']} {secs:.1f} s")
else:
    check(False, "intrusion range reached central")
sim(3, "loiter", "on")
time.sleep(6)
sim(3, "loiter", "off")
check(not events(ISIN, type="loitering"), "loitering not chosen: no event")

# ---------------------------------------------------------------- 4. Pro4-like
sim(1, "line", "on")
sim(1, "line", "off")
ev = wait_for(lambda: events(P4, type="line_crossing"), "pro4 line", 60)
check(ev and ev[0]["label"] == "Line crossing · Gate line · Person (87 %)", f"Pro4 line label {ev and ev[0]['label']}")
check(ev and ev[0]["data"].get("boxes") == ["0.10,0.20,0.30,0.60"] and ev[0]["data"].get("direction") == "LeftToRight",
      f"Pro4 data {ev and ev[0]['data']}")
sim(1, "intrusion", "on")
time.sleep(4)
sim(1, "intrusion", "off")
check(wait_for(lambda: closed(P4, "intrusion"), "pro4 intrusion", 60), "Pro4 intrusion range")
sim(1, "audio", "on")
sim(1, "face", "on")
sim(1, "count", "on")
check(wait_for(lambda: events(P4, type="audio_alarm"), "audio", 60)[0]["label"] == "Audio alarm · Window",
      "Pro4 audio alarm")
check(wait_for(lambda: events(P4, type="face"), "face", 60), "Pro4 face")
cnt = wait_for(lambda: events(P4, type="counting"), "count", 60)
check(cnt and cnt[0]["label"].startswith("People counting · in 1"), f"Pro4 counting {cnt and cnt[0]['label']}")
sim(1, "loiter", "on")
time.sleep(6)
check(not events(P4, type="loitering"), "Pro4 loitering not chosen: no event")

# ---------------------------------------------------------------- 5. burst
time.sleep(35)  # past the post time of the earlier crossings
before = len(events(ISIN, type="line_crossing"))
httpx.get(f"http://127.0.0.4:{SIM_PORT}/sim/line/burst?n=50", timeout=30)
burst = wait_for(lambda: [e for e in events(ISIN, type="line_crossing") if "×50" in (e["label"] or "")], "×50", 90)
check(burst and len(events(ISIN, type="line_crossing")) == before + 1,
      f"burst of 50 = one event: {[e['label'] for e in events(ISIN, type='line_crossing')][:3]}")

# ---------------------------------------------------------------- 6. search
found = events(q="gate LINE", group="analytics")
check(found and all("Gate line" in e["label"] for e in found) and {e["camera_id"] for e in found} == {ISIN, P4},
      f"q=gate line: {len(found)} events on both cameras")
check(all(e["type"] != "motion" for e in events(group="analytics")), "group=analytics has no motion")

# ---------------------------------------------------------------- 7. Event mode keeps video around a crossing
time.sleep(20)
segs = C.get(f"/cameras/{ISIN}/recordings", params={"start": start.isoformat(),
                                                    "end": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()}).json()["segments"]
check(any(datetime.fromisoformat(s["start_time"]) <= t_line + timedelta(seconds=5) for s in segs),
      f"video kept around the line crossing ({len(segs)} segment(s))")

say("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
