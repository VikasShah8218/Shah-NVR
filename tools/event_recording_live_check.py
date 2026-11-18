"""Live check of event recording (docs/EVENT_RECORDING_PLAN.md §8 step 5). Central :8100, node :7200, sim :8654."""
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

C = httpx.Client(base_url="http://127.0.0.1:8100/api/v1", timeout=10)
N = httpx.Client(base_url="http://127.0.0.1:7200/api/v1", timeout=10)
EV, ALW = 1, 2
ok = True


def say(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def check(cond, msg):
    global ok
    ok &= bool(cond)
    say("PASS" if cond else "FAIL", msg)


def status(cid):
    return C.get(f"/cameras/{cid}").json()["streams"][0]["status"]


def segments(cid, since):
    r = C.get(f"/cameras/{cid}/recordings", params={"start": since.isoformat(),
                                                    "end": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()})
    return r.json()["segments"]


def wait_for(fn, what, timeout=180):
    t = time.time()
    while time.time() - t < timeout:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(3)
    say("timeout waiting for", what)
    return None


start = datetime.now(timezone.utc) - timedelta(minutes=10)

# 1. standby: event camera writes held chunks, nothing reaches the catalog; always camera records
wait_for(lambda: status(EV) == "EVENT_STANDBY", "EVENT_STANDBY")
check(status(EV) == "EVENT_STANDBY", f"event camera status {status(EV)}")
wait_for(lambda: status(ALW) == "RECORDING" and segments(ALW, start), "always camera chunks")
time.sleep(60)
check(segments(EV, start) == [], "event camera: no chunks in the catalog before any event")
local = N.get("/segments", params={"camera_id": EV}).json()
check(local["total"] <= 7, f"event camera: only recent held chunks on the node ({local['total']})")

# 2. manual event: kept ~10 s before to ~20 s after
t_ev = datetime.now(timezone.utc)
e = C.post(f"/cameras/{EV}/events", json={"label": "Door"}).json()
say("event", e["id"], e["start_time"])
time.sleep(2)
check(any(w["central_id"] == e["id"] for w in N.get("/events").json()), "node got the event pushed")
check(status(EV) in ("RECORDING", "EVENT_STANDBY"), f"status during event: {status(EV)}")
m = C.post(f"/cameras/{EV}/events", json={"label": "Door"}).json()
check(m["id"] == e["id"] and m["merged"], "second press merged into the first event")
segs = wait_for(lambda: (s := segments(EV, start)) and max(datetime.fromisoformat(x["end_time"]) for x in s) >= t_ev + timedelta(seconds=20) and s,
                "kept chunks", 150)
if segs:
    first = min(datetime.fromisoformat(x["start_time"]) for x in segs)
    last = max(datetime.fromisoformat(x["end_time"]) for x in segs)
    say(f"kept {len(segs)} chunk(s): {first:%H:%M:%S} -> {last:%H:%M:%S} (event {t_ev:%H:%M:%S})")
    check(first <= t_ev - timedelta(seconds=10) and first >= t_ev - timedelta(seconds=25), "pre-event video kept (10 s, whole chunks)")
    check(last >= t_ev + timedelta(seconds=20) and last <= t_ev + timedelta(seconds=45), "post-event video kept (20 s, whole chunks)")
    check(sum(x["duration_ms"] for x in segs) < 70_000, "only the event window, not the whole time")
else:
    check(False, "event chunks reached the catalog")
time.sleep(30)
after = segments(EV, start)
check(len(after) == len(segs or []), f"nothing more kept after the window ({len(after)} chunks)")
check(status(EV) == "EVENT_STANDBY", f"back to standby: {status(EV)}")

# 3. video loss: stop the simulator, both cameras (seen up) get a video_loss event; restart closes them
say("stopping the camera simulator")
subprocess.run(["powershell", "-c", "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*camera_simulator*' -or $_.CommandLine -like '*shah_nvr_camera_sim*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"], check=False)
loss = wait_for(lambda: [x for x in C.get("/events", params={"type": "video_loss"}).json()["items"]], "video_loss events", 120)
check(loss and {x["camera_id"] for x in loss} == {EV, ALW}, f"video_loss for both cameras: {[(x['camera_id'], x['source']) for x in loss or []]}")
say("starting the camera simulator again")
subprocess.Popen([sys.executable, "tools/camera_simulator.py", "--count", "2"], cwd=r"D:\Drive-1\Shah-Secret-Project\Shah-NVR",
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
closed = wait_for(lambda: all(x["end_time"] for x in C.get("/events", params={"type": "video_loss"}).json()["items"]), "loss closed", 120)
check(closed, "video_loss events closed when the cameras came back")
ev_loss = [x for x in C.get("/events", params={"type": "video_loss", "camera_id": EV}).json()["items"]]
if ev_loss:
    t_loss = datetime.fromisoformat(ev_loss[0]["start_time"])
    kept = wait_for(lambda: [x for x in segments(EV, start) if datetime.fromisoformat(x["end_time"]) > t_loss - timedelta(seconds=10)
                             and datetime.fromisoformat(x["start_time"]) < t_loss], "pre-loss video", 90)
    check(kept, "event camera kept the video just before the loss")
say("ALL PASS" if ok else "SOME FAILED")
