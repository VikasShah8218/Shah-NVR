"""ONVIF event topics: parse a camera's TopicSet (GetEventProperties), parse NotificationMessages (PullMessages) and
classify topics into the event types Shah-NVR would store (docs/ONVIF_EVENTS_LAB.md §Classification).

Topic paths are written with canonical prefixes ("tns1:RuleEngine/CellMotionDetector/Motion"), whatever prefix the
camera used, so results from different vendors compare.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from lxml import etree

from .soap import NS, parse_time

# namespace URI -> canonical prefix (vendor topic namespaces seen in the field; unknown URIs keep the camera's prefix)
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
    "http://www.americandynamics.net/onvif/topics": "tnsad",  # American Dynamics (Tyco / Illustra), seen on jk-1
}
WSTOP_TOPIC = f"{{{NS['wstop']}}}topic"
TT_MESSAGE_DESCRIPTION = f"{{{NS['tt']}}}MessageDescription"


@dataclass
class TopicInfo:
    path: str  # canonical "tns1:RuleEngine/CellMotionDetector/Motion"
    is_property: bool  # stateful (Initialized/Changed/Deleted) vs. a pulse
    source: list[dict] = field(default_factory=list)  # [{name, type}]
    key: list[dict] = field(default_factory=list)
    data: list[dict] = field(default_factory=list)
    kind: str = "other"  # classify()

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Notification:
    topic: str  # canonical path
    raw_topic: str  # as sent
    utc_time: str | None
    operation: str | None  # Initialized / Changed / Deleted (properties only)
    source: dict
    key: dict
    data: dict
    kind: str
    state: bool | None  # True / False when the data carries an on/off value
    producer: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _prefix_for(uri: str | None, fallback: str | None) -> str:
    if uri and uri in PREFIXES:
        return PREFIXES[uri]
    return fallback or "ns"


# ---------------------------------------------------------------- TopicSet


def parse_topic_set(body: etree._Element) -> list[TopicInfo]:
    """GetEventPropertiesResponse body -> every leaf topic with its message description."""
    topic_set = body.find(".//wstop:TopicSet", NS)
    if topic_set is None:
        return []
    out: list[TopicInfo] = []

    def walk(el: etree._Element, parts: list[str], root_prefix: str | None):
        for child in el:
            if not isinstance(child.tag, str) or child.tag == TT_MESSAGE_DESCRIPTION:
                continue
            q = etree.QName(child)
            prefix = root_prefix or _prefix_for(q.namespace, child.prefix)
            path = parts + [q.localname]
            desc = child.find(TT_MESSAGE_DESCRIPTION)
            if child.get(WSTOP_TOPIC) == "true" or desc is not None:
                out.append(_topic_info(f"{prefix}:{'/'.join(path)}", desc))
            walk(child, path, prefix)

    walk(topic_set, [], None)
    for t in out:
        t.kind = classify(t.path, [d["name"] for d in t.data])
    return out


def _items(desc: etree._Element | None, part: str) -> list[dict]:
    if desc is None:
        return []
    node = desc.find(f"tt:{part}", NS)
    if node is None:
        return []
    items = []
    for it in node:
        if not isinstance(it.tag, str):
            continue
        name = it.get("Name")
        if name:
            items.append({"name": name, "type": (it.get("Type") or "").split(":")[-1],
                          "element": etree.QName(it).localname == "ElementItemDescription"})
    return items


def _topic_info(path: str, desc: etree._Element | None) -> TopicInfo:
    return TopicInfo(path=path, is_property=(desc is not None and desc.get("IsProperty") == "true"),
                     source=_items(desc, "Source"), key=_items(desc, "Key"), data=_items(desc, "Data"))


# ---------------------------------------------------------------- NotificationMessage


def canonical_topic(topic_el: etree._Element) -> tuple[str, str]:
    """wsnt:Topic text "tns1:VideoSource/MotionAlarm" -> (canonical, raw). The text's prefix is resolved through the
    element's in-scope namespaces, then mapped to our canonical prefix."""
    raw = (topic_el.text or "").strip()
    parts = []
    for piece in raw.split("|")[0].split("/"):  # "|" = ConcreteSet alternatives; use the first
        if ":" in piece:
            p, local = piece.split(":", 1)
            parts.append((p, local))
        else:
            parts.append((None, piece))
    if not parts:
        return raw, raw
    first_prefix = parts[0][0]
    uri = topic_el.nsmap.get(first_prefix) if first_prefix else None
    prefix = _prefix_for(uri, first_prefix)
    return f"{prefix}:{'/'.join(local for _p, local in parts)}", raw


def _simple_items(node: etree._Element | None) -> dict:
    if node is None:
        return {}
    out = {}
    for it in node:
        if not isinstance(it.tag, str):
            continue
        name = it.get("Name")
        if not name:
            continue
        if etree.QName(it).localname == "SimpleItem":
            out[name] = it.get("Value")
        else:  # ElementItem: keep a short XML summary
            out[name] = etree.tostring(it, encoding="unicode")[:300]
    return out


