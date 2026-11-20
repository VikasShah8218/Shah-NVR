"""One camera's ONVIF event surface: clock, identity, services, event topics, PullPoint subscriptions, analytics rules
and I/O ports. Everything here only reads, except PullPoint subscriptions, which are always given a short
termination time and unsubscribed (a camera has few subscription slots and another VMS may need them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx
from lxml import etree

from .soap import NS, Credentials, SoapClient, SoapError, parse_duration, parse_time, text
from .topics import Notification, TopicInfo, parse_notifications, parse_topic_set

A_EV = "http://www.onvif.org/ver10/events/wsdl/EventPortType"
A_PP = "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription"
A_SM = "http://docs.oasis-open.org/wsn/bw-2/SubscriptionManager"


@dataclass
class Subscription:
    address: str
    ref_params: str  # serialized ReferenceParameters children, echoed as SOAP headers
    created_at: datetime
    termination: str | None
    camera_time: str | None


@dataclass
class Camera:
    """A camera reached on `host:port` (ONVIF device service at /onvif/device_service unless `device_url`)."""

    id: int
    name: str
    host: str
    port: int = 80
    username: str | None = None
    password: str | None = None
    device_url: str | None = None
    timeout: float = 8.0
    client: SoapClient = field(init=False)
    xaddrs: dict = field(default_factory=dict)

    def __post_init__(self):
        scheme = "https" if self.port == 443 else "http"
        self.device_url = self.device_url or f"{scheme}://{self.host}:{self.port}/onvif/device_service"
        self.client = SoapClient(Credentials(self.username, self.password), timeout=self.timeout)

    async def __aenter__(self):
        self.client.http = httpx.AsyncClient(verify=False, follow_redirects=False,
                                             limits=httpx.Limits(max_connections=4, max_keepalive_connections=2))
        return self

    async def __aexit__(self, *exc):
        await self.client.http.aclose()

    # ---------------------------------------------------------------- helpers
    def fix_addr(self, url: str | None) -> str | None:
        """Cameras behind NAT / with several NICs often advertise an address we can't reach: keep their path and
        port, but use the host we reached them on (port 80 stays as advertised)."""
        if not url:
            return url
        u = urlsplit(url)
        scheme = urlsplit(self.device_url).scheme
        if u.hostname and (u.hostname != self.host or (u.scheme or "http") != scheme):
            # same host we reached, same scheme as the device service (a camera on 443 may advertise http://ip/)
            port = u.port if u.hostname == self.host and u.port else self.port
            default = 443 if scheme == "https" else 80
            netloc = self.host if port == default else f"{self.host}:{port}"
            return urlunsplit((scheme, netloc, u.path, u.query, u.fragment))
        return url

    async def call(self, service: str, body: str, action: str, **kw) -> etree._Element:
        url = self.xaddrs.get(service) or self.device_url
        return await self.client.call(url, body, action, **kw)

    # ---------------------------------------------------------------- device
    async def clock(self) -> dict:
        """GetSystemDateAndTime (no auth) -> camera clock and its offset from ours (seconds; > 0 = camera ahead)."""
        before = datetime.now(timezone.utc)
        body = await self.client.call(self.device_url, "<tds:GetSystemDateAndTime/>",
                                      "http://www.onvif.org/ver10/device/wsdl/GetSystemDateAndTime", auth=False)
        after = datetime.now(timezone.utc)
        utc = body.find(".//tt:UTCDateTime", NS)
        info = {"ntp": text(body, ".//tt:DateTimeType"), "tz": text(body, ".//tt:TimeZone/tt:TZ")}
        if utc is not None:
            d = [int(text(utc, f"tt:{p}/tt:{q}") or 0) for p, q in
                 (("Date", "Year"), ("Date", "Month"), ("Date", "Day"), ("Time", "Hour"), ("Time", "Minute"),
                  ("Time", "Second"))]
            cam = datetime(*d, tzinfo=timezone.utc)
            mid = before + (after - before) / 2
            self.client.offset = (cam - mid).total_seconds()
            info.update(camera_utc=cam.isoformat(), offset_s=round(self.client.offset, 1))
        return info

    async def identity(self) -> dict:
        body = await self.client.call(self.device_url, "<tds:GetDeviceInformation/>",
                                      "http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation")
        r = body.find("tds:GetDeviceInformationResponse", NS)
        return {k: text(r, f"tds:{k}") for k in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber",
                                                  "HardwareId")}

    async def services(self) -> dict:
        """GetServices (ONVIF 2.x), else GetCapabilities: namespace-keyed service addresses + versions."""
        found = {}
        try:
            body = await self.client.call(self.device_url,
                                          "<tds:GetServices><tds:IncludeCapability>true</tds:IncludeCapability>"
                                          "</tds:GetServices>", "http://www.onvif.org/ver10/device/wsdl/GetServices")
            for svc in body.iterfind(".//tds:Service", NS):
                ns_ = text(svc, "tds:Namespace")
                ver = svc.find("tds:Version", NS)
                caps = svc.find("tds:Capabilities", NS)
                found[ns_] = {"xaddr": self.fix_addr(text(svc, "tds:XAddr")),
                              "version": f"{text(ver, 'tt:Major')}.{text(ver, 'tt:Minor')}" if ver is not None else None,
                              "caps": dict(caps[0].attrib) if caps is not None and len(caps) else {}}
        except SoapError:
            pass
        if not found:
            body = await self.client.call(self.device_url,
                                          "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>",
                                          "http://www.onvif.org/ver10/device/wsdl/GetCapabilities")
            caps = body.find(".//tds:Capabilities", NS)
            mapping = {"Events": NS["tev"], "Media": NS["trt"], "Analytics": NS["tan"], "Device": NS["tds"]}
            for el in caps if caps is not None else []:
                local = etree.QName(el).localname
                if local in mapping:
                    found[mapping[local]] = {"xaddr": self.fix_addr(text(el, "tt:XAddr")), "version": None, "caps": {
                        k: v for k, v in ((etree.QName(c).localname, c.text) for c in el) if v and v in ("true", "false")}}
            ext = caps.find("tt:Extension/tt:DeviceIO", NS) if caps is not None else None
            if ext is not None:
                found[NS["tmd"]] = {"xaddr": self.fix_addr(text(ext, "tt:XAddr")), "version": None, "caps": {}}
        for key, ns_ in (("events", NS["tev"]), ("media", NS["trt"]), ("analytics", NS["tan"]),
                         ("deviceio", NS["tmd"])):
            if ns_ in found and found[ns_]["xaddr"]:
                self.xaddrs[key] = found[ns_]["xaddr"]
        return found

    # ---------------------------------------------------------------- events
    async def event_properties(self) -> tuple[list[TopicInfo], dict, str]:
        body = await self.call("events", "<tev:GetEventProperties/>", f"{A_EV}/GetEventPropertiesRequest", timeout=20)
        r = body.find("tev:GetEventPropertiesResponse", NS)
        meta = {
            "fixed_topic_set": text(r, "tev:FixedTopicSet"),
            "topic_dialects": [e.text for e in r.iterfind("wsnt:TopicExpressionDialect", NS)] if r is not None else [],
            "message_dialects": [e.text for e in r.iterfind("tev:MessageContentFilterDialect", NS)] if r is not None else [],
        }
        return parse_topic_set(body), meta, etree.tostring(body, encoding="unicode")

    async def subscribe(self, seconds: int = 60, topic_filter: str | None = None) -> Subscription:
        filt = ""
        if topic_filter:
            filt = (f"<tev:Filter><wsnt:TopicExpression Dialect=\"http://www.onvif.org/ver10/tev/topicExpression/"
                    f"ConcreteSet\">{topic_filter}</wsnt:TopicExpression></tev:Filter>")
        body = await self.call("events", f"<tev:CreatePullPointSubscription>{filt}<tev:InitialTerminationTime>"
                                         f"PT{seconds}S</tev:InitialTerminationTime></tev:CreatePullPointSubscription>",
                               f"{A_EV}/CreatePullPointSubscriptionRequest")
        r = body.find("tev:CreatePullPointSubscriptionResponse", NS)
        ref = r.find("tev:SubscriptionReference", NS) if r is not None else None
        addr = None
        params = ""
        if ref is not None:
            for wsa in ("wsa", "wsa04"):
                addr = addr or text(ref, f"{wsa}:Address")
                rp = ref.find(f"{wsa}:ReferenceParameters", NS)
                if rp is not None and not params:
                    params = "".join(etree.tostring(c, encoding="unicode") for c in rp if isinstance(c.tag, str))
        if not addr:
            raise SoapError("bad-xml", "CreatePullPointSubscription: no subscription address")
        return Subscription(address=self.fix_addr(addr), ref_params=params, created_at=datetime.now(timezone.utc),
                            termination=text(r, "wsnt:TerminationTime"), camera_time=text(r, "wsnt:CurrentTime"))

    async def pull(self, sub: Subscription, wait_s: int = 5, limit: int = 100) -> tuple[list[Notification], dict]:
        body = await self.client.call(
            sub.address, f"<tev:PullMessages><tev:Timeout>PT{wait_s}S</tev:Timeout>"
                         f"<tev:MessageLimit>{limit}</tev:MessageLimit></tev:PullMessages>",
            f"{A_PP}/PullMessagesRequest", wsa=True, extra_headers=sub.ref_params, timeout=wait_s + 10)
        return parse_notifications(body)

    async def sync_point(self, sub: Subscription) -> None:
        """Ask the camera to resend the current state of every property topic (Initialized messages)."""
        await self.client.call(sub.address, "<tev:SetSynchronizationPoint/>", f"{A_PP}/SetSynchronizationPointRequest",
                               wsa=True, extra_headers=sub.ref_params)

    async def renew(self, sub: Subscription, seconds: int = 60) -> str | None:
        body = await self.client.call(sub.address, f"<wsnt:Renew><wsnt:TerminationTime>PT{seconds}S"
                                                   f"</wsnt:TerminationTime></wsnt:Renew>",
                                      f"{A_SM}/RenewRequest", wsa=True, extra_headers=sub.ref_params)
        return text(body, ".//wsnt:TerminationTime")

    async def unsubscribe(self, sub: Subscription) -> None:
        await self.client.call(sub.address, "<wsnt:Unsubscribe/>", f"{A_SM}/UnsubscribeRequest", wsa=True,
                               extra_headers=sub.ref_params, timeout=5)

    # ---------------------------------------------------------------- analytics + I/O (read only)
    async def analytics(self) -> dict:
        """Analytics modules and rules per analytics configuration (ONVIF Profile M / T): what the camera can detect
        and what is configured now. Needs Media (GetVideoAnalyticsConfigurations) + Analytics service."""
        out = {"configs": [], "error": None}
        try:
            body = await self.call("media", "<trt:GetVideoAnalyticsConfigurations/>",
                                   "http://www.onvif.org/ver10/media/wsdl/GetVideoAnalyticsConfigurations")
        except SoapError as exc:
            out["error"] = f"media: {exc.kind}"
            return out
        for cfg in body.iterfind(".//trt:Configurations", NS):
            token = cfg.get("token")
            entry = {"token": token, "name": text(cfg, "tt:Name"), "modules": [], "rules": [],
                     "supported_rules": [], "supported_modules": []}
            for mod in cfg.iterfind(".//tt:AnalyticsModule", NS):
                entry["modules"].append({"name": mod.get("Name"), "type": mod.get("Type")})
            for rule in cfg.iterfind(".//tt:Rule", NS):
                entry["rules"].append({"name": rule.get("Name"), "type": rule.get("Type")})
            if "analytics" in self.xaddrs and token:
                for op, key in (("GetSupportedRules", "supported_rules"),
                                ("GetSupportedAnalyticsModules", "supported_modules")):
                    try:
                        b = await self.call("analytics", f"<tan:{op}><tan:ConfigurationToken>{token}"
                                                         f"</tan:ConfigurationToken></tan:{op}>",
                                            f"http://www.onvif.org/ver20/analytics/wsdl/{op}")
                        entry[key] = sorted({d.get("Name") for d in b.iter()
                                             if isinstance(d.tag, str) and d.get("Name")
                                             and etree.QName(d).localname in ("RuleDescription",
                                                                              "AnalyticsModuleDescription")})
                    except SoapError as exc:
                        entry[key] = [f"error: {exc.kind}"]
            out["configs"].append(entry)
        return out

    async def io_ports(self) -> dict:
        out = {"inputs": None, "relays": None}
        try:
            b = await self.call("deviceio" if "deviceio" in self.xaddrs else "device",
                                "<tmd:GetDigitalInputs/>", "http://www.onvif.org/ver10/deviceIO/wsdl/GetDigitalInputs")
            out["inputs"] = [{"token": d.get("token"), "idle": d.get("IdleState")}
                             for d in b.iterfind(".//tmd:DigitalInputs", NS)]
        except SoapError as exc:
            out["inputs"] = f"error: {exc.kind}"
        try:
            b = await self.client.call(self.device_url, "<tds:GetRelayOutputs/>",
                                       "http://www.onvif.org/ver10/device/wsdl/GetRelayOutputs")
            out["relays"] = [{"token": r.get("token"), "mode": text(r, "tt:Properties/tt:Mode"),
                              "idle": text(r, "tt:Properties/tt:IdleState")}
                             for r in b.iterfind(".//tds:RelayOutputs", NS)]
        except SoapError as exc:
            out["relays"] = f"error: {exc.kind}"
        return out


def termination_seconds(sub: Subscription) -> float | None:
    """Seconds the camera granted (TerminationTime - CurrentTime), or a duration if it answered one."""
    if sub.termination and sub.termination.startswith("P"):
        return parse_duration(sub.termination)
    t, now = parse_time(sub.termination), parse_time(sub.camera_time)
    return (t - now).total_seconds() if t and now else None
