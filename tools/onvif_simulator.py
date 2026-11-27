"""Fake ONVIF cameras for development: answers WS-Discovery and the H1 SOAP calls for the camera simulator.

    py tools/camera_simulator.py --count 2          (RTSP: rtsp://127.0.0.1:8654/sim-1, sim-2)
    py tools/onvif_simulator.py --count 2           (ONVIF: http://127.0.0.2:8655, http://127.0.0.3:8655)

Camera N listens on 127.0.0.(N+1) (Windows/Linux route all of 127/8 to loopback), so each fake camera has its own
IP like on a real LAN. Login: admin / admin (WS-UsernameToken digest). Camera 2 starts with its clock 10 minutes
behind, to try "Sync time". Main profile = 1280x720, sub = 640x360 (both point at sim-N; the simulator has one
stream per camera). Snapshot = one frame grabbed from the RTSP stream with FFmpeg.

Camera events (ONVIF PullPoint, docs/ONVIF_EVENTS_PLAN.md §9) copy the cameras of the lab (docs/ONVIF_EVENTS_LAB.md):
    sim-1, 4, 7...  "tyco"  tns1:VideoSource/MotionAlarm (State); ignores topic filters; resends an unchanged
                            HealthMonitor value and a PTZ position every 8 s (lab Q7/Q8)
    sim-2, 5, 8...  "axis"  tnsaxis:.../VMD/Camera1ProfileANY (active); needs the ReferenceParameters echoed (Q2);
                            honours topic filters; Initialized messages carry a time weeks old (Q6)
    sim-3, 6, 9...  "isin"  tns1:RuleEngine/CellMotionDetector/Motion (IsMotion); refuses "//." filters (Q5)
All have tamper and one digital input. Fire them from a browser or curl (GET on the camera's ONVIF address):
    http://127.0.0.2:8655/sim/motion/on   .../motion/off   .../tamper/on|off   .../input/on|off

Camera analytics (docs/ONVIF_ANALYTICS_EVENTS_PLAN.md §6) on "isin" (standard rule engine, rule names in the Source)
and "tyco" (Pro4: one ObjectTrackingAlarm topic, the kind in RuleType; FaceAlarm, AudioAlert, PersonTrackingAlarm):
    .../sim/line/on   (a crossing: a new ObjectId / a pulse)   .../intrusion/on|off   .../loiter/on|off
    .../object/on|off   .../person/on|off   .../face/on   .../count/on   .../audio/on (tyco)
    .../sim/line/burst?n=50   (50 crossings at once: the flood control)
"""

import argparse
import base64
import hashlib
import socket
import struct
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

S = "http://www.w3.org/2003/05/soap-envelope"
NS = ('xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:tds="http://www.onvif.org/ver10/device/wsdl" '
      'xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema" '
      'xmlns:ter="http://www.onvif.org/ver10/error"')
WSSE = "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}"
WSU = "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}"
NO_AUTH = {"GetSystemDateAndTime"}
EVENTS_NS = "http://www.onvif.org/ver10/events/wsdl"
WSA = "{http://www.w3.org/2005/08/addressing}"
EV_NS = ('xmlns:tev="http://www.onvif.org/ver10/events/wsdl" xmlns:wsnt="http://docs.oasis-open.org/wsn/b-2" '
         'xmlns:wstop="http://docs.oasis-open.org/wsn/t-1" xmlns:wsa="http://www.w3.org/2005/08/addressing" '
         'xmlns:tns1="http://www.onvif.org/ver10/topics" xmlns:tnsaxis="http://www.axis.com/2009/event/topics"')
