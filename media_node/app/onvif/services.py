"""One ONVIF device: clock, identity, services, media profiles, read-only settings and the H1 write actions.

Parsers are pure functions (unit-tested on XML recorded from real cameras in tests/fixtures/onvif).
"""

from __future__ import annotations

import ipaddress
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx
from lxml import etree

from app.onvif.soap import NS, Fault, NotAuthorized, NotSupported, OnvifError, SoapClient, Unreachable

_NO_LIMIT = 1_000_000  # kbps; cameras report 2147483647 for "unlimited"
VIDEO_CODECS = ("H264", "H265")


def _t(el, path: str) -> str | None:
    v = el.findtext(path, namespaces=NS) if el is not None else None
    return v.strip() if v and v.strip() else None


def _int(v: str | None) -> int | None:
    try:
        return int(float(v)) if v is not None else None
    except ValueError:
        return None


# ------------------------------------------------------------------ parsers
def parse_clock(body: etree._Element, node_now: float) -> dict:
    """GetSystemDateAndTime -> {offset_seconds (camera - node), source, timezone, camera_utc}."""
    sdt = body.find(".//tds:SystemDateAndTime", NS)
    out = {"offset_seconds": None, "source": _t(sdt, "tt:DateTimeType"), "timezone": _t(sdt, "tt:TimeZone/tt:TZ"),
           "camera_utc": None}
    utc = sdt.find("tt:UTCDateTime", NS) if sdt is not None else None
    if utc is not None:
        try:
            cam = datetime(*(int(_t(utc, p)) for p in ("tt:Date/tt:Year", "tt:Date/tt:Month", "tt:Date/tt:Day",
                                                        "tt:Time/tt:Hour", "tt:Time/tt:Minute", "tt:Time/tt:Second")),
                           tzinfo=timezone.utc)
            out["camera_utc"] = cam.isoformat()
            out["offset_seconds"] = round(cam.timestamp() - node_now, 1)
        except (TypeError, ValueError):
            pass
    return out


