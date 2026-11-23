"""Camera event watcher on the node (docs/ONVIF_EVENTS_PLAN.md §5.3): edges -> node events with merging (D7), long
events split at max (D7), event time from the camera clock (D8), the login lockout guard (D4), a full PullPoint
session against a fake camera, and the supervisor following the assignments."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from tortoise import Tortoise

import app.onvif.services as onvif_services
from app.events.models import EventWindow
from app.node.utils import runtime
from app.onvif import event_watch as ew
from app.onvif.event_topics import Edge
from settings.settings import settings

T0 = datetime(2026, 11, 23, 10, 0, tzinfo=timezone.utc)
EVENTS = {"pre": 10, "post": 30, "marking": True, "max": 300}
CREDS = {"kinds": ["motion", "digital_input"], "store_other": False, "username": "admin", "password": "pw"}


def cam(cid=1, events=CREDS, host="192.0.2.10"):
    return {"camera_id": cid, "camera_name": f"cam {cid}", "generation": 1, "streams": [],
            "recording": {"mode": "event", "events": EVENTS}, "onvif_host": host, "onvif_port": 80,
            "onvif_events": events}


@pytest.fixture
def node():
    saved = (runtime.assignments, runtime.node_id)
    runtime.assignments = {1: cam()}
    runtime.node_id = 7
    ew._status.clear()
    yield
    runtime.assignments, runtime.node_id = saved
    ew._status.clear()


def run_db(tmp_path, fn):
    async def go():
        await Tortoise.init(db_url=f"sqlite://{(tmp_path / 'node.sqlite3').as_posix()}",
                            modules={"models": ["app.node.models", "app.recordings.models", "app.events.models"]})
        await Tortoise.generate_schemas()
        try:
            return await fn()
        finally:
            await Tortoise.close_connections()

    return asyncio.run(go())


def edge(action, key="m", kind="motion", label=None):
    return Edge(kind, key, action, label, {"topic": "tns1:VideoSource/MotionAlarm"}, None)


# ---------------------------------------------------------------- config / time


def test_config_needs_host_and_events():
    assert ew.config_of(1, cam()).kinds == ("motion", "digital_input")
    assert ew.config_of(1, cam(events=None)) is None
    assert ew.config_of(1, cam(host=None)) is None
    assert ew.config_of(1, cam(events={**CREDS, "kinds": ["bogus"]})) is None
    assert ew.config_of(1, cam(events={**CREDS, "kinds": None})).kinds == ("motion", "tamper", "digital_input")


def test_event_time_uses_the_camera_clock_minus_its_offset():
    now = T0
    assert ew.event_time(T0 + timedelta(seconds=118), 120, now) == T0 - timedelta(seconds=2)
    assert ew.event_time(datetime(1971, 1, 1, tzinfo=timezone.utc), 120, now) == now  # wrong clock: receive time
    assert ew.event_time(None, 0, now) == now


# ---------------------------------------------------------------- edges -> events


def test_flapping_motion_is_one_event(node, tmp_path):
    async def go():
        st = ew.EventState()
        await ew.apply_edge(1, edge("start"), T0, st)
        await ew.apply_edge(1, edge("end"), T0 + timedelta(seconds=5), st)
        await ew.apply_edge(1, edge("start"), T0 + timedelta(seconds=20), st)  # within post (30 s): same event
        await ew.apply_edge(1, edge("end"), T0 + timedelta(seconds=25), st)
        await ew.apply_edge(1, edge("start"), T0 + timedelta(seconds=90), st)  # later: a new event
        return await EventWindow.all().order_by("start_time")

    rows = run_db(tmp_path, go)
    assert [(r.type, r.start_time, r.end_time) for r in rows] == [
        ("motion", T0, T0 + timedelta(seconds=25)), ("motion", T0 + timedelta(seconds=90), None)]
    assert all(r.node_made and not r.uploaded for r in rows)  # marking on: uploaded to central


def test_inputs_keep_their_own_events(node, tmp_path):
    async def go():
        st = ew.EventState()
        await ew.apply_edge(1, edge("start", "DI1", "digital_input", "Input DI1"), T0, st)
        await ew.apply_edge(1, edge("start", "DI2", "digital_input", "Input DI2"), T0, st)
        await ew.apply_edge(1, edge("end", "DI1", "digital_input", "Input DI1"), T0 + timedelta(seconds=3), st)
        return await EventWindow.all().order_by("label")

    rows = run_db(tmp_path, go)
    assert [(r.label, r.end_time) for r in rows] == [("Input DI1", T0 + timedelta(seconds=3)), ("Input DI2", None)]


def test_moments_merge_too(node, tmp_path):
    async def go():
        st = ew.EventState()
        await ew.apply_edge(1, edge("moment", kind="onvif"), T0, st)
        await ew.apply_edge(1, edge("moment", kind="onvif"), T0 + timedelta(seconds=10), st)
        return await EventWindow.all()

    rows = run_db(tmp_path, go)
    assert [(r.start_time, r.end_time) for r in rows] == [(T0, T0 + timedelta(seconds=10))]


def test_long_motion_is_split_at_max(node, tmp_path):
    async def go():
        st = ew.EventState()
        await ew.apply_edge(1, edge("start"), T0, st)
        await ew.split_long(1, st, T0 + timedelta(seconds=299))
        await ew.split_long(1, st, T0 + timedelta(seconds=301))
        return await EventWindow.all().order_by("start_time")

    rows = run_db(tmp_path, go)
    assert [(r.start_time, r.end_time) for r in rows] == [
        (T0, T0 + timedelta(seconds=300)), (T0 + timedelta(seconds=300), None)]


def test_events_left_open_by_a_previous_run_are_closed(node, tmp_path):
    async def go():
        await EventWindow.create(key="a", camera_id=1, type="motion", start_time=T0, node_made=True)
        await EventWindow.create(key="b", camera_id=1, type="video_loss", start_time=T0, node_made=True)
        assert await ew.close_stale_events() == 1
        return {w.key: w.end_time for w in await EventWindow.all()}

    ends = run_db(tmp_path, go)
    assert ends["a"] is not None and ends["b"] is None  # video loss has its own watcher


# ---------------------------------------------------------------- status report


def test_status_is_reported_once_until_it_changes(node):
    ew.set_status(1, "ok", topics={"motion": "x"}, offered=["motion"])
    sent = ew.take_status()
    assert [s["state"] for s in sent] == ["ok"]
    ew.ack_status(sent)
    assert ew.take_status() == []
    ew.set_status(1, "ok", topics={"motion": "x"}, offered=["motion"])  # same: nothing new
    assert ew.take_status() == []
    ew.set_status(1, "auth_failed", detail="wrong password")
    assert [s["state"] for s in ew.take_status()] == ["auth_failed"]


# ---------------------------------------------------------------- full session against a fake camera


class Camera:
    """A Pro3-like camera: motion on, then off; or a wrong password."""

    def __init__(self, wrong_password=False):
        self.wrong_password = wrong_password
        self.ops: list[str] = []
        self.pulls = [
            [("Initialized", "false")],
            [("Changed", "true"), ("Changed", "true")],  # a repeat (Q7)
            [("Changed", "false")],
        ]

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        op = next(o for o in ("GetSystemDateAndTime", "GetServices", "GetEventProperties",
                              "CreatePullPointSubscription", "PullMessages", "Renew", "Unsubscribe",
                              "SetSynchronizationPoint") if f":{o}" in body)
        self.ops.append(op)
        env = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
               'xmlns:tev="http://www.onvif.org/ver10/events/wsdl" xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" '
               'xmlns:wsa="http://www.w3.org/2005/08/addressing" xmlns:tt="http://www.onvif.org/ver10/schema" '
               'xmlns:tns1="http://www.onvif.org/ver10/topics"><s:Body>{}</s:Body></s:Envelope>')
        if op == "GetSystemDateAndTime":
            now = datetime.now(timezone.utc)
            inner = ("<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime><tt:DateTimeType>NTP</tt:DateTimeType>"
                     f"<tt:UTCDateTime><tt:Date><tt:Year>{now.year}</tt:Year><tt:Month>{now.month}</tt:Month>"
                     f"<tt:Day>{now.day}</tt:Day></tt:Date><tt:Time><tt:Hour>{now.hour}</tt:Hour><tt:Minute>"
                     f"{now.minute}</tt:Minute><tt:Second>{now.second}</tt:Second></tt:Time></tt:UTCDateTime>"
                     "</tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>")
        elif self.wrong_password:
            return httpx.Response(400, content=env.format(
                '<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode><s:Value>ter:NotAuthorized</s:Value>'
                '</s:Subcode></s:Code><s:Reason><s:Text>Sender not authorized</s:Text></s:Reason></s:Fault>').encode())
        elif op == "GetServices":
            inner = ('<tds:GetServicesResponse><tds:Service><tds:Namespace>http://www.onvif.org/ver10/events/wsdl'
                     '</tds:Namespace><tds:XAddr>http://192.0.2.10/onvif/event_service</tds:XAddr></tds:Service>'
                     '</tds:GetServicesResponse>')
        elif op == "GetEventProperties":
            from tests.test_onvif_events import FIX
            return httpx.Response(200, content=b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
                                  + (FIX / "pro3_topicset.xml").read_bytes() + b"</s:Envelope>")
        elif op == "CreatePullPointSubscription":
            inner = ('<tev:CreatePullPointSubscriptionResponse><tev:SubscriptionReference>'
                     '<wsa:Address>http://192.0.2.10/onvif/sub/1</wsa:Address></tev:SubscriptionReference>'
                     '</tev:CreatePullPointSubscriptionResponse>')
        elif op == "PullMessages":
            if not self.pulls:
                await asyncio.sleep(0.05)  # nothing new: the long-poll would wait
            batch = self.pulls.pop(0) if self.pulls else []
            inner = "<tev:PullMessagesResponse>" + "".join(
                f'<wsnt:NotificationMessage><wsnt:Topic>tns1:VideoSource/MotionAlarm</wsnt:Topic><wsnt:Message>'
                f'<tt:Message UtcTime="{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}" PropertyOperation="{op_}">'
                f'<tt:Source><tt:SimpleItem Name="Source" Value="1"/></tt:Source><tt:Data>'
                f'<tt:SimpleItem Name="State" Value="{v}"/></tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage>'
                for op_, v in batch) + "</tev:PullMessagesResponse>"
        else:
            inner = f"<tev:{op}Response/>"
        return httpx.Response(200, content=env.format(inner).encode())


@pytest.fixture
def fake_camera(monkeypatch):
    real = httpx.AsyncClient
    holder = {}

    def client(**kw):
        kw.pop("verify", None)
        return real(transport=httpx.MockTransport(holder["cam"]), **kw)

    monkeypatch.setattr(onvif_services.httpx, "AsyncClient", client)
    monkeypatch.setattr(settings, "ONVIF_EVENTS_PULL_SECONDS", 1)
    return holder


async def wait_for(cond, seconds=3.0):
    for _ in range(int(seconds / 0.02)):
        if await cond():
            return True
        await asyncio.sleep(0.02)
    return False


def test_session_turns_camera_motion_into_one_event(node, tmp_path, fake_camera):
    camera = fake_camera["cam"] = Camera()

    async def go():
        w = ew.CameraWatch(ew.config_of(1, runtime.assignments[1]))
        w.start()
        ok = await wait_for(lambda: EventWindow.filter(type="motion", end_time__isnull=False).exists())
        await w.stop()
        return ok, await EventWindow.all()

    ok, rows = run_db(tmp_path, go)
    assert ok
    assert len(rows) == 1 and rows[0].type == "motion" and rows[0].end_time >= rows[0].start_time
    assert rows[0].data["topic"] == "tns1:VideoSource/MotionAlarm"
    assert camera.ops[:5] == ["GetSystemDateAndTime", "GetServices", "GetEventProperties",
                              "CreatePullPointSubscription", "SetSynchronizationPoint"]
    assert camera.ops[-1] == "Unsubscribe"  # stop frees the camera's subscription slot
    assert ew._status[1]["state"] == "ok"
    assert ew._status[1]["topics"] == {"motion": "tns1:VideoSource/MotionAlarm",
                                       "digital_input": "tns1:Device/Trigger/DigitalInput"}


def test_wrong_password_stops_after_one_login(node, tmp_path, fake_camera):
    camera = fake_camera["cam"] = Camera(wrong_password=True)

    async def go():
        w = ew.CameraWatch(ew.config_of(1, runtime.assignments[1]))
        w.start()
        await wait_for(lambda: _async(ew._status.get(1, {}).get("state") == "auth_failed"))
        await asyncio.sleep(0.1)
        await w.stop()

    run_db(tmp_path, go)
    assert ew._status[1]["state"] == "auth_failed"
    assert camera.ops == ["GetSystemDateAndTime", "GetServices"]  # one login, then it waits (D4)


async def _async(v):
    return v


def test_supervisor_follows_the_assignments(node, tmp_path, fake_camera, monkeypatch):
    fake_camera["cam"] = Camera()
    monkeypatch.setattr(ew, "_started", True)

    async def go():
        await ew.events_supervisor_tick()
        first = ew._watches[1]
        await ew.events_supervisor_tick()
        same = ew._watches[1] is first
        runtime.assignments = {1: cam(events={**CREDS, "password": "new"})}
        await ew.events_supervisor_tick()
        restarted = ew._watches[1] is not first
        runtime.assignments = {1: cam(events=None)}
        await ew.events_supervisor_tick()
        stopped = 1 not in ew._watches and 1 not in ew._status
        monkeypatch.setattr(settings, "ONVIF_EVENTS_ENABLED", False)
        runtime.assignments = {1: cam()}
        await ew.events_supervisor_tick()
        off = not ew._watches
        await ew.stop_all()
        return same, restarted, stopped, off

    assert run_db(tmp_path, go) == (True, True, True, True)