# vendor -> kind -> (topic, data item name, value on, value off)
VENDORS = {
    "tyco": {"motion": ("tns1:VideoSource/MotionAlarm", "State", "true", "false"),
             "tamper": ("tns1:VideoSource/TamperDetect", "State", "true", "false"),
             "input": ("tns1:Device/Trigger/DigitalInput", "LogicalState", "true", "false")},
    "axis": {"motion": ("tnsaxis:CameraApplicationPlatform/VMD/Camera1ProfileANY", "active", "1", "0"),
             "tamper": ("tns1:VideoSource/GlobalSceneChange/ImagingService", "State", "true", "false"),
             "input": ("tns1:Device/Trigger/DigitalInput", "LogicalState", "true", "false")},
    "isin": {"motion": ("tns1:RuleEngine/CellMotionDetector/Motion", "IsMotion", "true", "false"),
             "tamper": ("tns1:RuleEngine/TamperDetector/Tamper", "IsTamper", "true", "false"),
             "input": ("tns1:Device/Trigger/DigitalInput", "LogicalState", "true", "false")},
}
# analytics name -> (topic, item, rule name, read: state | value)  (ISIN-B05M031-N, shah-ho-1 2026-11-26)
ISIN_ANALYTICS = {
    "line": ("tns1:RuleEngine/LineDetector/Crossed", "ObjectId", "Gate line", "value"),
    "intrusion": ("tns1:RuleEngine/FieldDetector/ObjectsInside", "IsInside", "Parking", "state"),
    "loiter": ("tns1:RuleEngine/LoiteringDetector/Loitering", "IsLoitering", "Entrance", "state"),
    "object": ("tns1:RuleEngine/ObjectDetector/Object", "IsLeft", "Lobby", "state"),
    "person": ("tns1:RuleEngine/HumanDetector/Human", "IsHuman", "MyHumanDetectorRule", "state"),
    "face": ("tns1:RuleEngine/FaceDetector/Face", "IsFace", "MyFaceDetectorRule", "state"),
    "count": ("tns1:RuleEngine/CounterDetector/Counter", "IsCounter", "MyCounterDetectorRule", "state"),
}
# Pro4: ObjectTrackingAlarm RuleType per analytics name (the strings are a guess until a Pro4 capture)
TYCO_TRACK = "tns1:VideoSource/ObjectTrackingAlarm"
TYCO_RULES = {"line": ("LineCrossing", "Gate line"), "intrusion": ("Intrusion", "Parking"),
              "loiter": ("Loitering", "Entrance"), "object": ("AbandonedObject", "Lobby"),
              "person": ("PersonDetection", "Yard")}
TYCO_OTHER = {"face": "tns1:VideoSource/FaceAlarm", "audio": "tns1:AudioSource/AudioAlert",
              "count": "tns1:VideoSource/PersonTrackingAlarm"}
ANALYTICS = {"isin": tuple(ISIN_ANALYTICS), "tyco": tuple(TYCO_RULES) + tuple(TYCO_OTHER)}
NOISE = [("tns1:Monitoring/HealthMonitor", "Status", "OK"),  # resent unchanged (tyco: lab Q7)
         ("tns1:PTZController/PTZPosition", "Position", "0.1,0.2,0")]  # position stream (lab Q8)


def envelope(body: str) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope {NS}><s:Body>{body}</s:Body></s:Envelope>'.encode()


def fault(code: str, sub: str, reason: str) -> bytes:
    return envelope(f"<s:Fault><s:Code><s:Value>s:{code}</s:Value><s:Subcode><s:Value>ter:{sub}</s:Value></s:Subcode>"
                    f'</s:Code><s:Reason><s:Text xml:lang="en">{reason}</s:Text></s:Reason></s:Fault>')


def dt(ts: float) -> str:
    d = datetime.fromtimestamp(ts, timezone.utc)
    return (f"<tt:Date><tt:Year>{d.year}</tt:Year><tt:Month>{d.month}</tt:Month><tt:Day>{d.day}</tt:Day></tt:Date>"
            f"<tt:Time><tt:Hour>{d.hour}</tt:Hour><tt:Minute>{d.minute}</tt:Minute><tt:Second>{d.second}</tt:Second></tt:Time>")


