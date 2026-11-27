"""Camera analytics events (ONVIF phase 2, docs/ONVIF_ANALYTICS_EVENTS_PLAN.md §4): which topics carry the camera's
own analytics (line crossing, intrusion, ...), how to read them, and how to name them. Pure, no I/O.

One `Matcher` per known topic (plus fallback regexes for other vendors). A matcher says:
- the kind, or, for a topic that carries many rules (Illustra Pro4 `VideoSource/ObjectTrackingAlarm`), a map from the
  message's `RuleType` value to the kind (A2);
- how the message says "on": a boolean data item (`IsInside`), a value that changes on each detection
  (`LineDetector/Crossed` carries an ObjectId; `PersonTrackingAlarm` carries the counts), or a pulse;
- which data items give the rule name, object class, confidence, direction and boxes.

Shapes (A3): line crossing, face, object left, counting and audio are moments; intrusion, loitering and person are
ranges when the camera sends on/off (moments when it only pulses without a state).

Camera strings are data, never code (A10): they are cut to 64 characters and only shown (escaped by the UIs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The analytics kinds, in the order the UIs list them.
ANALYTICS_KINDS = ("line_crossing", "intrusion", "loitering", "object_left", "person", "face", "counting",
                   "audio_alarm")
TITLES = {"line_crossing": "Line crossing", "intrusion": "Intrusion", "loitering": "Loitering",
          "object_left": "Object left", "person": "Person", "face": "Face", "counting": "People counting",
          "audio_alarm": "Audio alarm"}
# Range kinds: start / end when the camera reports on and off. All the others are moments.
RANGE_KINDS = ("intrusion", "loitering", "person")

MAX_TEXT = 64
MAX_BOXES = 4

# RuleType / rule-module text -> kind (first match wins). Used for topics that carry several rules (Pro4), and for
# the fallback of unknown topics. The Pro4 strings are matched loosely until a capture fixes them (plan step 0).
RULE_TYPES: tuple[tuple[str, str], ...] = (
    (r"line|cross|tripwire|virtualfence", "line_crossing"),
    (r"loiter|dwell", "loitering"),
    (r"abandon|left|remov|unattended|missing|objectdetector", "object_left"),
    (r"count", "counting"),
    (r"face", "face"),
    (r"intru|zone|area|region|field|entr|exit|perimeter|inside", "intrusion"),
    (r"person|human|people|pedestrian", "person"),
    (r"audio|sound|scream|glass|gunshot|bark|aggress", "audio_alarm"),
)


@dataclass(frozen=True)
class Matcher:
    topic: str  # plain path ("ruleengine/linedetector/crossed") or, with `regex`, a pattern on it
    kind: str | None = None  # fixed kind; None = from the RuleType item (RULE_TYPES)
    kinds: tuple[str, ...] = ()  # what a RuleType topic may carry (for "offered" before any message)
    read: str = "state"  # state: a boolean item | value: a moment whenever `item` changes | pulse
    item: str | None = None  # the boolean / value item
    regex: bool = False
    ignore_values: tuple[str, ...] = ("0", "")  # value-read: values that mean "nothing" (ObjectId 0)


_RULE = ("Rule", "RuleName", "rule")
_CLASS = ("ObjectClass", "ClassType", "Class", "ObjectType", "Type")
_CONF = ("Confidence", "Likelihood", "Score")
_DIR = ("Direction",)
_BOXES = ("BoundingBoxes", "BoundingBox")
_TRACK = ("TrackingId", "ObjectId")
_TRACKED_RULE_TOPICS = ("videosource/objecttrackingalarm",)

ANALYTICS: tuple[Matcher, ...] = (
    # standard ONVIF rule engine (Tyco ISIN-B05M031-N; Hikvision and others use the same names)
    Matcher("ruleengine/linedetector/crossed", "line_crossing", read="value", item="ObjectId"),
    Matcher("ruleengine/fielddetector/objectsinside", "intrusion", item="IsInside"),
    Matcher("ruleengine/loiteringdetector/loitering", "loitering", item="IsLoitering"),
    Matcher("ruleengine/objectdetector/object", "object_left", item="IsLeft"),
    Matcher("ruleengine/humandetector/human", "person", item="IsHuman"),
    Matcher("ruleengine/facedetector/face", "face", item="IsFace"),
    Matcher("ruleengine/counterdetector/counter", "counting", item="IsCounter"),
    # Illustra Pro4: one topic, many rules (the kind is in RuleType); faces, audio, people counts
    Matcher("videosource/objecttrackingalarm", None, read="pulse", item="State",
            kinds=("line_crossing", "intrusion", "loitering", "object_left", "person")),
    Matcher("videosource/facealarm", "face", read="pulse", item="State"),
    Matcher("audiosource/audioalert", "audio_alarm", read="pulse", item="State"),
    Matcher("videosource/persontrackingalarm", "counting", read="value", item="NetCount"),
    # other vendors: fallbacks until a real camera is captured (the rule engine names above cover most of them)
    Matcher(r"linecross|crossline|tripwire|linedetect", "line_crossing", regex=True),
    Matcher(r"intrusion|fielddetect|regionentr|regionexit|areaentr|areaexit", "intrusion", regex=True),
    Matcher(r"loiter", "loitering", regex=True),
    Matcher(r"abandon|objectleft|objectremov|unattended", "object_left", regex=True),
    Matcher(r"humandetect|persondetect|peopledetect", "person", regex=True),
    Matcher(r"facedetect", "face", regex=True),
    Matcher(r"peoplecount|objectcount|counterdetect", "counting", regex=True),
    Matcher(r"audioalarm|audiodetect|soundalarm|audioanaly", "audio_alarm", regex=True),
)
_EXACT = {m.topic: m for m in ANALYTICS if not m.regex}
_FALLBACK = [(re.compile(m.topic), m) for m in ANALYTICS if m.regex]
# "Inverse" topics we never use (FieldDetector/ObjectsOutside is the same rule as ObjectsInside, the other way).
SKIP = re.compile(r"objectsoutside")


def _plain(path: str) -> str:
    return re.sub(r"\b[A-Za-z0-9_-]+:", "", path).lower()


def matcher_for(topic: str) -> Matcher | None:
    p = _plain(topic)
    if SKIP.search(p):
        return None
    if p in _EXACT:
        return _EXACT[p]
    if p.startswith(("ruleengine/cellmotiondetector", "ruleengine/motiondetector", "ruleengine/tamperdetector")):
        return None  # phase-1 kinds
    return next((m for rx, m in _FALLBACK if rx.search(p)), None)


def kinds_of(m: Matcher) -> tuple[str, ...]:
    return (m.kind,) if m.kind else m.kinds


def analytics_topics(offered_paths: list[str], kinds=ANALYTICS_KINDS) -> dict[str, list[str]]:
    """{kind: offered topics that may carry it} for the wanted analytics kinds (a RuleType topic is listed under
    every kind it may carry)."""
    out: dict[str, list[str]] = {}
    for path in offered_paths:
        m = matcher_for(path)
        if m is None:
            continue
        for k in kinds_of(m):
            if k in kinds and path not in out.setdefault(k, []):
                out[k].append(path)
    return {k: out[k] for k in kinds if out.get(k)}


def analytics_kinds(offered_paths: list[str]) -> list[str]:
    return list(analytics_topics(offered_paths))


def rule_kind(rule_type: str | None) -> str | None:
    t = re.sub(r"[^a-z]", "", (rule_type or "").lower())
    return next((k for rx, k in RULE_TYPES if re.search(rx, t)), None) if t else None


# ---------------------------------------------------------------- one message


@dataclass
class Analytic:
    kind: str | None  # None = a RuleType we do not know (the caller may keep it as a generic camera event)
    read: str  # state | value | pulse
    state: bool | None  # state / pulse: on or off (None = not said)
    value: str | None  # value-read: the changing value
    rule: str | None
    rule_type: str | None
    data: dict = field(default_factory=dict)  # bounded, for Event.data
    track: str | None = None  # an object id inside one rule (Pro4 TrackingId): one event per rule, not per object

    @property
    def is_range(self) -> bool:
        return self.kind in RANGE_KINDS and self.read in ("state", "pulse") and self.state is not None


def _cut(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s[:MAX_TEXT] if s else None


def _first(items: dict, names: tuple[str, ...]) -> str | None:
    for n in names:
        if n in items and _cut(items[n]):
            return _cut(items[n])
    return None


_TRUE = {"true", "1", "active", "on", "yes", "alarm", "detected"}
_FALSE = {"false", "0", "inactive", "off", "no", "normal", "idle"}


def _bool(v) -> bool | None:
    s = str(v).strip().lower() if v is not None else ""
    return True if s in _TRUE else False if s in _FALSE else None


def _confidence(v: str | None) -> int | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if f != f or f < 0:  # NaN
        return None
    pct = f * 100 if f <= 1 else f
    return round(pct) if pct <= 100 else None


def _boxes(data: dict) -> list[str] | None:
    text = next((str(data[n]) for n in _BOXES if data.get(n)), None)
    if not text:
        return None
    parts = [p.strip()[:MAX_TEXT] for p in re.split(r"[;|]", text) if p.strip()]
    return parts[:MAX_BOXES] or None


def classify(topic: str, source: dict, data: dict) -> Analytic | None:
    """A notification on an analytics topic -> what it says, or None if the topic is not analytics."""
    m = matcher_for(topic)
    if m is None:
        return None
    items = {**source, **data}
    rule_type = _cut(data.get("RuleType"))
    kind = m.kind or rule_kind(rule_type)
    if m.regex and m.item is None:  # fallback topic: any boolean item, else a pulse
        state = next((b for b in (_bool(v) for v in data.values()) if b is not None), None)
        read = "state" if state is not None else "pulse"
    else:
        read = m.read
        state = _bool(data.get(m.item)) if m.item and read != "value" else None
    value = _cut(data.get(m.item)) if read == "value" and m.item else None
    if read == "value" and value in m.ignore_values:
        value = None
    out: dict = {}
    rule = _first(items, _RULE)
    obj = _first(data, _CLASS)
    conf = _confidence(_first(data, _CONF))
    direction = _first(data, _DIR)
    for key, val in (("rule", rule), ("rule_type", rule_type), ("object", obj), ("confidence", conf),
                     ("direction", direction)):
        if val is not None:
            out[key] = val
    if boxes := _boxes(data):
        out["boxes"] = boxes
    if kind == "counting":
        for name in ("InCount", "OutCount", "NetCount"):
            if _cut(data.get(name)) is not None:
                out[name[:-5].lower()] = _cut(data.get(name))
    track = _first(data, _TRACK) if _plain(topic) in _TRACKED_RULE_TOPICS else None
    return Analytic(kind=kind, read=read, state=state, value=value, rule=rule, rule_type=rule_type, data=out,
                    track=track)


def label(kind: str, data: dict, count: int = 1) -> str:
    """'Line crossing · Gate line · person (87 %)', '... ×12' when merged (A4, A8)."""
    parts = [TITLES.get(kind, kind)]
    if data.get("rule"):
        parts.append(str(data["rule"]))
    if kind == "counting" and any(k in data for k in ("in", "out", "net")):
        parts.append(" / ".join(f"{k} {data[k]}" for k in ("in", "out", "net") if k in data))
    elif data.get("object"):
        conf = f" ({data['confidence']} %)" if data.get("confidence") is not None else ""
        parts.append(f"{data['object']}{conf}")
    text = " · ".join(parts)
    if count > 1:
        text += f" ×{count}"
    return text[:128]