def parse_device_info(body: etree._Element) -> dict:
    r = body.find("tds:GetDeviceInformationResponse", NS)
    return {k.lower(): _t(r, f"tds:{k}") for k in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber", "HardwareId")}


def parse_services(body: etree._Element) -> dict[str, str]:
    """GetServices -> {namespace: xaddr}."""
    out = {}
    for s in body.iterfind(".//tds:Service", NS):
        ns, xaddr = _t(s, "tds:Namespace"), _t(s, "tds:XAddr")
        if ns and xaddr:
            out[ns] = xaddr
    return out


def parse_capabilities(body: etree._Element) -> dict[str, str]:
    """GetCapabilities (old devices without GetServices) -> {namespace: xaddr}."""
    mapping = {"Device": "http://www.onvif.org/ver10/device/wsdl", "Media": NS["trt"],
               "Events": "http://www.onvif.org/ver10/events/wsdl", "PTZ": "http://www.onvif.org/ver20/ptz/wsdl",
               "Imaging": "http://www.onvif.org/ver20/imaging/wsdl", "Analytics": "http://www.onvif.org/ver20/analytics/wsdl"}
    caps = body.find(".//tds:Capabilities", NS)
    out = {}
    for name, ns in mapping.items():
        x = _t(caps, f"tt:{name}/tt:XAddr")
        if x:
            out[ns] = x
    return out


def _bitrate(v: str | None) -> int | None:
    b = _int(v)
    return b if b and b < _NO_LIMIT else None


def parse_media1_profiles(body: etree._Element) -> list[dict]:
    out = []
    for p in body.iterfind(".//trt:Profiles", NS):
        enc = p.find("tt:VideoEncoderConfiguration", NS)
        out.append({
            "token": p.get("token"), "name": _t(p, "tt:Name"), "api": "media1",
            "encoding": (_t(enc, "tt:Encoding") or "").upper() or None,
            "width": _int(_t(enc, "tt:Resolution/tt:Width")), "height": _int(_t(enc, "tt:Resolution/tt:Height")),
            "fps": _int(_t(enc, "tt:RateControl/tt:FrameRateLimit")),
            "bitrate_kbps": _bitrate(_t(enc, "tt:RateControl/tt:BitrateLimit")),
            "has_audio": p.find("tt:AudioEncoderConfiguration", NS) is not None,
            "has_ptz": p.find("tt:PTZConfiguration", NS) is not None,
        })
    return out


def parse_media2_profiles(body: etree._Element) -> list[dict]:
    out = []
    for p in body.iterfind(".//tr2:Profiles", NS):
        conf = p.find("tr2:Configurations", NS)
        enc = conf.find("tr2:VideoEncoder", NS) if conf is not None else None
        encoding = (_t(enc, "tt:Encoding") or "").upper() or None
        out.append({
            "token": p.get("token"), "name": _t(p, "tr2:Name"), "api": "media2",
            "encoding": "H265" if encoding == "HEVC" else encoding,
            "width": _int(_t(enc, "tt:Resolution/tt:Width")), "height": _int(_t(enc, "tt:Resolution/tt:Height")),
            "fps": _int(_t(enc, "tt:RateControl/tt:FrameRateLimit")),
            "bitrate_kbps": _bitrate(_t(enc, "tt:RateControl/tt:BitrateLimit")),
            "has_audio": conf is not None and conf.find("tr2:AudioEncoder", NS) is not None,
            "has_ptz": conf is not None and conf.find("tr2:PTZ", NS) is not None,
        })
    return out


def parse_uri(body: etree._Element) -> str | None:
    return _t(body, ".//trt:MediaUri/tt:Uri") or _t(body, ".//tr2:Uri")


def parse_ntp(body: etree._Element) -> dict:
    info = body.find(".//tds:NTPInformation", NS)
    servers = []
    for tag in ("tt:NTPManual", "tt:NTPFromDHCP"):
        for e in info.iterfind(tag, NS) if info is not None else []:
            v = _t(e, "tt:IPv4Address") or _t(e, "tt:DNSname") or _t(e, "tt:IPv6Address")
            if v and v not in servers:
                servers.append(v)
    return {"from_dhcp": (_t(info, "tt:FromDHCP") or "").lower() == "true", "servers": servers}


def parse_hostname(body: etree._Element) -> str | None:
    return _t(body, ".//tds:HostnameInformation/tt:Name")


def parse_network(body: etree._Element) -> dict:
    nic = body.find(".//tds:NetworkInterfaces", NS)
    ipv4 = nic.find("tt:IPv4/tt:Config", NS) if nic is not None else None
    manual = ipv4.find("tt:Manual", NS) if ipv4 is not None else None
    from_dhcp = ipv4.find("tt:FromDHCP", NS) if ipv4 is not None else None
    addr = manual if manual is not None else from_dhcp
    return {"mac": _t(nic, "tt:Info/tt:HwAddress"), "dhcp": (_t(ipv4, "tt:DHCP") or "").lower() == "true",
            "ip": _t(addr, "tt:Address"), "prefix_length": _int(_t(addr, "tt:PrefixLength"))}


def suggest_streams(profiles: list[dict]) -> dict:
    """main = highest resolution video profile (then fps), sub = lowest one if it differs. JPEG is skipped."""
    video = [p for p in profiles if p.get("encoding") in VIDEO_CODECS and p.get("rtsp")]
    if not video:
        return {"main": None, "sub": None}
    key = lambda p: ((p.get("width") or 0) * (p.get("height") or 0), p.get("fps") or 0)  # noqa: E731
    main = max(video, key=key)
    rest = [p for p in video if p["token"] != main["token"] and key(p)[0] < key(main)[0]]
    sub = min(rest, key=key) if rest else None
    return {"main": main["token"], "sub": sub["token"] if sub else None}


def rehost(url: str, host: str) -> str:
    """Service addresses sometimes carry another IP (link-local, NAT, old DHCP lease): keep path/port, use our host."""
    parts = urlsplit(url)
    if not parts.hostname or parts.hostname == host:
        return url
    netloc = host if ":" not in host else f"[{host}]"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _is_ip(v: str) -> bool:
    try:
        ipaddress.ip_address(v)
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------ device
class OnvifDevice:
    """`async with OnvifDevice(host, port, user, password) as dev: await dev.probe()`."""

    def __init__(self, host: str, port: int = 80, username: str = "", password: str = "", *,
                 xaddr: str | None = None, timeout: float = 5.0):
        self.host, self.port = host, port
        self.device_url = xaddr or f"http://{host}:{port}/onvif/device_service"
        self._http = httpx.AsyncClient(timeout=timeout, verify=False)
        self.soap = SoapClient(self._http, username, password)
        self._services: dict[str, str] | None = None

    async def __aenter__(self) -> "OnvifDevice":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._http.aclose()

    # -------------------------------------------------------------- reads
    async def clock(self) -> dict:
        """Unauthenticated (ONVIF allows it); some devices still demand HTTP Digest -> one authenticated try."""
        body = "<tds:GetSystemDateAndTime/>"
        try:
            reply = await self.soap.call(self.device_url, body, auth=False)
        except NotAuthorized:
            if not self.soap.username:
                raise
            reply = await self.soap.call(self.device_url, body)
        clock = parse_clock(reply, time.time())
        if clock["offset_seconds"] is not None:
            self.soap.offset = clock["offset_seconds"]
        return clock

    async def info(self) -> dict:
        return parse_device_info(await self.soap.call(self.device_url, "<tds:GetDeviceInformation/>"))

    async def services(self) -> dict[str, str]:
        if self._services is None:
            try:
                found = parse_services(await self.soap.call(
                    self.device_url, "<tds:GetServices><tds:IncludeCapability>false</tds:IncludeCapability></tds:GetServices>"))
            except (NotSupported, Fault):
                found = parse_capabilities(await self.soap.call(
                    self.device_url, "<tds:GetCapabilities><tds:Category>All</tds:Category></tds:GetCapabilities>"))
            self._services = {ns: rehost(x, self.host) for ns, x in found.items()}
        return self._services

    async def profiles(self) -> list[dict]:
        """Video profiles with RTSP + snapshot URIs: Media2 when offered, else Media1."""
        services = await self.services()
        media2, media1 = services.get(NS["tr2"]), services.get(NS["trt"])
        profiles: list[dict] = []
        if media2:
            try:
                reply = await self.soap.call(media2, "<tr2:GetProfiles><tr2:Type>All</tr2:Type></tr2:GetProfiles>")
                profiles = parse_media2_profiles(reply)
                for p in profiles:
                    p["rtsp"] = await self._uri(media2, "<tr2:GetStreamUri><tr2:Protocol>RtspUnicast</tr2:Protocol>"
                                                f"<tr2:ProfileToken>{p['token']}</tr2:ProfileToken></tr2:GetStreamUri>")
                    p["snapshot"] = await self._uri(media2, "<tr2:GetSnapshotUri>"
                                                    f"<tr2:ProfileToken>{p['token']}</tr2:ProfileToken></tr2:GetSnapshotUri>")
            except (NotSupported, Fault):
                profiles = []
        if not profiles and (media1 or not media2):
            url = media1 or self.device_url
            profiles = parse_media1_profiles(await self.soap.call(url, "<trt:GetProfiles/>"))
            for p in profiles:
                p["rtsp"] = await self._uri(url, "<trt:GetStreamUri><trt:StreamSetup><tt:Stream>RTP-Unicast</tt:Stream>"
                                            "<tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport></trt:StreamSetup>"
                                            f"<trt:ProfileToken>{p['token']}</trt:ProfileToken></trt:GetStreamUri>")
                p["snapshot"] = await self._uri(url, f"<trt:GetSnapshotUri><trt:ProfileToken>{p['token']}</trt:ProfileToken></trt:GetSnapshotUri>")
        for p in profiles:
            for k in ("rtsp", "snapshot"):
                if p.get(k):
                    p[k] = rehost(p[k], self.host)
        return profiles

    async def _uri(self, url: str, body: str) -> str | None:
        try:
            return parse_uri(await self.soap.call(url, body))
        except (NotSupported, Fault):
            return None

    async def settings(self) -> dict:
        """Read-only device settings; each is optional (devices differ)."""
        out: dict = {"ntp": None, "hostname": None, "network": None}
        for key, body, parser in (("ntp", "<tds:GetNTP/>", parse_ntp), ("hostname", "<tds:GetHostname/>", parse_hostname),
                                  ("network", "<tds:GetNetworkInterfaces/>", parse_network)):
            try:
                out[key] = parser(await self.soap.call(self.device_url, body))
            except (NotSupported, Fault, NotAuthorized):
                pass  # NotAuthorized here = user level too low; SoapClient stops further logins anyway
        return out

    async def probe(self) -> dict:
        """Everything needed to add the camera. Raises NotAuthorized / Unreachable (nothing partial)."""
        clock = await self.clock()
        info = await self.info()
        services = await self.services()
        profiles = await self.profiles()
        return {
            "host": self.host, "port": self.port, "device_url": self.device_url, "clock": clock, "info": info,
            "services": sorted(services), "profiles": profiles, "suggested": suggest_streams(profiles),
        }

    async def snapshot(self, uri: str) -> tuple[bytes, str]:
        """JPEG from a snapshot URI of this device (Digest or Basic auth as the camera asks)."""
        if urlsplit(uri).hostname != self.host:
            raise Fault("snapshot URI is not on this device")
        try:
            r = await self._http.get(uri)
            if r.status_code == 401 and self.soap.username:
                scheme = r.headers.get("www-authenticate", "").lower()
                auth = (httpx.DigestAuth if scheme.startswith("digest") else httpx.BasicAuth)(self.soap.username, self.soap.password)
                r = await self._http.get(uri, auth=auth)
        except httpx.HTTPError as exc:
            raise Unreachable(f"snapshot: {type(exc).__name__}") from None
        if r.status_code == 401:
            raise NotAuthorized("snapshot: wrong username or password")
        if r.status_code >= 400:
            raise Fault(f"snapshot: HTTP {r.status_code}")
        return r.content, r.headers.get("content-type", "image/jpeg")

    # -------------------------------------------------------------- writes (explicit user actions only)
    async def set_time_from_node(self) -> dict:
        """Manual time = this node's UTC clock (the camera's time zone is kept)."""
        now = datetime.now(timezone.utc)
        await self.soap.call(self.device_url, (
            "<tds:SetSystemDateAndTime><tds:DateTimeType>Manual</tds:DateTimeType>"
            "<tds:DaylightSavings>false</tds:DaylightSavings><tds:UTCDateTime>"
            f"<tt:Date><tt:Year>{now.year}</tt:Year><tt:Month>{now.month}</tt:Month><tt:Day>{now.day}</tt:Day></tt:Date>"
            f"<tt:Time><tt:Hour>{now.hour}</tt:Hour><tt:Minute>{now.minute}</tt:Minute><tt:Second>{now.second}</tt:Second></tt:Time>"
            "</tds:UTCDateTime></tds:SetSystemDateAndTime>"))
        self.soap.offset = 0.0
        return await self.clock()

    async def set_ntp(self, from_dhcp: bool, servers: list[str]) -> dict:
        manual = "".join(
            f"<tds:NTPManual><tt:Type>IPv4</tt:Type><tt:IPv4Address>{s}</tt:IPv4Address></tds:NTPManual>" if _is_ip(s)
            else f"<tds:NTPManual><tt:Type>DNS</tt:Type><tt:DNSname>{s}</tt:DNSname></tds:NTPManual>"
            for s in ([] if from_dhcp else servers))
        await self.soap.call(self.device_url, f"<tds:SetNTP><tds:FromDHCP>{str(from_dhcp).lower()}</tds:FromDHCP>{manual}</tds:SetNTP>")
        await self.soap.call(self.device_url, "<tds:SetSystemDateAndTime><tds:DateTimeType>NTP</tds:DateTimeType>"
                                              "<tds:DaylightSavings>false</tds:DaylightSavings></tds:SetSystemDateAndTime>")
        return {"clock": await self.clock(), "ntp": parse_ntp(await self.soap.call(self.device_url, "<tds:GetNTP/>"))}

    async def reboot(self) -> str:
        reply = await self.soap.call(self.device_url, "<tds:SystemReboot/>")
        return _t(reply, ".//tds:Message") or "Rebooting"


__all__ = ["OnvifDevice", "OnvifError", "NotAuthorized", "Unreachable", "NotSupported", "Fault", "suggest_streams"]
