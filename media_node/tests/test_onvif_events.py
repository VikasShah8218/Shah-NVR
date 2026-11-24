"""ONVIF camera events (docs/ONVIF_EVENTS_PLAN.md): topic choice on real camera topic sets (lab fixtures), notification
parsing, edges (lab Q6/Q7), topic filters and the PullPoint client's WS-Addressing (lab Q2)."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from lxml import etree

from app.onvif.event_topics import (EdgeTracker, Notification, kind_topics, parse_notifications, parse_topic_set,
                                    pick_topics, topic_filter, topics_text)
from app.onvif.events import EventClient, InvalidFilter, parse_subscription, wsa_headers
from app.onvif.services import OnvifDevice
from app.onvif.soap import NotSupported

FIX = Path(__file__).parent / "fixtures" / "onvif" / "events"


def topics(name):
    return parse_topic_set(etree.parse(str(FIX / f"{name}_topicset.xml")).getroot())


# ---------------------------------------------------------------- topic choice (lab §4.2 / §5.3)


@pytest.mark.parametrize("camera, expected", [
    ("pro4", {"motion": "tns1:VideoSource/MotionAlarm", "tamper": "tns1:VideoSource/TamperDetect",
              "digital_input": "tns1:Device/Trigger/DigitalInput"}),
    ("pro3", {"motion": "tns1:VideoSource/MotionAlarm", "digital_input": "tns1:Device/Trigger/DigitalInput"}),
    ("isin", {"motion": "tns1:RuleEngine/CellMotionDetector/Motion", "tamper": "tns1:RuleEngine/TamperDetector/Tamper",
              "digital_input": "tns1:Device/Trigger/DigitalInput"}),
    ("axis_vmd", {"motion": "tnsaxis:CameraApplicationPlatform/VMD/Camera1ProfileANY",
                  "tamper": "tns1:VideoSource/GlobalSceneChange/ImagingService",
                  "digital_input": "tns1:Device/Trigger/DigitalInput"}),
    # AXIS with its motion app stopped offers no motion topic: the UI warns (plan §7.1)
    ("axis_novmd", {"tamper": "tns1:VideoSource/GlobalSceneChange/ImagingService",
                    "digital_input": "tns1:Device/Trigger/DigitalInput"}),
])
def test_one_topic_per_kind_on_real_cameras(camera, expected):
    assert pick_topics(topics(camera)) == expected


def test_only_wanted_kinds_are_picked():
    assert pick_topics(topics("isin"), ["motion"]) == {"motion": "tns1:RuleEngine/CellMotionDetector/Motion"}


def test_unknown_vendor_falls_back_to_a_matching_topic():
    t = parse_topic_set(etree.fromstring(
        b'<Body xmlns:wstop="http://docs.oasis-open.org/wsn/t-1" xmlns:tt="http://www.onvif.org/ver10/schema">'
        b'<wstop:TopicSet><v:Alarm xmlns:v="http://vendor.example/topics"><v:VideoMotion wstop:topic="true">'
        b'<tt:MessageDescription IsProperty="true"><tt:Data><tt:SimpleItemDescription Name="State" Type="xs:boolean"/>'
        b'</tt:Data></tt:MessageDescription></v:VideoMotion><v:PTZMotion wstop:topic="true"/></v:Alarm>'
        b'</wstop:TopicSet></Body>'))
    assert pick_topics(t) == {"motion": "v:Alarm/VideoMotion"}  # PTZ "motion" is never picked
    assert t[0].is_property and t[0].data == ["State"] and t[0].uri == "http://vendor.example/topics"


def test_topic_filter_declares_every_prefix():
    chosen = pick_topics(topics("axis_vmd"))
    f = etree.fromstring(topic_filter(chosen, topics("axis_vmd")))
    assert f.get("Dialect").endswith("ConcreteSet")
    assert set(f.text.split("|")) == set(chosen.values())
    assert f.nsmap["tnsaxis"] == "http://www.axis.com/2009/event/topics"
    assert f.nsmap["tns1"] == "http://www.onvif.org/ver10/topics"
    assert topic_filter({}, []) is None


def test_every_offered_topic_of_a_kind_is_listened_to():
    k = kind_topics(topics("isin"))
    assert k["motion"][0] == "tns1:RuleEngine/CellMotionDetector/Motion"
    assert "tns1:VideoSource/MotionAlarm" in k["motion"] and "tns1:RuleEngine/MotionDetector/Motion" in k["motion"]
    assert k["digital_input"] == ["tns1:Device/Trigger/DigitalInput"]
    # tamper keeps one topic: the ISIN copies motion into GlobalSceneChange (fake tamper)
    assert k["tamper"] == ["tns1:RuleEngine/TamperDetector/Tamper"]
    assert topics_text({"motion": ["a", "b"]}) == {"motion": "a, b"}
    f = etree.fromstring(topic_filter(k, topics("isin")))
    assert "tns1:VideoSource/MotionAlarm" in f.text.split("|")


# ---------------------------------------------------------------- notifications


def pull_body(*messages: str) -> etree._Element:
    return etree.fromstring(
        '<s:Body xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tev="http://www.onvif.org/ver10/events/wsdl" '
        'xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:tt="http://www.onvif.org/ver10/schema" '
        'xmlns:tns1="http://www.onvif.org/ver10/topics" xmlns:tnsaxis="http://www.axis.com/2009/event/topics">'
        '<tev:PullMessagesResponse><tev:CurrentTime>2026-11-23T10:00:00Z</tev:CurrentTime>'
        + "".join(messages) + "</tev:PullMessagesResponse></s:Body>")


def msg(topic, op, data, source="", time="2026-11-23T10:00:01Z"):
    items = "".join(f'<tt:SimpleItem Name="{k}" Value="{v}"/>' for k, v in data.items())
    src = "".join(f'<tt:SimpleItem Name="{k}" Value="{v}"/>' for k, v in (source or {}).items())
    op_attr = f' PropertyOperation="{op}"' if op else ""
    return (f'<wsnt:NotificationMessage><wsnt:Topic Dialect="http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet">'
            f'{topic}</wsnt:Topic><wsnt:Message><tt:Message UtcTime="{time}"{op_attr}><tt:Source>{src}</tt:Source>'
            f'<tt:Data>{items}</tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage>')


def test_parse_notifications_of_three_vendors():
    ns = parse_notifications(pull_body(
        msg("tns1:VideoSource/MotionAlarm", "Changed", {"State": "true"}, {"Source": "VideoSourceToken"}),
        msg("tnsaxis:CameraApplicationPlatform/VMD/Camera1ProfileANY", "Changed", {"active": "0"}),
        msg("tns1:Device/Trigger/DigitalInput", "Initialized", {"LogicalState": "false"}, {"InputToken": "DI1"},
            time="2026-11-23T10:00:01.1234567Z"),
    ))
    assert [n.topic for n in ns] == ["tns1:VideoSource/MotionAlarm",
                                     "tnsaxis:CameraApplicationPlatform/VMD/Camera1ProfileANY",
                                     "tns1:Device/Trigger/DigitalInput"]
    assert [n.state for n in ns] == [True, False, False]
    assert [n.operation for n in ns] == ["Changed", "Changed", "Initialized"]
    assert ns[2].source == {"InputToken": "DI1"}
    assert ns[2].utc_time == datetime(2026, 11, 23, 10, 0, 1, 123456, tzinfo=timezone.utc)


def test_topic_prefix_is_resolved_through_the_namespace():
    body = etree.fromstring(
        '<Body xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:tt="http://www.onvif.org/ver10/schema">'
        '<wsnt:NotificationMessage><wsnt:Topic xmlns:x="http://www.onvif.org/ver10/topics">x:VideoSource/MotionAlarm'
        '</wsnt:Topic><wsnt:Message><tt:Message PropertyOperation="Changed"><tt:Data>'
        '<tt:SimpleItem Name="State" Value="true"/></tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage></Body>')
    assert parse_notifications(body)[0].topic == "tns1:VideoSource/MotionAlarm"


# ---------------------------------------------------------------- edges


CHOSEN = {"motion": "tns1:VideoSource/MotionAlarm", "digital_input": "tns1:Device/Trigger/DigitalInput"}


def n(topic, op, state, source=None):
    return Notification(topic=topic, utc_time=None, operation=op, source=source or {}, data={}, state=state)


def actions(tracker, items):
    return [(e.kind, e.action) if e else None for e in (tracker.feed(i) for i in items)]


def test_initialized_never_starts_an_event_and_repeats_are_dropped():
    t = EdgeTracker(CHOSEN)
    m = "tns1:VideoSource/MotionAlarm"
    assert actions(t, [
        n(m, "Initialized", True),   # old state (Q6): no event
        n(m, "Changed", True),       # same value (Q7)
        n(m, "Changed", False),      # end of a motion we never started: still an end (it was on)
        n(m, "Changed", False),      # repeat
        n(m, "Changed", True),
        n(m, "Changed", True),       # repeat
        n(m, "Changed", False),
    ]) == [None, None, ("motion", "end"), None, ("motion", "start"), None, ("motion", "end")]


def test_flex4k_reports_every_change_as_initialized():
    """Illustra Flex4K Box SS004.01.03 on jk-1 (2026-11-23): no Changed messages at all."""
    t = EdgeTracker(CHOSEN)
    m = "tns1:VideoSource/MotionAlarm"
    assert actions(t, [
        n(m, "Initialized", False),  # starting state
        n(m, "Initialized", True),
        n(m, "Initialized", False),
        n(m, "Initialized", True),
        n(m, "Initialized", True),   # repeat
    ]) == [None, ("motion", "start"), ("motion", "end"), ("motion", "start"), None]


def test_end_without_a_known_start_is_ignored():
    t = EdgeTracker(CHOSEN)
    assert actions(t, [n("tns1:VideoSource/MotionAlarm", "Changed", False)]) == [None]


def test_inputs_are_tracked_per_token_and_labelled():
    t = EdgeTracker(CHOSEN)
    di = "tns1:Device/Trigger/DigitalInput"
    e1 = t.feed(n(di, "Changed", True, {"InputToken": "DI1"}))
    e2 = t.feed(n(di, "Changed", True, {"InputToken": "DI2"}))
    assert (e1.action, e1.label, e2.action, e2.label) == ("start", "Input DI1", "start", "Input DI2")
    assert e1.key != e2.key


def test_reinitialized_off_closes_a_missed_end():
    t = EdgeTracker(CHOSEN)
    m = "tns1:VideoSource/MotionAlarm"
    t.feed(n(m, "Changed", True))
    assert t.feed(n(m, "Initialized", False)).action == "end"  # after a resubscribe


def test_other_topics_only_with_the_switch_and_never_noise():
    other = "tns1:RuleEngine/LineDetector/Crossed"
    assert EdgeTracker(CHOSEN).feed(n(other, None, None)) is None
    t = EdgeTracker(CHOSEN, store_other=True)
    e = t.feed(n(other, None, None))
    assert (e.kind, e.action, e.label) == ("onvif", "moment", "LineDetector/Crossed")
    assert t.feed(n("tns1:PTZController/PTZPosition", "Changed", None)) is None  # Q8
    assert t.feed(n("tns1:Monitoring/ProcessorUsage", "Changed", None)) is None  # Q7
    # a second motion topic would mark the same motion twice (D5)
    assert t.feed(n("tns1:RuleEngine/MotionDetector/Motion", "Changed", True)) is None


def test_isin_lists_cell_motion_but_sends_only_motion_alarm():
    """ISIN-B05M031-N V2.0.0.20210812 on shah-ho-1 (2026-11-24): CellMotionDetector is in the TopicSet but never sent;
    motion comes on VideoSource/MotionAlarm while RuleEngine/MotionDetector/Motion stays false."""
    t = EdgeTracker(kind_topics(topics("isin")))
    cell, alarm, rule = ("tns1:RuleEngine/CellMotionDetector/Motion", "tns1:VideoSource/MotionAlarm",
                         "tns1:RuleEngine/MotionDetector/Motion")
    src = {"Source": "VideoSource"}
    assert actions(t, [
        n(alarm, "Initialized", True, src),
        n(rule, "Initialized", False, {"Rule": "MyMotionDetectorRule"}),
        n(alarm, "Changed", False, src),
        n(alarm, "Changed", True, src),
        n(alarm, "Changed", False, src),
    ]) == [None, None, ("motion", "end"), ("motion", "start"), ("motion", "end")]
    assert t.kind(cell) == "motion"


def test_two_topics_of_one_motion_give_one_event():
    t = EdgeTracker({"motion": ["tns1:RuleEngine/CellMotionDetector/Motion", "tns1:VideoSource/MotionAlarm"]})
    cell, alarm = "tns1:RuleEngine/CellMotionDetector/Motion", "tns1:VideoSource/MotionAlarm"
    out = [t.feed(i) for i in [n(cell, "Changed", True), n(alarm, "Changed", True), n(cell, "Changed", False),
                               n(alarm, "Changed", False)]]
    assert [(e.action, e.key) if e else None for e in out] == [("start", "motion"), None, None, ("end", "motion")]


# ---------------------------------------------------------------- PullPoint client


def test_subscription_reference_both_addressing_versions():
    for wsa in ("http://www.w3.org/2005/08/addressing", "http://schemas.xmlsoap.org/ws/2004/08/addressing"):
        body = etree.fromstring(
            f'<s:Body xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tev="http://www.onvif.org/ver10/events/wsdl" '
            f'xmlns:a="{wsa}"><tev:CreatePullPointSubscriptionResponse><tev:SubscriptionReference>'
            f'<a:Address>http://10.0.0.5/onvif/services/sub?id=7</a:Address><a:ReferenceParameters>'
            f'<dom:SubscriptionId xmlns:dom="http://www.axis.com/2009/event">7</dom:SubscriptionId>'
            f'</a:ReferenceParameters></tev:SubscriptionReference></tev:CreatePullPointSubscriptionResponse></s:Body>')
        address, params = parse_subscription(body)
        assert address == "http://10.0.0.5/onvif/services/sub?id=7"
        assert "SubscriptionId" in params and ">7<" in params


def test_wsa_headers_echo_reference_parameters():
    h = wsa_headers("urn:act", "http://cam/sub?a=1&b=2", "<x:Id xmlns:x='urn:x'>9</x:Id>")
    root = etree.fromstring(f'<H xmlns:s="http://www.w3.org/2003/05/soap-envelope">{h}</H>')
    assert root.findtext("{http://www.w3.org/2005/08/addressing}To") == "http://cam/sub?a=1&b=2"
    assert root.findtext("{http://www.w3.org/2005/08/addressing}Action") == "urn:act"
    assert root.findtext("{urn:x}Id") == "9"


class FakeCamera:
    """Answers the event calls like a lab camera; records each request."""

    def __init__(self, refuse_filter=False):
        self.calls: list[tuple[str, str]] = []
        self.refuse_filter = refuse_filter

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        op = next(o for o in ("GetServices", "GetEventProperties", "CreatePullPointSubscription", "PullMessages",
                              "Renew", "Unsubscribe", "SetSynchronizationPoint") if f":{o}" in body)
        self.calls.append((op, body))
        env = ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
               'xmlns:tds="http://www.onvif.org/ver10/device/wsdl" xmlns:tev="http://www.onvif.org/ver10/events/wsdl" '
               'xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" xmlns:wsa="http://www.w3.org/2005/08/addressing" '
               'xmlns:tt="http://www.onvif.org/ver10/schema" xmlns:tns1="http://www.onvif.org/ver10/topics"><s:Body>{}'
               '</s:Body></s:Envelope>')
        if op == "GetServices":  # the camera advertises another address (NAT): we keep the host we reached
            inner = ('<tds:GetServicesResponse><tds:Service><tds:Namespace>http://www.onvif.org/ver10/events/wsdl'
                     '</tds:Namespace><tds:XAddr>http://172.16.0.9/onvif/event_service</tds:XAddr></tds:Service>'
                     '</tds:GetServicesResponse>')
        elif op == "GetEventProperties":  # the lab saved only the Body element
            return httpx.Response(200, content=b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
                                  + (FIX / "pro3_topicset.xml").read_bytes() + b"</s:Envelope>")
        elif op == "CreatePullPointSubscription":
            if self.refuse_filter and "TopicExpression" in body:
                return httpx.Response(400, content=env.format(
                    '<s:Fault><s:Code><s:Value>s:Sender</s:Value></s:Code><s:Reason><s:Text>InvalidFilterFault'
                    '</s:Text></s:Reason></s:Fault>').encode())
            inner = ('<tev:CreatePullPointSubscriptionResponse><tev:SubscriptionReference>'
                     '<wsa:Address>http://172.16.0.9/onvif/sub/1</wsa:Address><wsa:ReferenceParameters>'
                     '<r:Id xmlns:r="urn:ref">1</r:Id></wsa:ReferenceParameters></tev:SubscriptionReference>'
                     '</tev:CreatePullPointSubscriptionResponse>')
        elif op == "PullMessages":
            inner = etree.tostring(pull_body(msg("tns1:VideoSource/MotionAlarm", "Changed", {"State": "true"}))[0],
                                   encoding="unicode")
        else:
            inner = f"<tev:{op}Response/>"
        return httpx.Response(200, content=env.format(inner).encode())


def with_client(cam, fn):
    async def go():
        async with OnvifDevice("192.0.2.10", 80, "admin", "pw") as dev:
            dev._http._transport = httpx.MockTransport(cam)
            dev.soap.http = dev._http
            return await fn(EventClient(dev))

    return asyncio.run(go())


def test_pullpoint_round_trip_uses_our_host_and_ws_addressing():
    cam = FakeCamera()

    async def fn(c: EventClient):
        offered = await c.properties()
        sub = await c.subscribe(60, topic_filter(pick_topics(offered), offered))
        got = await c.pull(sub, wait=1)
        await c.renew(sub)
        await c.unsubscribe(sub)
        return sub, got

    sub, got = with_client(cam, fn)
    assert sub.address == "http://192.0.2.10/onvif/sub/1"  # rehosted
    assert [m.state for m in got] == [True]
    ops = [op for op, _ in cam.calls]
    assert ops == ["GetServices", "GetEventProperties", "CreatePullPointSubscription", "PullMessages", "Renew",
                   "Unsubscribe"]
    for op, body in cam.calls[3:]:
        assert "<wsa:To" in body and "http://192.0.2.10/onvif/sub/1" in body and ">1</r:Id>" in body, op
        assert "UsernameToken" in body
    assert "TopicExpression" in cam.calls[2][1]


def test_refused_filter_is_reported():
    cam = FakeCamera(refuse_filter=True)

    async def fn(c: EventClient):
        offered = await c.properties()
        with pytest.raises(InvalidFilter):
            await c.subscribe(60, topic_filter(pick_topics(offered), offered))
        return await c.subscribe(60)  # without a filter it works

    assert with_client(cam, fn).address.endswith("/onvif/sub/1")


def test_no_event_service_is_not_supported():
    def cam(request):
        return httpx.Response(200, content=(
            b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl">'
            b'<s:Body><tds:GetServicesResponse/><tds:GetCapabilitiesResponse/></s:Body></s:Envelope>'))

    async def fn(c):
        with pytest.raises(NotSupported):
            await c.events_url()

    with_client(cam, fn)
