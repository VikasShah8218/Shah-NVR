"""ONVIF event topics: parse a camera's TopicSet and its notifications, pick one topic per event kind, and turn the
message stream into edges (start / end / moment). Pure functions, no I/O (docs/ONVIF_EVENTS_PLAN.md §3-§4).

Rules from the lab on 38 real cameras (docs/ONVIF_EVENTS_LAB.md):
- several topics report the same motion: use ONE per kind, in priority order (D5);
- the first `Initialized` message only sets the starting state (its time can be weeks old: Q6); later ones count
  like `Changed` (the Illustra Flex4K reports every motion change as `Initialized`);
- Pro3/Pro4 resend unchanged values every 8-64 s: only changes count (Q7);
- PTZ position, health and recording topics are noise: never stored (D10, Q8).

Topic paths are written with canonical prefixes ("tns1:VideoSource/MotionAlarm") whatever prefix the camera used;
matching ignores the prefix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from lxml import etree

NS = {
    "tt": "http://www.onvif.org/ver10/schema",
    "tev": "http://www.onvif.org/ver10/events/wsdl",
    "wsnt": "http://docs.oasis-open.org/wsn/b-2",
    "wstop": "http://docs.oasis-open.org/wsn/t-1",
    "wsa": "http://www.w3.org/2005/08/addressing",
    "wsa04": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
}
# topic namespace URI -> canonical prefix (unknown URIs keep the camera's prefix)
PREFIXES = {
    "http://www.onvif.org/ver10/topics": "tns1",
    "http://www.axis.com/2009/event/topics": "tnsaxis",
    "http://www.hikvision.com/2011/event/topics": "tnshik",
    "http://www.dahua.com/2011/event/topics": "tnsdahua",
    "http://www.hanwha.com/onvif/event/topics": "tnssamsung",
    "http://www.samsungcctv.com/2011/event/topics": "tnssamsung",
    "http://www.uniview.com/ver10/topics": "tnsuniview",
    "http://www.boschsecurity.com/2013/event/topics": "tnsbosch",
    "http://www.tyco.com/2016/event/topics": "tnstyco",
    "http://www.illustracameras.com/event/topics": "tnsillustra",
    "http://www.americandynamics.net/onvif/topics": "tnsad",
}
_WSTOP_TOPIC = f"{{{NS['wstop']}}}topic"
_MESSAGE_DESCRIPTION = f"{{{NS['tt']}}}MessageDescription"

KINDS = ("motion", "tamper", "digital_input")

# One topic per kind: the first one the camera offers wins (lab §5.3).
PRIORITY: dict[str, tuple[str, ...]] = {
    "motion": ("tns1:RuleEngine/CellMotionDetector/Motion",
               "tnsaxis:CameraApplicationPlatform/VMD/Camera1ProfileANY",
               "tns1:VideoSource/MotionAlarm",
               "tns1:RuleEngine/MotionDetector/Motion"),
    "tamper": ("tns1:RuleEngine/TamperDetector/Tamper",
               "tns1:VideoSource/GlobalSceneChange/ImagingService",
               "tns1:VideoSource/GlobalSceneChange/AnalyticsService",
               "tns1:VideoSource/TamperDetect"),
    "digital_input": ("tns1:Device/Trigger/DigitalInput",),
}
# Cameras whose topics are not in the lists above (other vendors): the first offered topic matching the kind.
FALLBACK: dict[str, str] = {
    "motion": r"motion|vmd",
    "tamper": r"tamper|scenechange|defocus|blurry|sabotage|videoblind|occlusion",
    "digital_input": r"digitalinput|device/trigger|/io/input|alarmin|inputport|externalinput",
}
# Never stored as events, not even with "store other camera events" (D10).
NEVER = re.compile(
    r"ptz|monitoring|healthmonitor|recordingconfig|recordinghistory|recordingjob|hardwarefailure|virtualinput|"
    r"processorusage|lastreboot|backup|configurationchanged|profilechanged|networkstatus|usermanagement|"
    r"/media/|relay|digitaloutput", re.I)

TRUE = {"true", "1", "active", "on", "yes", "alarm", "detected", "open"}
FALSE = {"false", "0", "inactive", "off", "no", "normal", "idle", "closed"}
STATE_NAMES = ("IsMotion", "State", "IsTamper", "LogicalState", "active", "Active", "Value", "IsInside", "Alarm",
               "Triggered", "IsActive")


def plain(path: str) -> str:
    """'tns1:VideoSource/MotionAlarm' -> 'videosource/motionalarm' (prefixes dropped, lower case)."""
    return re.sub(r"\b[A-Za-z0-9_-]+:", "", path).lower()


def _prefix_for(uri: str | None, fallback: str | None) -> str:
    return PREFIXES.get(uri or "", fallback or "ns")


# ---------------------------------------------------------------- TopicSet (GetEventProperties)


@dataclass
class TopicInfo:
    path: str  # canonical "tns1:RuleEngine/CellMotionDetector/Motion"
    is_property: bool  # stateful (Initialized / Changed / Deleted) or a pulse
    uri: str | None = None  # namespace of the first path element (for topic filters)
    data: list[str] = field(default_factory=list)  # data item names


def parse_topic_set(body: etree._Element) -> list[TopicInfo]:
    """GetEventPropertiesResponse body -> every leaf topic."""
    topic_set = body.find(".//wstop:TopicSet", NS)
    if topic_set is None:
        return []
    out: list[TopicInfo] = []

    def walk(el: etree._Element, parts: list[str], root: tuple[str, str | None] | None):
        for child in el:
            if not isinstance(child.tag, str) or child.tag == _MESSAGE_DESCRIPTION:
                continue
            q = etree.QName(child)
            here = root or (_prefix_for(q.namespace, child.prefix), q.namespace)
            path = parts + [q.localname]
            desc = child.find(_MESSAGE_DESCRIPTION)
            if child.get(_WSTOP_TOPIC) == "true" or desc is not None:
                data = desc.find("tt:Data", NS) if desc is not None else None
                out.append(TopicInfo(
                    path=f"{here[0]}:{'/'.join(path)}", uri=here[1],
                    is_property=desc is not None and desc.get("IsProperty") == "true",
                    data=[d.get("Name") for d in (data if data is not None else []) if isinstance(d.tag, str) and d.get("Name")]))
            walk(child, path, here)

    walk(topic_set, [], None)
    return out


def pick_topics(offered: list[TopicInfo], kinds=KINDS) -> dict[str, str]:
    """{kind: canonical topic path} for the wanted kinds the camera offers (one per kind)."""
    by_plain = {plain(t.path): t.path for t in offered}
    chosen: dict[str, str] = {}
    for kind in kinds:
        for want in PRIORITY.get(kind, ()):
            if plain(want) in by_plain:
                chosen[kind] = by_plain[plain(want)]
                break
        else:
            rx = FALLBACK.get(kind)
            for t in offered:
                p = plain(t.path)
                if rx and re.search(rx, p) and not NEVER.search(p):
                    chosen[kind] = t.path
                    break
    return chosen


def offered_kinds(offered: list[TopicInfo]) -> list[str]:
    return list(pick_topics(offered, KINDS))


def topic_filter(chosen: dict[str, str], offered: list[TopicInfo]) -> str | None:
    """A ConcreteSet TopicExpression element for the chosen topics (cameras that honour it send less; we filter on
    our side anyway: lab Q5)."""
    if not chosen:
        return None
    uris = {t.path: t.uri for t in offered}
    decl: dict[str, str] = {}
    for path in chosen.values():
        prefix = path.split(":", 1)[0]
        uri = uris.get(path) or next((u for u, p in PREFIXES.items() if p == prefix), None)
        if not uri:
            return None
        decl[prefix] = uri
    xmlns = " ".join(f'xmlns:{p}="{u}"' for p, u in sorted(decl.items()))
    return (f'<wsnt:TopicExpression xmlns:wsnt="{NS["wsnt"]}" {xmlns} '
            f'Dialect="http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet">'
            f'{"|".join(sorted(set(chosen.values())))}</wsnt:TopicExpression>')


# ---------------------------------------------------------------- notifications (PullMessages)


@dataclass
class Notification:
    topic: str  # canonical path
    utc_time: datetime | None  # camera clock
    operation: str | None  # Initialized / Changed / Deleted (properties); None = pulse
    source: dict
    data: dict
    state: bool | None  # on / off when the data carries such a value


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        v = value.strip().replace("Z", "+00:00")
        if "." in v:  # some cameras send 7 fraction digits
            head, frac = v.split(".", 1)
            digits = "".join(ch for ch in frac if ch.isdigit())
            v = f"{head}.{digits[:6]}{frac[len(digits):]}"
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def canonical_topic(el: etree._Element) -> str:
    """wsnt:Topic text -> canonical path: its prefix is resolved through the element's namespaces."""
    raw = (el.text or "").strip().split("|")[0]
    pieces = raw.split("/")
    first = pieces[0].split(":", 1)
    if len(first) == 2:
        prefix = _prefix_for(el.nsmap.get(first[0]), first[0])
        pieces[0] = first[1]
    else:
        prefix = "ns"
    return f"{prefix}:{'/'.join(p.split(':', 1)[-1] for p in pieces)}"


