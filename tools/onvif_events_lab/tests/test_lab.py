"""Unit tests for the ONVIF events lab: XML parsing, classification, and the SOAP / subscription flow against a
fake camera (httpx.MockTransport). Run: cd tools && python -m pytest onvif_events_lab/tests -q"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from lxml import etree

from onvif_events_lab import camera as cam_mod
from onvif_events_lab import report, runner
from onvif_events_lab.soap import NS, parse_duration, parse_time
from onvif_events_lab.topics import classify, parse_notifications, parse_topic_set, state_of

ENV = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tt="http://www.onvif.org/ver10/schema" '
       'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:tev="http://www.onvif.org/ver10/events/wsdl" '
       'xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:wstop="http://docs.oasis-open.org/wsn/t-1" '
       'xmlns:wsa="http://www.w3.org/2005/08/addressing" xmlns:tns1="http://www.onvif.org/ver10/topics" '
       'xmlns:tnsaxis="http://www.axis.com/2009/event/topics" xmlns:trt="http://www.onvif.org/ver10/media/wsdl">'
       '<s:Header/><s:Body>{}</s:Body></s:Envelope>')

TOPICSET = """<tev:GetEventPropertiesResponse>
<tev:TopicNamespaceLocation>http://www.onvif.org/onvif/ver10/topics/topicns.xml</tev:TopicNamespaceLocation>
<wsnt:FixedTopicSet>true</wsnt:FixedTopicSet>
<wstop:TopicSet>
 <tns1:RuleEngine><CellMotionDetector><Motion wstop:topic="true">
  <tt:MessageDescription IsProperty="true">
   <tt:Source><tt:SimpleItemDescription Name="VideoSourceConfigurationToken" Type="tt:ReferenceToken"/>
   <tt:SimpleItemDescription Name="Rule" Type="xs:string"/></tt:Source>
   <tt:Data><tt:SimpleItemDescription Name="IsMotion" Type="xs:boolean"/></tt:Data>
  </tt:MessageDescription></Motion></CellMotionDetector>
  <TamperDetector><Tamper wstop:topic="true"><tt:MessageDescription IsProperty="true">
   <tt:Data><tt:SimpleItemDescription Name="IsTamper" Type="xs:boolean"/></tt:Data></tt:MessageDescription></Tamper>
  </TamperDetector>
  <LineDetector><Crossed wstop:topic="true"><tt:MessageDescription>
   <tt:Data><tt:ElementItemDescription Name="ObjectId" Type="tt:ObjectRefType"/></tt:Data></tt:MessageDescription>
  </Crossed></LineDetector>
 </tns1:RuleEngine>
 <tns1:Device><Trigger><DigitalInput wstop:topic="true"><tt:MessageDescription IsProperty="true">
  <tt:Source><tt:SimpleItemDescription Name="InputToken" Type="tt:ReferenceToken"/></tt:Source>
  <tt:Data><tt:SimpleItemDescription Name="LogicalState" Type="xs:boolean"/></tt:Data></tt:MessageDescription>
 </DigitalInput><Relay wstop:topic="true"/></Trigger></tns1:Device>
 <tnsaxis:VideoSource><ABR wstop:topic="true"/></tnsaxis:VideoSource>
 <tns1:Monitoring><ProcessorUsage wstop:topic="true"/></tns1:Monitoring>
