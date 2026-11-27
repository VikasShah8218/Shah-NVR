"""Camera analytics events (docs/ONVIF_ANALYTICS_EVENTS_PLAN.md): the catalogue on real topic sets (lab fixtures), what
a message says (classify), labels, edges per kind + rule (A2/A3/A6), and on the node: moment merge ×N and the cap (A4).

Message shapes are the ones seen on the ISIN-B05M031-N at shah-ho-1 (2026-11-26: rule names in the Source, `ObjectId`
on LineDetector/Crossed, Initialized false for every rule) and the Pro4 TopicSet (RuleType / ObjectClass / ...)."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from lxml import etree
from tortoise import Tortoise

from app.events.models import EventWindow
from app.node.utils import runtime
from app.onvif import event_watch as ew
from app.onvif.event_analytics import analytics_kinds, analytics_topics, classify, label, matcher_for, rule_kind
from app.onvif.event_topics import EdgeTracker, Notification, kind_topics, offered_kinds, parse_topic_set
from settings.settings import settings

FIX = Path(__file__).parent / "fixtures" / "onvif" / "events"
ISIN_SRC = {"VideoSourceConfigurationToken": "VideoSource", "VideoAnalyticsConfigurationToken": "VideoAnalyticsToken"}
LINE, FIELD = "tns1:RuleEngine/LineDetector/Crossed", "tns1:RuleEngine/FieldDetector/ObjectsInside"
TRACK = "tns1:VideoSource/ObjectTrackingAlarm"


def paths(name):
    return [t.path for t in parse_topic_set(etree.parse(str(FIX / f"{name}_topicset.xml")).getroot())]


def n(topic, op, data, rule=None, source=None):
    src = source if source is not None else {**ISIN_SRC, **({"Rule": rule} if rule else {})}
    return Notification(topic=topic, utc_time=None, operation=op, source=src, data=data, state=None)


def feed(t, items):
    return [(e.kind, e.action) if e else None for e in (t.feed(i) for i in items)]


# ---------------------------------------------------------------- catalogue


def test_isin_offers_the_rule_engine_analytics():
    assert analytics_kinds(paths("isin")) == ["line_crossing", "intrusion", "loitering", "object_left", "person",
                                              "face", "counting"]
    topics = analytics_topics(paths("isin"))
    assert topics["intrusion"] == [FIELD]  # ObjectsOutside is the same rule the other way: never used
    assert topics["line_crossing"] == [LINE]


def test_pro4_one_topic_many_kinds_plus_face_audio_counting():
    topics = analytics_topics(paths("pro4"))
    for k in ("line_crossing", "intrusion", "loitering", "object_left", "person"):
        assert TRACK in topics[k]
    assert topics["face"] == ["tns1:VideoSource/FaceAlarm"]
    assert topics["audio_alarm"] == ["tns1:AudioSource/AudioAlert"]
    assert topics["counting"] == ["tns1:VideoSource/PersonTrackingAlarm"]


def test_cameras_without_analytics_offer_none():
    assert analytics_kinds(paths("pro3")) == []
    assert analytics_kinds(paths("axis_vmd")) == []
    assert analytics_kinds(paths("axis_novmd")) == []


def test_phase_one_topics_are_never_analytics():
    for t in ("tns1:RuleEngine/CellMotionDetector/Motion", "tns1:RuleEngine/MotionDetector/Motion",
              "tns1:RuleEngine/TamperDetector/Tamper", "tns1:VideoSource/MotionAlarm",
              "tns1:RuleEngine/FieldDetector/ObjectsOutside"):
        assert matcher_for(t) is None, t


def test_offered_kinds_lists_basic_then_analytics():
    offered = parse_topic_set(etree.parse(str(FIX / "isin_topicset.xml")).getroot())
    assert offered_kinds(offered)[:3] == ["motion", "tamper", "digital_input"]
    assert "line_crossing" in offered_kinds(offered)
    # null / the basic kinds never listen to analytics (A5)
    assert set(kind_topics(offered)) == {"motion", "tamper", "digital_input"}
    assert kind_topics(offered, ["intrusion"]) == {"intrusion": [FIELD]}


@pytest.mark.parametrize("rule_type, kind", [
    ("tt:LineDetector", "line_crossing"), ("LineCrossing", "line_crossing"), ("Tripwire", "line_crossing"),
    ("tt:FieldDetector", "intrusion"), ("Intrusion", "intrusion"), ("ObjectEntry", "intrusion"),
    ("ZoneExit", "intrusion"), ("Loitering", "loitering"), ("tt:LoiteringDetector", "loitering"),
    ("AbandonedObject", "object_left"), ("ObjectRemoved", "object_left"), ("tt:ObjectDetector", "object_left"),
    ("tt:HumanDetector", "person"), ("PersonDetection", "person"), ("tt:CounterDetector", "counting"),
    ("tt:FaceDetector", "face"), ("GlassBreak", "audio_alarm"), ("Scream", "audio_alarm"),
    ("tt:CellMotionDetector", None), ("tt:TamperDetector", None), ("", None), (None, None),
])
def test_rule_type_to_kind(rule_type, kind):
    assert rule_kind(rule_type) == kind


# ---------------------------------------------------------------- classify + label


def test_classify_pro4_object_tracking():
    a = classify(TRACK, {"Source": "VideoSource"},
                 {"RuleType": "LineCrossing", "RuleName": "Gate line", "ObjectClass": "Person", "Confidence": "0.87",
                  "Direction": "LeftToRight", "State": "true", "TrackingId": "42",
                  "BoundingBoxes": "0.1,0.2,0.3,0.4;0.5,0.5,0.6,0.7;1;2;3;4"})
    assert (a.kind, a.read, a.state, a.rule, a.track) == ("line_crossing", "pulse", True, "Gate line", "42")
    assert a.data == {"rule": "Gate line", "rule_type": "LineCrossing", "object": "Person", "confidence": 87,
                      "direction": "LeftToRight", "boxes": ["0.1,0.2,0.3,0.4", "0.5,0.5,0.6,0.7", "1", "2"]}
    assert label("line_crossing", a.data) == "Line crossing · Gate line · Person (87 %)"


def test_camera_strings_are_bounded():
    a = classify(TRACK, {}, {"RuleType": "Intrusion", "RuleName": "x" * 500, "ObjectClass": "<b>" * 50,
                             "Confidence": "1e9"})
    assert len(a.rule) == 64 and len(a.data["object"]) == 64 and "confidence" not in a.data
    assert len(label("intrusion", a.data, 99999)) <= 128


def test_counting_label_and_merged_count():
    a = classify("tns1:VideoSource/PersonTrackingAlarm", {}, {"InCount": "5", "OutCount": "3", "NetCount": "2"})
    assert (a.kind, a.read, a.value) == ("counting", "value", "2")
    assert label("counting", a.data) == "People counting · in 5 / out 3 / net 2"
    assert label("intrusion", {"rule": "Parking"}, 12) == "Intrusion · Parking ×12"


# ---------------------------------------------------------------- edges


def test_isin_line_crossing_is_a_moment_per_new_object_and_resends_are_dropped():
    t = EdgeTracker(kind_topics(parse_topic_set(etree.parse(str(FIX / "isin_topicset.xml")).getroot()),
                                ["line_crossing"]))
    assert feed(t, [
        n(LINE, "Initialized", {"ObjectId": "0"}, "MyLineDetector1"),  # starting state
        n(LINE, "Changed", {"ObjectId": "17"}, "MyLineDetector1"),
        n(LINE, "Initialized", {"ObjectId": "17"}, "MyLineDetector1"),  # ISIN resends every state (lab Q14)
        n(LINE, "Changed", {"ObjectId": "18"}, "MyLineDetector1"),
        n(LINE, "Changed", {"ObjectId": "0"}, "MyLineDetector1"),  # reset: nothing
        n(LINE, "Changed", {"ObjectId": "5"}, "MyLineDetector2"),  # another line: its own event
    ]) == [None, ("line_crossing", "moment"), None, ("line_crossing", "moment"), None, ("line_crossing", "moment")]


def test_isin_intrusion_is_a_range_per_rule():
    t = EdgeTracker({"intrusion": [FIELD]})
    out = [t.feed(i) for i in [
        n(FIELD, "Initialized", {"IsInside": "false"}, "MyFieldDetector1"),
        n(FIELD, "Changed", {"IsInside": "true"}, "MyFieldDetector1"),
        n(FIELD, "Changed", {"IsInside": "true"}, "MyFieldDetector2"),
        n(FIELD, "Changed", {"IsInside": "true"}, "MyFieldDetector1"),  # repeat
        n(FIELD, "Changed", {"IsInside": "false"}, "MyFieldDetector1"),
    ]]
    assert [(e.action, e.key, e.label) if e else None for e in out] == [
        None,
        ("start", "intrusion|MyFieldDetector1", "Intrusion · MyFieldDetector1"),
        ("start", "intrusion|MyFieldDetector2", "Intrusion · MyFieldDetector2"),
        None,
        ("end", "intrusion|MyFieldDetector1", "Intrusion · MyFieldDetector1"),
    ]


def test_face_property_rising_edge_is_a_moment():
    face = "tns1:RuleEngine/FaceDetector/Face"
    t = EdgeTracker({"face": [face]})
    assert feed(t, [n(face, "Initialized", {"IsFace": "false"}, "R"), n(face, "Changed", {"IsFace": "true"}, "R"),
                    n(face, "Changed", {"IsFace": "true"}, "R"), n(face, "Changed", {"IsFace": "false"}, "R"),
                    n(face, "Changed", {"IsFace": "true"}, "R")]) == [None, ("face", "moment"), None, None,
                                                                       ("face", "moment")]


def test_pro4_kind_comes_from_rule_type_and_only_chosen_kinds_count():
    t = EdgeTracker({"line_crossing": [TRACK], "intrusion": [TRACK]})
    src = {"Source": "VideoSource"}
    line = {"RuleType": "LineCrossing", "RuleName": "Gate", "State": "true", "TrackingId": "1"}
    zone = {"RuleType": "Intrusion", "RuleName": "Yard", "ObjectClass": "Vehicle"}
    loiter = {"RuleType": "Loitering", "RuleName": "Door", "State": "true"}
    out = [t.feed(i) for i in [
        n(TRACK, None, line, source=src),
        n(TRACK, None, {**line, "State": "false"}, source=src),  # end of a moment pulse: nothing
        n(TRACK, None, {**zone, "State": "true", "TrackingId": "7"}, source=src),
        n(TRACK, None, {**zone, "State": "true", "TrackingId": "8"}, source=src),  # 2nd object, same rule: same range
        n(TRACK, None, {**zone, "State": "false", "TrackingId": "7"}, source=src),
        n(TRACK, None, {**zone, "State": "false", "TrackingId": "8"}, source=src),
        n(TRACK, None, loiter, source=src),  # loitering is off on this camera
    ]]
    assert [(e.kind, e.action, e.key) if e else None for e in out] == [
        ("line_crossing", "moment", "line_crossing|Gate"), None,
        ("intrusion", "start", "intrusion|Yard"), None, None, ("intrusion", "end", "intrusion|Yard"), None]
    assert out[2].label == "Intrusion · Yard · Vehicle"


def test_unknown_rule_type_is_a_generic_event_only_with_store_other():
    unknown = n(TRACK, None, {"RuleType": "Crowd", "RuleName": "Hall", "State": "true"}, source={})
    assert EdgeTracker({"line_crossing": [TRACK]}).feed(unknown) is None
    e = EdgeTracker({"line_crossing": [TRACK]}, store_other=True).feed(unknown)
    assert e.kind == "onvif"


def test_analytics_without_their_kind_stay_generic_with_store_other():
    t = EdgeTracker({"motion": ["tns1:VideoSource/MotionAlarm"]}, store_other=True)
    e = t.feed(n(LINE, "Changed", {"ObjectId": "3"}, "L1"))
    assert e.kind == "onvif"


# ---------------------------------------------------------------- node: merge ×N and the cap (A4)

T0 = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
EVENTS = {"pre": 10, "post": 30, "marking": True, "max": 300}


@pytest.fixture
def node():
    saved = (runtime.assignments, runtime.node_id)
    runtime.assignments = {1: {"camera_id": 1, "streams": [], "recording": {"mode": "event", "events": EVENTS}}}
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


def line_edge(obj="17", rule="Gate"):
    t = EdgeTracker({"line_crossing": [LINE]})
    t.feed(n(LINE, "Initialized", {"ObjectId": "0"}, rule))
    return t.feed(n(LINE, "Changed", {"ObjectId": obj}, rule))


def test_crossings_within_post_merge_into_one_event_with_a_count(node, tmp_path):
    async def go():
        st = ew.EventState()
        for i in range(12):
            await ew.apply_edge(1, line_edge(str(i + 1)), T0 + timedelta(seconds=5 * i), st)
        await ew.apply_edge(1, line_edge("99", rule="Back door"), T0, st)
        rows = await EventWindow.all().order_by("id")
        assert [(w.type, w.label, (w.data or {}).get("count")) for w in rows] == [
            ("line_crossing", "Line crossing · Gate ×12", 12), ("line_crossing", "Line crossing · Back door", None)]
        assert rows[0].end_time == T0 + timedelta(seconds=55) and rows[0].start_time == T0
        assert rows[0].data["topic"] == LINE

    run_db(tmp_path, go)


def test_over_the_cap_events_are_counted_not_stored(node, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ONVIF_ANALYTICS_PER_MINUTE", 3)
    ew.set_status(1, "ok", topics={}, offered=[])

    async def go():
        st = ew.EventState()
        for i in range(5):  # different rules: no merge, each a new event
            await ew.apply_edge(1, line_edge("1", rule=f"L{i}"), T0, st)
        assert await EventWindow.all().count() == 3
        assert ew._status[1]["detail"].startswith("busy: 2 analytics event(s) not stored")
        # motion is never capped
        from app.onvif.event_topics import Edge
        await ew.apply_edge(1, Edge("motion", "motion", "start", None, {}, None), T0, st)
        assert await EventWindow.filter(type="motion").count() == 1
        # a quiet minute clears "busy"
        assert ew.over_cap(1, "motion", st, mono=st.dropped_at + 61) is False
        assert ew._status[1]["detail"] is None

    run_db(tmp_path, go)


def test_analytics_kinds_are_accepted_from_central():
    cam = {"onvif_host": "192.0.2.1", "onvif_events": {"kinds": ["motion", "line_crossing", "bogus"]}}
    assert ew.config_of(1, cam).kinds == ("motion", "line_crossing")