def _items(node: etree._Element | None) -> dict:
    out = {}
    for it in node if node is not None else []:
        if isinstance(it.tag, str) and it.get("Name") and etree.QName(it).localname == "SimpleItem":
            out[it.get("Name")] = it.get("Value")
    return out


def state_of(data: dict) -> bool | None:
    ordered = [k for k in STATE_NAMES if k in data] + [k for k in data if k not in STATE_NAMES]
    for k in ordered:
        v = str(data[k]).strip().lower()
        if v in TRUE:
            return True
        if v in FALSE:
            return False
    return None


def parse_notifications(body: etree._Element) -> list[Notification]:
    out = []
    for nm in body.iter(f"{{{NS['wsnt']}}}NotificationMessage"):
        topic_el = nm.find("wsnt:Topic", NS)
        if topic_el is None or not (topic_el.text or "").strip():
            continue
        msg = nm.find("wsnt:Message/tt:Message", NS)
        if msg is None:  # some cameras nest it differently
            wrapper = nm.find("wsnt:Message", NS)
            msg = next((e for e in (wrapper.iter() if wrapper is not None else [])
                        if e is not wrapper and isinstance(e.tag, str) and etree.QName(e).localname == "Message"), None)
        source = _items(msg.find("tt:Source", NS)) if msg is not None else {}
        data = _items(msg.find("tt:Data", NS)) if msg is not None else {}
        out.append(Notification(topic=canonical_topic(topic_el),
                                utc_time=parse_time(msg.get("UtcTime")) if msg is not None else None,
                                operation=msg.get("PropertyOperation") if msg is not None else None,
                                source=source, data=data, state=state_of(data)))
    return out