class Camera:
    def __init__(self, index: int, args):
        self.index, self.args = index, args
        self.ip = f"127.0.0.{index + 1}"
        self.url = f"http://{self.ip}:{args.http_port}/onvif/device_service"
        self.endpoint = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_DNS, f'shah-nvr-sim-{index}')}"
        self.skew = -600.0 if index == 2 else 0.0
        self.ntp_dhcp, self.ntp_servers, self.time_type = True, [], "Manual"
        self.vendor = ("isin", "tyco", "axis")[index % 3]
        self.events_url = f"http://{self.ip}:{args.http_port}/onvif/event_service"
        self.state = {k: False for k in VENDORS[self.vendor]}
        self.subs: dict[str, dict] = {}  # id -> {queue, expires, topics (filter) or None}
        self.cond = threading.Condition()
        self.next_sub = 0
        self.analytics = {a: False for a in ANALYTICS.get(self.vendor, ())}
        self.object_id = 0
        self.counts = [0, 0]  # people in / out

    # ---------------------------------------------------------------- events
    def utc(self, ago: float = 0.0) -> str:
        return datetime.fromtimestamp(time.time() + self.skew - ago, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def message(self, topic: str, op: str | None, item: str, value: str, ago: float = 0.0) -> str:
        source = ('<tt:SimpleItem Name="InputToken" Value="DI1"/>' if "DigitalInput" in topic
                  else '<tt:SimpleItem Name="VideoSourceToken" Value="vs1"/>')
        op_attr = f' PropertyOperation="{op}"' if op else ""
        return (f'<wsnt:NotificationMessage><wsnt:Topic Dialect="http://www.onvif.org/ver10/tev/topicExpression/'
                f'ConcreteSet">{topic}</wsnt:Topic><wsnt:Message><tt:Message UtcTime="{self.utc(ago)}"{op_attr}>'
                f'<tt:Source>{source}</tt:Source><tt:Data><tt:SimpleItem Name="{item}" Value="{value}"/></tt:Data>'
                "</tt:Message></wsnt:Message></wsnt:NotificationMessage>")

    def amessage(self, topic: str, op: str | None, source: dict, data: dict) -> str:
        """A message with several items (analytics)."""
        items = lambda d: "".join(f'<tt:SimpleItem Name="{k}" Value="{v}"/>' for k, v in d.items())  # noqa: E731
        op_attr = f' PropertyOperation="{op}"' if op else ""
        return (f'<wsnt:NotificationMessage><wsnt:Topic Dialect="http://www.onvif.org/ver10/tev/topicExpression/'
                f'ConcreteSet">{topic}</wsnt:Topic><wsnt:Message><tt:Message UtcTime="{self.utc()}"{op_attr}>'
                f'<tt:Source>{items(source)}</tt:Source><tt:Data>{items(data)}</tt:Data>'
                "</tt:Message></wsnt:Message></wsnt:NotificationMessage>")

    def isin_analytic(self, name: str, op: str) -> tuple[str, str]:
        topic, item, rule, read = ISIN_ANALYTICS[name]
        src = {"VideoSourceConfigurationToken": "VideoSource", "VideoAnalyticsConfigurationToken": "VideoAnalyticsToken",
               "Rule": rule}
        value = str(self.object_id) if read == "value" else ("true" if self.analytics[name] else "false")
        return topic, self.amessage(topic, op, src, {item: value})

    def trigger_analytic(self, name: str, on: bool) -> str:
        """An analytics detection (on: for moments, one detection)."""
        if self.vendor == "isin":
            if ISIN_ANALYTICS[name][3] == "value":
                if not on:
                    return f"sim-{self.index}: {name} is a moment, use /on"
                self.object_id += 1
            else:
                self.analytics[name] = on
            self.push(*self.isin_analytic(name, "Changed"))
        elif name in TYCO_RULES:
            rule_type, rule = TYCO_RULES[name]
            self.object_id += 1 if on else 0
            self.push(TYCO_TRACK, self.amessage(TYCO_TRACK, None, {"Source": "VideoSource"}, {
                "RuleType": rule_type, "RuleName": rule, "ObjectClass": "Person" if name != "object" else "Bag",
                "Confidence": "0.87", "Direction": "LeftToRight", "State": "true" if on else "false",
                "TrackingId": str(self.object_id), "BoundingBoxes": "0.10,0.20,0.30,0.60"}))
        elif name == "count":
            self.counts[0] += 1
            topic = TYCO_OTHER["count"]
            self.push(topic, self.amessage(topic, "Changed", {}, {"InCount": self.counts[0], "OutCount": self.counts[1],
                                                                   "NetCount": self.counts[0] - self.counts[1]}))
        else:
            topic = TYCO_OTHER[name]
            data = {"State": "true" if on else "false"}
            if name == "audio":
                data.update(RuleType="GlassBreak", RuleName="Window", Confidence="91")
            self.push(topic, self.amessage(topic, None, {"Source": "VideoSource"}, data))
        return f"sim-{self.index} ({self.vendor}): {name} {'on' if on else 'off'}, {len(self.subs)} subscription(s)"

    def push(self, topic: str, xml: str) -> None:
        with self.cond:
            for sub in self.subs.values():
                if sub["topics"] is None or topic in sub["topics"] or self.vendor == "tyco":  # tyco ignores filters
                    sub["queue"].append(xml)
            self.cond.notify_all()

    def initialized(self) -> list[str]:
        ago = 30 * 86400 if self.vendor == "axis" else 0  # AXIS: the time the state last changed (lab Q6)
        out = [self.message(t, "Initialized", item, on if self.state[k] else off, ago)
               for k, (t, item, on, off) in VENDORS[self.vendor].items()]
        if self.vendor == "isin":  # every rule's state, like the real ISIN
            out += [self.isin_analytic(a, "Initialized")[1] for a in ISIN_ANALYTICS]
        return out

    def trigger(self, kind: str, on: bool) -> str:
        t, item, v_on, v_off = VENDORS[self.vendor][kind]
        self.state[kind] = on
        self.push(t, self.message(t, "Changed", item, v_on if on else v_off))
        return f"sim-{self.index} ({self.vendor}): {kind} {'on' if on else 'off'}, {len(self.subs)} subscription(s)"

    def noise_loop(self) -> None:
        while True:
            time.sleep(8)
            if self.vendor == "tyco":
                for t, item, v in NOISE:
                    self.push(t, self.message(t, "Changed", item, v))
            with self.cond:
                for sid in [s for s, sub in self.subs.items() if sub["expires"] < time.time()]:
                    del self.subs[sid]  # not renewed: gone, like on a camera

    def topic_set(self) -> str:
        def leaf(path: str, item: str) -> str:
            parts = path.split(":", 1)[1].split("/")
            prefix = path.split(":", 1)[0]
            inner = ('<tt:MessageDescription IsProperty="true"><tt:Source><tt:SimpleItemDescription Name="Token" '
                     f'Type="tt:ReferenceToken"/></tt:Source><tt:Data><tt:SimpleItemDescription Name="{item}" '
                     'Type="xs:boolean"/></tt:Data></tt:MessageDescription>')
            xml = f'<{prefix}:{parts[-1]} wstop:topic="true">{inner}</{prefix}:{parts[-1]}>'
            for p_ in reversed(parts[:-1]):
                xml = f"<{prefix}:{p_}>{xml}</{prefix}:{p_}>"
            return xml
        topics = [(t, item) for t, item, *_ in VENDORS[self.vendor].values()] + [(t, i) for t, i, _ in NOISE]
        if self.vendor == "isin":
            topics += [(t, item) for t, item, *_ in ISIN_ANALYTICS.values()]
        elif self.vendor == "tyco":
            topics += [(TYCO_TRACK, "RuleType"), *[(t, "State") for t in TYCO_OTHER.values()]]
        return "".join(leaf(t, i) for t, i in topics)

    def events(self, action: str, req: ET.Element, path: str) -> bytes | None:
        """The PullPoint calls; None = not an event call."""
        if action == "GetEventProperties":
            return envelope(f"<tev:GetEventPropertiesResponse {EV_NS}><wstop:TopicSet>{self.topic_set()}</wstop:TopicSet>"
                            "</tev:GetEventPropertiesResponse>")
        if action == "CreatePullPointSubscription":
            expr = req.findtext(".//{http://docs.oasis-open.org/wsn/b-2}TopicExpression")
            if expr and self.vendor == "isin" and "//." in expr:
                return fault("Sender", "InvalidFilterFault", "InvalidFilterFault: //. not supported")
            with self.cond:
                self.next_sub += 1
                sid = str(self.next_sub)
                self.subs[sid] = {"queue": self.initialized(), "expires": time.time() + 60,
                                  "topics": set(expr.split("|")) if expr else None}
            if self.vendor == "axis":  # one address; the subscription is named in ReferenceParameters (lab Q2)
                ref = (f"<wsa:Address>http://{self.ip}:{self.args.http_port}/onvif/services</wsa:Address>"
                       f'<wsa:ReferenceParameters><dom:SubscriptionId xmlns:dom="http://www.axis.com/2009/event">{sid}'
                       "</dom:SubscriptionId></wsa:ReferenceParameters>")
            else:
                ref = f"<wsa:Address>http://{self.ip}:{self.args.http_port}/onvif/subscription?id={sid}</wsa:Address>"
            print(f"  sim-{self.index} ({self.vendor}): subscription {sid}" + (f" filter {expr}" if expr else ""))
            return envelope(f"<tev:CreatePullPointSubscriptionResponse {EV_NS}><tev:SubscriptionReference>{ref}"
                            f"</tev:SubscriptionReference><wsnt:CurrentTime>{self.utc()}</wsnt:CurrentTime>"
                            f"<wsnt:TerminationTime>{self.utc(-60)}</wsnt:TerminationTime>"
                            "</tev:CreatePullPointSubscriptionResponse>")
        if action not in ("PullMessages", "Renew", "Unsubscribe", "SetSynchronizationPoint"):
            return None
        if req.find(f".//{WSA}To") is None or req.find(f".//{WSA}Action") is None:
            return fault("Sender", "InvalidArgs", "WS-Addressing To / Action missing")  # lab Q2
        if self.vendor == "axis":
            sid = req.findtext(".//{http://www.axis.com/2009/event}SubscriptionId")
        else:
            sid = (parse_qs(urlsplit(path).query).get("id") or [None])[0]
        with self.cond:
            sub = self.subs.get(sid or "")
        if sub is None:
            return fault("Receiver", "ResourceUnknownFault", "Invalid Subscription Reference")
        if action == "Renew":
            sub["expires"] = time.time() + 60
            return envelope(f"<wsnt:RenewResponse {EV_NS}><wsnt:TerminationTime>{self.utc(-60)}</wsnt:TerminationTime>"
                            "</wsnt:RenewResponse>")
        if action == "Unsubscribe":
            with self.cond:
                self.subs.pop(sid, None)
            print(f"  sim-{self.index} ({self.vendor}): subscription {sid} removed")
            return envelope(f"<wsnt:UnsubscribeResponse {EV_NS}/>")
        if action == "SetSynchronizationPoint":
            with self.cond:
                sub["queue"].extend(self.initialized())
                self.cond.notify_all()
            return envelope(f"<tev:SetSynchronizationPointResponse {EV_NS}/>")
        wait = req.findtext(f".//{{{EVENTS_NS}}}Timeout") or "PT10S"
        seconds = float(wait.strip("PTS") or 10) if wait.endswith("S") else 10.0
        with self.cond:
            self.cond.wait_for(lambda: sub["queue"], timeout=min(seconds, 60))
            out, sub["queue"][:] = list(sub["queue"]), []
        return envelope(f"<tev:PullMessagesResponse {EV_NS}><tev:CurrentTime>{self.utc()}</tev:CurrentTime>"
                        f"<tev:TerminationTime>{self.utc(-60)}</tev:TerminationTime>{''.join(out)}</tev:PullMessagesResponse>")

    def rtsp(self) -> str:
        return f"rtsp://127.0.0.1:{self.args.rtsp_port}/sim-{self.index}"

    def profile(self, token, w, h) -> str:
        return (f'<trt:Profiles token="{token}" fixed="true"><tt:Name>{token}</tt:Name>'
                f'<tt:VideoEncoderConfiguration token="enc_{token}"><tt:Name>{token}</tt:Name><tt:UseCount>1</tt:UseCount>'
                f"<tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>{w}</tt:Width><tt:Height>{h}</tt:Height></tt:Resolution>"
                "<tt:Quality>5</tt:Quality><tt:RateControl><tt:FrameRateLimit>25</tt:FrameRateLimit><tt:EncodingInterval>1"
                "</tt:EncodingInterval><tt:BitrateLimit>1500</tt:BitrateLimit></tt:RateControl></tt:VideoEncoderConfiguration>"
                "</trt:Profiles>")

    def handle(self, action: str, req: ET.Element, path: str = "/") -> bytes:
        a = self
        if (reply := a.events(action, req, path)) is not None:
            return reply
        if action == "GetSystemDateAndTime":
            return envelope("<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime>"
                            f"<tt:DateTimeType>{a.time_type}</tt:DateTimeType><tt:DaylightSavings>false</tt:DaylightSavings>"
                            f"<tt:TimeZone><tt:TZ>UTC0</tt:TZ></tt:TimeZone><tt:UTCDateTime>{dt(time.time() + a.skew)}</tt:UTCDateTime>"
                            "</tds:SystemDateAndTime></tds:GetSystemDateAndTimeResponse>")
        if action == "GetDeviceInformation":
            return envelope("<tds:GetDeviceInformationResponse><tds:Manufacturer>Shah</tds:Manufacturer>"
                            f"<tds:Model>SimCam {a.index}</tds:Model><tds:FirmwareVersion>1.0.{a.index}</tds:FirmwareVersion>"
                            f"<tds:SerialNumber>SIM{a.index:04d}</tds:SerialNumber><tds:HardwareId>sim</tds:HardwareId>"
                            "</tds:GetDeviceInformationResponse>")
        if action == "GetServices":
            svc = "".join(f"<tds:Service><tds:Namespace>{ns}</tds:Namespace><tds:XAddr>{a.url}</tds:XAddr>"
                          "<tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version></tds:Service>"
                          for ns in ("http://www.onvif.org/ver10/device/wsdl", "http://www.onvif.org/ver10/media/wsdl"))
            svc += (f"<tds:Service><tds:Namespace>{EVENTS_NS}</tds:Namespace><tds:XAddr>{a.events_url}</tds:XAddr>"
                    "<tds:Version><tt:Major>2</tt:Major><tt:Minor>6</tt:Minor></tds:Version></tds:Service>")
            return envelope(f"<tds:GetServicesResponse>{svc}</tds:GetServicesResponse>")
        if action == "GetProfiles":
            return envelope(f"<trt:GetProfilesResponse>{a.profile('main', 1280, 720)}{a.profile('sub', 640, 360)}</trt:GetProfilesResponse>")
        if action == "GetStreamUri":
            return envelope(f"<trt:GetStreamUriResponse><trt:MediaUri><tt:Uri>{a.rtsp()}</tt:Uri></trt:MediaUri></trt:GetStreamUriResponse>")
        if action == "GetSnapshotUri":
            return envelope(f"<trt:GetSnapshotUriResponse><trt:MediaUri><tt:Uri>http://{a.ip}:{a.args.http_port}/snapshot.jpg"
                            "</tt:Uri></trt:MediaUri></trt:GetSnapshotUriResponse>")
        if action == "GetVideoAnalyticsConfigurations" and a.vendor == "isin":  # the configured rules (analytics A7)
            rules = "".join(f'<tt:Rule Name="{rule}" Type="tt:{t.split("/")[1]}"/>' for t, _i, rule, _r in ISIN_ANALYTICS.values())
            return envelope('<trt:GetVideoAnalyticsConfigurationsResponse><trt:Configurations token="VideoAnalyticsToken">'
                            "<tt:Name>VideoAnalyticsName</tt:Name><tt:RuleEngineConfiguration>"
                            f"{rules}</tt:RuleEngineConfiguration></trt:Configurations>"
                            "</trt:GetVideoAnalyticsConfigurationsResponse>")
        if action == "GetNTP":
            manual = "".join(f"<tt:NTPManual><tt:Type>DNS</tt:Type><tt:DNSname>{s}</tt:DNSname></tt:NTPManual>" for s in a.ntp_servers)
            return envelope(f"<tds:GetNTPResponse><tds:NTPInformation><tt:FromDHCP>{str(a.ntp_dhcp).lower()}</tt:FromDHCP>"
                            f"{manual}</tds:NTPInformation></tds:GetNTPResponse>")
        if action == "GetHostname":
            return envelope(f"<tds:GetHostnameResponse><tds:HostnameInformation><tt:FromDHCP>false</tt:FromDHCP>"
                            f"<tt:Name>simcam-{a.index}</tt:Name></tds:HostnameInformation></tds:GetHostnameResponse>")
        if action == "GetNetworkInterfaces":
            return envelope('<tds:GetNetworkInterfacesResponse><tds:NetworkInterfaces token="eth0"><tt:Enabled>true</tt:Enabled>'
                            f"<tt:Info><tt:HwAddress>02:00:00:00:00:{a.index:02x}</tt:HwAddress></tt:Info><tt:IPv4><tt:Enabled>true</tt:Enabled>"
                            f"<tt:Config><tt:Manual><tt:Address>{a.ip}</tt:Address><tt:PrefixLength>8</tt:PrefixLength></tt:Manual>"
                            "<tt:DHCP>false</tt:DHCP></tt:Config></tt:IPv4></tds:NetworkInterfaces></tds:GetNetworkInterfacesResponse>")
        if action == "SetSystemDateAndTime":
            a.time_type = req.findtext(".//{http://www.onvif.org/ver10/device/wsdl}DateTimeType") or "Manual"
            a.skew = 0.0
            return envelope("<tds:SetSystemDateAndTimeResponse/>")
        if action == "SetNTP":
            a.ntp_dhcp = (req.findtext(".//{http://www.onvif.org/ver10/device/wsdl}FromDHCP") or "").lower() == "true"
            a.ntp_servers = [e.text for e in req.iter("{http://www.onvif.org/ver10/schema}DNSname")] + \
                            [e.text for e in req.iter("{http://www.onvif.org/ver10/schema}IPv4Address")]
            return envelope("<tds:SetNTPResponse/>")
        if action == "SystemReboot":
            print(f"  sim-{a.index}: reboot requested")
            return envelope("<tds:SystemRebootResponse><tds:Message>Rebooting in 30 seconds</tds:Message></tds:SystemRebootResponse>")
        return fault("Sender", "ActionNotSupported", f"{action} not supported by the simulator")

    def authorized(self, root: ET.Element) -> bool:
        token = root.find(f".//{WSSE}UsernameToken")
        if token is None:
            return False
        user = token.findtext(f"{WSSE}Username")
        digest = token.findtext(f"{WSSE}Password")
        nonce = base64.b64decode(token.findtext(f"{WSSE}Nonce") or "")
        created = token.findtext(f"{WSU}Created") or ""
        expect = base64.b64encode(hashlib.sha1(nonce + created.encode() + self.args.password.encode()).digest()).decode()
        try:  # like real cameras: the token time must match the camera clock (+-5 min)
            ts = datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return False
        return user == self.args.user and digest == expect and abs(ts - (time.time() + self.skew)) < 300


def make_handler(cam: Camera):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                root = ET.fromstring(data)
                action = next(iter(root.find(f"{{{S}}}Body"))).tag.split("}")[-1]
            except (ET.ParseError, StopIteration, TypeError):
                return self._send(400, fault("Sender", "WellFormed", "bad request"))
            if action not in NO_AUTH and not cam.authorized(root):
                print(f"  sim-{cam.index}: {action} refused (wrong login)")
                return self._send(400, fault("Sender", "NotAuthorized", "Sender not authorized"))
            body = cam.handle(action, root, self.path)
            self._send(500 if b"ActionNotSupported" in body else 200, body)

        def do_GET(self):
            parts = self.path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "sim" and parts[1] in cam.state and parts[2] in ("on", "off"):
                text = cam.trigger(parts[1], parts[2] == "on")
                print(f"  {text}")
                return self._send(200, text.encode(), "text/plain")
            url = urlsplit(self.path)
            parts = url.path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "sim" and parts[1] in cam.analytics and parts[2] in ("on", "off", "burst"):
                if parts[2] == "burst":
                    n = min(int((parse_qs(url.query).get("n") or ["50"])[0]), 1000)
                    for _ in range(n):
                        cam.trigger_analytic(parts[1], True)
                    text = f"sim-{cam.index}: {n} x {parts[1]}"
                else:
                    text = cam.trigger_analytic(parts[1], parts[2] == "on")
                print(f"  {text}")
                return self._send(200, text.encode(), "text/plain")
            if self.path != "/snapshot.jpg":
                return self._send(404, b"", "text/plain")
            out = subprocess.run(["ffmpeg", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", cam.rtsp(),
                                  "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-"], capture_output=True, timeout=15)
            self._send(200 if out.stdout else 503, out.stdout, "image/jpeg")

        def _send(self, status: int, body: bytes, ctype: str = "application/soap+xml; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def discovery_responder(cams: list[Camera]) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 3702))
    for ip in {"0.0.0.0", *_local_ips()}:  # join on every interface the node may probe from
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            struct.pack("4s4s", socket.inet_aton("239.255.255.250"), socket.inet_aton(ip)))
        except OSError:
            pass
    while True:
        data, addr = sock.recvfrom(65535)
        if b"Probe" not in data or b"ProbeMatches" in data:
            continue
        try:
            rel = ET.fromstring(data).findtext(".//{http://schemas.xmlsoap.org/ws/2004/08/addressing}MessageID") or ""
        except ET.ParseError:
            continue
        for cam in cams:
            reply = (f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="{S}" '
                     'xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
                     'xmlns:dn="http://www.onvif.org/ver10/network/wsdl"><s:Header>'
                     "<a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</a:Action>"
                     f"<a:MessageID>uuid:{uuid.uuid4()}</a:MessageID><a:RelatesTo>{rel}</a:RelatesTo></s:Header><s:Body>"
                     f"<d:ProbeMatches><d:ProbeMatch><a:EndpointReference><a:Address>{cam.endpoint}</a:Address></a:EndpointReference>"
                     "<d:Types>dn:NetworkVideoTransmitter</d:Types><d:Scopes>onvif://www.onvif.org/Profile/Streaming "
                     f"onvif://www.onvif.org/name/SimCam%20{cam.index} onvif://www.onvif.org/hardware/SimCam "
                     f"onvif://www.onvif.org/location/Lab</d:Scopes><d:XAddrs>{cam.url}</d:XAddrs>"
                     "<d:MetadataVersion>1</d:MetadataVersion></d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>")
            sock.sendto(reply.encode(), addr)


def _local_ips() -> list[str]:
    try:
        return [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        return []


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--count", type=int, default=2)
    p.add_argument("--http-port", type=int, default=8655)
    p.add_argument("--rtsp-port", type=int, default=8654)
    p.add_argument("--user", default="admin")
    p.add_argument("--password", default="admin")
    args = p.parse_args()

    cams = [Camera(i, args) for i in range(1, args.count + 1)]
    for cam in cams:
        server = ThreadingHTTPServer((cam.ip, args.http_port), make_handler(cam))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        threading.Thread(target=cam.noise_loop, daemon=True).start()
        print(f"sim-{cam.index}: ONVIF {cam.url}  RTSP {cam.rtsp()}  events like {cam.vendor}"
              + ("  (clock 10 min behind)" if cam.skew else ""))
    threading.Thread(target=discovery_responder, args=(cams,), daemon=True).start()
    print(f"WS-Discovery on udp/3702. Login {args.user}/{args.password}. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