def parse_notifications(body: etree._Element) -> tuple[list[Notification], dict]:
    """PullMessagesResponse body -> (notifications, {current_time, termination_time})."""
    out = []
    resp = body.find("tev:PullMessagesResponse", NS)
    meta = {}
    if resp is not None:
        meta = {"current_time": (resp.findtext("tev:CurrentTime", namespaces=NS) or "").strip() or None,
                "termination_time": (resp.findtext("tev:TerminationTime", namespaces=NS) or "").strip() or None}
    for nm in body.iter(f"{{{NS['wsnt']}}}NotificationMessage"):
        topic_el = nm.find("wsnt:Topic", NS)
        if topic_el is None:
            continue
        topic, raw = canonical_topic(topic_el)
        msg = nm.find("wsnt:Message/tt:Message", NS)
        if msg is None:  # some cameras put tt:Message one level deeper or without the tt namespace
            msg = next((e for e in nm.iter() if isinstance(e.tag, str) and etree.QName(e).localname == "Message"
                        and e is not nm.find("wsnt:Message", NS)), None)
        source = _simple_items(msg.find("tt:Source", NS)) if msg is not None else {}
        key = _simple_items(msg.find("tt:Key", NS)) if msg is not None else {}
        data = _simple_items(msg.find("tt:Data", NS)) if msg is not None else {}
        producer = nm.findtext("wsnt:ProducerReference/wsa:Address", namespaces=NS)
        kind = classify(topic, list(data))
        out.append(Notification(topic=topic, raw_topic=raw, utc_time=msg.get("UtcTime") if msg is not None else None,
                                operation=msg.get("PropertyOperation") if msg is not None else None, source=source,
                                key=key, data=data, kind=kind, state=state_of(data), producer=producer))
    return out, meta


TRUE = {"true", "1", "active", "on", "yes", "alarm", "detected", "open"}
FALSE = {"false", "0", "inactive", "off", "no", "normal", "idle", "closed"}
STATE_NAMES = ("IsMotion", "State", "Value", "IsTamper", "LogicalState", "Active", "IsInside", "Alarm", "Triggered",
               "IsActive", "Signal", "Level")


def state_of(data: dict) -> bool | None:
    """The on/off value of a message, if it has one (IsMotion=true, LogicalState=1, State=false...)."""
    ordered = [k for k in STATE_NAMES if k in data] + [k for k in data if k not in STATE_NAMES]
    for k in ordered:
        v = str(data[k]).strip().lower()
        if v in TRUE:
            return True
        if v in FALSE:
            return False
    return None


# ---------------------------------------------------------------- classification

# (kind, regex on the lower-case path without prefixes). Order matters: the first match wins.
RULES: list[tuple[str, str]] = [
    ("video_loss", r"signalloss|videoloss|video_loss|/videolost|novideo"),
    ("tamper", r"tamper|globalscenechange|scenechange|imagetooblurry|imagetoodark|imagetoobright|defocus|"
               r"blurry|camerasabotage|videoblind|occlusion|outoffocus|accelerometer"),
    ("line_crossing", r"linedetector|linecross|line_cross|tripwire|crossed"),
    ("intrusion", r"fielddetector|intrusion|objectsinside|regionentrance|regionexit|loitering|areaentry|areaexit"),
    ("face", r"(^|/)face|facedetect|facerecogn|facecapture"),
    ("vehicle", r"licenseplate|vehicle|/lpr|anpr|plate"),
    ("people_count", r"counting|occupancy|peoplecount|crowd|counterdetector|persontracking"),
    ("object", r"objectdetect|humandetect|persondetect|objectclassif|abandon|removedobject|unattended|"
               r"objectremoval|leftobject|objecttracking"),
    ("audio", r"audio|sound|scream|gunshot"),
    ("motion", r"motion|cellmotion|motionalarm|videomotion|vmd"),
    ("relay", r"relay|digitaloutput|alarmout"),
    ("digital_input", r"digitalinput|device/trigger|/io/port|/io/input|alarmin|inputport|externalinput|"
                      r"virtualinput|manualtrigger"),
    ("ptz", r"ptz"),
    ("storage", r"storage|sdcard|recording(config|job|history)|disk"),
    ("system", r"monitoring|hardware|systemmessage|heartbeat|configurationchanged|profilechanged|"
               r"media/|networkstatus|ipaddress|reboot|firmware|processor|temperature|fan|power|"
               r"usermanagement|network|healthmonitor|factoryreset|otafirmware"),
]


def classify(path: str, data_names: list[str] | None = None) -> str:
    plain = re.sub(r"\b[a-z0-9]+:", "", path.lower())  # drop prefixes
    for kind, rx in RULES:
        if re.search(rx, plain):
            return kind
    return "other"


# what Shah-NVR would do with a kind (used by the report)
NVR_TYPES = {
    "motion": "motion", "tamper": "tamper", "digital_input": "digital_input", "video_loss": "video_loss",
    "line_crossing": "line_crossing", "intrusion": "intrusion", "face": "face", "vehicle": "vehicle",
    "people_count": "people_count", "object": "object", "audio": "audio",
}