# ---------------------------------------------------------------- edges


@dataclass
class Edge:
    kind: str  # motion | tamper | digital_input | onvif
    key: str  # one per (topic, source): an input token, a video source...
    action: str  # start | end | moment
    label: str | None
    data: dict
    camera_time: datetime | None


def _label(kind: str, topic: str, source: dict) -> str | None:
    if kind == "digital_input":
        token = next((v for k, v in source.items() if "input" in k.lower() or "token" in k.lower()), None)
        return f"Input {token}" if token else "Input"
    if kind == "onvif":
        return "/".join(topic.split(":", 1)[-1].split("/")[-2:])[:128]
    return None


class EdgeTracker:
    """Turns notifications into edges. Kept across resubscribes so a state seen before a reconnect still counts."""

    def __init__(self, chosen: dict[str, str], store_other: bool = False):
        self.kind_of = {plain(path): kind for kind, path in chosen.items()}
        self.families = [re.compile(FALLBACK[k]) for k in chosen if k in FALLBACK]
        self.store_other = store_other
        self.last: dict[str, bool] = {}

    def kind(self, topic: str) -> str | None:
        p = plain(topic)
        if p in self.kind_of:
            return self.kind_of[p]
        if not self.store_other or NEVER.search(p) or any(rx.search(p) for rx in self.families):
            return None  # other topics of a chosen kind report the same thing twice (D5)
        return "onvif"

    def feed(self, n: Notification) -> Edge | None:
        kind = self.kind(n.topic)
        if kind is None:
            return None
        key = n.topic + "|" + "|".join(f"{k}={v}" for k, v in sorted(n.source.items()))
        label = _label(kind, n.topic, n.source)
        info = {"topic": n.topic, "source": n.source, "data": n.data}

        def edge(action: str) -> Edge:
            return Edge(kind, key, action, label, info, n.utc_time)

        if n.state is None:  # no on/off value: a pulse (or a changed generic value) is a moment
            if n.operation is None or (kind == "onvif" and n.operation == "Changed"):
                return edge("moment")
            return None
        before = self.last.get(key)
        if n.operation == "Deleted":
            self.last.pop(key, None)
            return edge("end") if before else None
        self.last[key] = n.state
        if before is None and n.operation == "Initialized":
            # the first state we hear of is only the starting state (its time can be weeks old: lab Q6)
            return None
        # After that, Initialized counts like Changed: the Illustra Flex4K (SS004.01.03) sends every motion change
        # as Initialized (seen on jk-1, 2026-11-23). An old camera time is replaced by our receive time (D8).
        if before == n.state:
            return None  # repeat without change (Q7)
        if n.state:
            return edge("start")
        return edge("end") if before else None