</wstop:TopicSet>
</tev:GetEventPropertiesResponse>"""


def body(xml: str) -> etree._Element:
    return etree.fromstring(ENV.format(xml).encode()).find("{http://www.w3.org/2003/05/soap-envelope}Body")


def notification(topic: str, data: str, op: str = "Changed", ns: str = 'xmlns:t1="http://www.onvif.org/ver10/topics"',
                 utc: str = "2026-11-18T10:00:00Z") -> str:
    return (f'<wsnt:NotificationMessage><wsnt:Topic Dialect="http://www.onvif.org/ver10/tev/topicExpression/'
            f'ConcreteSet" {ns}>{topic}</wsnt:Topic><wsnt:Message><tt:Message UtcTime="{utc}" PropertyOperation="{op}">'
            f'<tt:Source><tt:SimpleItem Name="VideoSourceConfigurationToken" Value="vsc1"/></tt:Source>'
            f'<tt:Data>{data}</tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage>')


# ---------------------------------------------------------------- parsing


def test_topic_set_paths_kinds_and_descriptions():
    topics = {t.path: t for t in parse_topic_set(body(TOPICSET))}
    assert set(topics) == {"tns1:RuleEngine/CellMotionDetector/Motion", "tns1:RuleEngine/TamperDetector/Tamper",
                           "tns1:RuleEngine/LineDetector/Crossed", "tns1:Device/Trigger/DigitalInput",
                           "tns1:Device/Trigger/Relay", "tnsaxis:VideoSource/ABR", "tns1:Monitoring/ProcessorUsage"}
    m = topics["tns1:RuleEngine/CellMotionDetector/Motion"]
    assert m.is_property and m.kind == "motion" and [d["name"] for d in m.data] == ["IsMotion"]
    assert [d["name"] for d in m.source] == ["VideoSourceConfigurationToken", "Rule"]
    assert topics["tns1:RuleEngine/TamperDetector/Tamper"].kind == "tamper"
    crossed = topics["tns1:RuleEngine/LineDetector/Crossed"]
    assert crossed.kind == "line_crossing" and not crossed.is_property and crossed.data[0]["element"]
    assert topics["tns1:Device/Trigger/DigitalInput"].kind == "digital_input"
    assert topics["tns1:Device/Trigger/Relay"].kind == "relay"
    assert topics["tns1:Monitoring/ProcessorUsage"].kind == "system"


def test_notifications_any_prefix_and_states():
    xml = ('<tev:PullMessagesResponse><tev:CurrentTime>2026-11-18T10:00:05Z</tev:CurrentTime>'
           '<tev:TerminationTime>2026-11-18T10:01:05Z</tev:TerminationTime>'
           + notification("t1:RuleEngine/CellMotionDetector/Motion", '<tt:SimpleItem Name="IsMotion" Value="true"/>')
           + notification("tns1:VideoSource/MotionAlarm", '<tt:SimpleItem Name="State" Value="false"/>', "Initialized",
                          ns="", utc="2026-11-18T10:00:01.1234567Z")
           + notification("ax:VideoSource/ABR", '<tt:SimpleItem Name="abr_error" Value="1"/>',
                          ns='xmlns:ax="http://www.axis.com/2009/event/topics"')
           + '</tev:PullMessagesResponse>')
    notes, meta = parse_notifications(body(xml))
    assert meta["termination_time"] == "2026-11-18T10:01:05Z"
    a, b, c = notes
    assert a.topic == "tns1:RuleEngine/CellMotionDetector/Motion" and a.raw_topic.startswith("t1:")
    assert a.kind == "motion" and a.state is True and a.source == {"VideoSourceConfigurationToken": "vsc1"}
    assert b.topic == "tns1:VideoSource/MotionAlarm" and b.operation == "Initialized" and b.state is False
    assert parse_time(b.utc_time).microsecond == 123456  # 7 fraction digits accepted
    assert c.topic == "tnsaxis:VideoSource/ABR" and c.kind == "other"


@pytest.mark.parametrize("path,kind", [
    ("tns1:VideoSource/MotionAlarm", "motion"),
    ("tns1:VideoAnalytics/tnsaxis:MotionDetection", "motion"),
    ("tns1:VideoSource/GlobalSceneChange/ImagingService", "tamper"),
    ("tns1:VideoSource/ImageTooBlurry/AnalyticsService", "tamper"),
    ("tns1:VideoSource/SignalLoss", "video_loss"),
    ("tns1:RuleEngine/FieldDetector/ObjectsInside", "intrusion"),
    ("tns1:RuleEngine/MyRuleDetector/FaceDetect", "face"),
    ("tns1:Device/HardwareFailure/StorageFailure", "storage"),
    ("tns1:Device/Network/NetworkInterface", "system"),
    ("tnshik:Mediacontrol/VideoLoss", "video_loss"),
    ("tns1:PTZController/PTZPresets/Reached", "ptz"),
    ("tns1:Device/IO/VirtualPort", "other"),
    # seen on the jk-1 Illustra cameras (docs/ONVIF_EVENTS_LAB.md)
    ("tns1:VideoSource/OutOfFocusDetect", "tamper"),
    ("tns1:Device/Accelerometer", "tamper"),
    ("tns1:RuleEngine/CounterDetector/Counter", "people_count"),
    ("tns1:VideoSource/ObjectTrackingAlarm", "object"),
    ("tns1:RecordingHistory/Recording/State", "storage"),
    ("tns1:Device/HealthMonitor", "system"),
    ("tns1:Device/Trigger/Relay", "relay"),
])
def test_classification(path, kind):
    assert classify(path) == kind


def test_helpers():
    assert state_of({"LogicalState": "1"}) is True and state_of({"x": "low"}) is None
    assert parse_duration("PT1M30S") == 90 and parse_duration("P1DT1H") == 90000 and parse_duration("x") is None
    assert parse_time("2026-11-18T10:00:00") == datetime(2026, 11, 18, 10, tzinfo=timezone.utc)


# ---------------------------------------------------------------- SOAP flow against a fake camera


class FakeCamera:
    """Digest-protected camera, clock 30 s ahead, ReferenceParameters on its subscriptions, 2 subscription slots."""

    def __init__(self):
        self.now = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
        self.subs: set[str] = set()
        self.seen: list[str] = []
        self.next_id = 0
        self.created_offsets: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        xml = request.content.decode()
        op = etree.QName(etree.fromstring(request.content).find(".//{*}Body")[0]).localname
        self.seen.append(op)
        self.xml = xml
        if op != "GetSystemDateAndTime":
            if "authorization" not in request.headers:
                return httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="cam", nonce="abc", qop="auth"'})
            self._check_wsse(xml)
        cam_now = datetime.now(timezone.utc) + timedelta(seconds=30)
        if op == "GetSystemDateAndTime":
            d = cam_now
            return self.ok(f'<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime><tt:DateTimeType>NTP'
                           f'</tt:DateTimeType><tt:UTCDateTime><tt:Time><tt:Hour>{d.hour}</tt:Hour><tt:Minute>{d.minute}'
                           f'</tt:Minute><tt:Second>{d.second}</tt:Second></tt:Time><tt:Date><tt:Year>{d.year}'
                           f'</tt:Year><tt:Month>{d.month}</tt:Month><tt:Day>{d.day}</tt:Day></tt:Date>'
                           f'</tt:UTCDateTime></tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>')
        if op == "GetDeviceInformation":
            return self.ok("<tds:GetDeviceInformationResponse><tds:Manufacturer>Fake</tds:Manufacturer><tds:Model>F1"
                           "</tds:Model><tds:FirmwareVersion>1.0</tds:FirmwareVersion><tds:SerialNumber>1"
                           "</tds:SerialNumber><tds:HardwareId>h</tds:HardwareId></tds:GetDeviceInformationResponse>")
        if op == "GetServices":
            return self.ok('<tds:GetServicesResponse><tds:Service><tds:Namespace>http://www.onvif.org/ver10/events/wsdl'
                           '</tds:Namespace><tds:XAddr>http://10.9.9.9/onvif/event_service</tds:XAddr><tds:Version>'
                           '<tt:Major>2</tt:Major><tt:Minor>60</tt:Minor></tds:Version></tds:Service>'
                           '</tds:GetServicesResponse>')
        if op == "GetEventProperties":
            return self.ok(TOPICSET)
        if op == "CreatePullPointSubscription":
            if len(self.subs) >= 2:
                return self.fault("ter:ResourceUnknownFault", "too many subscriptions")
            self.next_id += 1
            sid = f"s{self.next_id}"
            self.subs.add(sid)
            return self.ok(f'<tev:CreatePullPointSubscriptionResponse><tev:SubscriptionReference><wsa:Address>'
                           f'http://10.9.9.9/onvif/sub</wsa:Address><wsa:ReferenceParameters>'
                           f'<x:SubId xmlns:x="urn:x">{sid}</x:SubId></wsa:ReferenceParameters>'
                           f'</tev:SubscriptionReference><wsnt:CurrentTime>2026-11-18T10:00:00Z</wsnt:CurrentTime>'
                           f'<wsnt:TerminationTime>2026-11-18T10:01:00Z</wsnt:TerminationTime>'
                           f'</tev:CreatePullPointSubscriptionResponse>')
        # subscription manager calls: must carry wsa:To / wsa:Action and echo the ReferenceParameters
        assert request.url.host == "cam.test", "advertised 10.9.9.9 must be rewritten to the host we reached"
        assert "<wsa:To" in xml and "<wsa:Action" in xml
        sid = etree.fromstring(request.content).findtext(".//{urn:x}SubId")
        if sid not in self.subs:
            return self.fault("wsrf-rw:ResourceUnknownFault", "unknown subscription")
        if op == "PullMessages":
            return self.ok('<tev:PullMessagesResponse><tev:CurrentTime>2026-11-18T10:00:05Z</tev:CurrentTime>'
                           '<tev:TerminationTime>2026-11-18T10:01:05Z</tev:TerminationTime>'
                           + notification("tns1:RuleEngine/CellMotionDetector/Motion",
                                          '<tt:SimpleItem Name="IsMotion" Value="true"/>',
                                          utc=(datetime.now(timezone.utc) + timedelta(seconds=29)).isoformat())
                           + '</tev:PullMessagesResponse>')
        if op == "SetSynchronizationPoint":
            return self.ok("<tev:SetSynchronizationPointResponse/>")
        if op == "Renew":
            return self.ok('<wsnt:RenewResponse><wsnt:TerminationTime>2026-11-18T10:02:00Z</wsnt:TerminationTime>'
                           '</wsnt:RenewResponse>')
        if op == "Unsubscribe":
            self.subs.discard(sid)
            return self.ok("<wsnt:UnsubscribeResponse/>")
        return self.fault("ter:ActionNotSupported", op)

    def _check_wsse(self, xml: str):
        root = etree.fromstring(xml.encode())
        created = root.findtext(".//{%s}Created" % NS["wsu"])
        nonce = base64.b64decode(root.findtext(".//{%s}Nonce" % NS["wsse"]))
        digest = root.findtext(".//{%s}Password" % NS["wsse"])
        assert digest == base64.b64encode(hashlib.sha1(nonce + created.encode() + b"pw").digest()).decode()
        self.created_offsets.append((parse_time(created) - datetime.now(timezone.utc)).total_seconds())

    @staticmethod
    def ok(inner: str) -> httpx.Response:
        return httpx.Response(200, content=ENV.format(inner).encode(),
                              headers={"Content-Type": "application/soap+xml"})

    @staticmethod
    def fault(code: str, reason: str) -> httpx.Response:
        return httpx.Response(400, content=ENV.format(
            f'<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode><s:Value>{code}</s:Value></s:Subcode></s:Code>'
            f'<s:Reason><s:Text xml:lang="en">{reason}</s:Text></s:Reason></s:Fault>').encode())


@pytest.fixture
def fake(monkeypatch):
    fc = FakeCamera()
    real = httpx.AsyncClient

    def client(*a, **kw):
        kw.pop("verify", None)
        return real(transport=httpx.MockTransport(fc.handler), **kw)

    monkeypatch.setattr(cam_mod.httpx, "AsyncClient", client)
    return fc


CAM = {"id": 1, "name": "Fake", "host": "cam.test", "port": 80, "username": "admin", "password": "pw"}


def test_probe_full_flow(fake, tmp_path):
    res = asyncio.run(runner.probe_one(CAM, tmp_path, timeout=5, pull_seconds=1))
    st = res["stages"]
    assert all(st[k]["ok"] for k in ("clock", "identity", "services", "event_properties", "subscribe", "pull_first",
                                     "sync_point", "renew", "unsubscribe")), st
    assert res["identity"]["Manufacturer"] == "Fake"
    assert 29 <= res["clock"]["offset_s"] <= 31
    assert all(25 <= o <= 35 for o in fake.created_offsets), "WS-Security Created must follow the camera clock"
    assert len(res["topics"]) == 7 and res["has_events_service"]
    pp = res["pullpoint"]
    assert pp["granted_s"] == 60 and pp["ref_params"] and pp["sync_point"] and pp["renew"] and pp["unsubscribe"]
    assert pp["messages"] and pp["messages"][0]["kind"] == "motion"
    assert fake.subs == set(), "the subscription is always removed"
    assert (tmp_path / "1-topicset.xml").exists()


def test_limits_counts_slots_and_cleans_up(fake, tmp_path):
    path = asyncio.run(runner.limits(CAM, tmp_path, maximum=4, timeout=5))
    r = json.loads(path.read_text())
    assert r["accepted"] == 2 and r["refused"]["kind"] == "fault" and "ResourceUnknown" in r["refused"]["fault"]
    assert r["usable_after"] == 2 and r["unsubscribed"] == 2 and fake.subs == set()


def test_listen_records_events_with_latency_and_report(fake, tmp_path):
    summary_path, events_path = asyncio.run(runner.listen([CAM], tmp_path, minutes=0.05, timeout=5))
    rows = [json.loads(x) for x in events_path.read_text().splitlines()]
    assert rows and rows[0]["kind"] == "motion" and rows[0]["state"] is True and "password" not in json.dumps(rows)
    assert all(abs(r["latency_s"]) < 3 for r in rows), "camera time corrected by the clock offset"
    s = json.loads(summary_path.read_text())["cameras"][0]
    assert s["subscriptions"] == 1 and s["changes"]["motion"] >= 1 and s["latency"]["n"] >= 1
    assert fake.subs == set()
    asyncio.run(runner.probe([CAM], tmp_path, concurrency=1, timeout=5, pull_seconds=1))
    md = report.build(tmp_path)
    assert "| tns1:" not in md and "`tns1:RuleEngine/CellMotionDetector/Motion` | motion | state" in md
    assert "pw" not in md.replace("PullPoint", "").replace("pulse", "")


def test_subscribe_with_topic_filter_sends_concrete_set(fake):
    async def run():
        async with cam_mod.Camera(id=1, name="Fake", host="cam.test", username="admin", password="pw") as cam:
            await cam.clock()
            await cam.services()
            sub = await cam.subscribe(30, topic_filter="tns1:VideoSource/MotionAlarm|tns1:Device/Trigger/DigitalInput")
            sent = fake.xml
            await cam.unsubscribe(sub)
            return sent

    xml = asyncio.run(run())
    root = etree.fromstring(xml.encode())
    expr = root.find(".//{%s}TopicExpression" % NS["wsnt"])
    assert expr is not None and expr.get("Dialect").endswith("/ConcreteSet")
    assert expr.text == "tns1:VideoSource/MotionAlarm|tns1:Device/Trigger/DigitalInput"
    assert root.find(".//{%s}InitialTerminationTime" % NS["tev"]).text == "PT30S" and fake.subs == set()
