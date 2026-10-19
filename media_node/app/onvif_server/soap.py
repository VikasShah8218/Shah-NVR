"""Small, explicit SOAP surface for the initial H5 Device and Media services."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from lxml import etree

from app.node.utils import runtime
from settings.settings import settings

SOAP = "http://www.w3.org/2003/05/soap-envelope"
TDS = "http://www.onvif.org/ver10/device/wsdl"
TRT = "http://www.onvif.org/ver10/media/wsdl"
TRC = "http://www.onvif.org/ver10/recording/wsdl"
TSE = "http://www.onvif.org/ver10/search/wsdl"
TT = "http://www.onvif.org/ver10/schema"
TER = "http://www.onvif.org/ver10/error"
NS = {"s": SOAP, "tds": TDS, "trt": TRT, "trc": TRC, "tse": TSE, "tt": TT, "ter": TER}
PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


class SoapFault(Exception):
    def __init__(self, subcode: str, reason: str):
        super().__init__(reason)
        self.subcode, self.reason = subcode, reason


def parse(data: bytes) -> etree._Element:
    if len(data) > 1024 * 1024:
        raise SoapFault("ter:InvalidArgVal", "SOAP request is too large")
    try:
        root = etree.fromstring(data, PARSER)
    except etree.XMLSyntaxError as exc:
        raise SoapFault("ter:InvalidArgVal", "Malformed SOAP XML") from exc
    if etree.QName(root).localname != "Envelope":
        raise SoapFault("ter:InvalidArgVal", "SOAP Envelope is required")
    return root


def action(root: etree._Element) -> tuple[str, etree._Element]:
    body = root.find(f"{{{SOAP}}}Body")
    operation = next(iter(body), None) if body is not None else None
    if operation is None:
        raise SoapFault("ter:InvalidArgVal", "SOAP Body operation is required")
    return etree.QName(operation).localname, operation


def envelope(child: etree._Element) -> bytes:
    envelope = etree.Element(etree.QName(SOAP, "Envelope"), nsmap=NS)
    etree.SubElement(envelope, etree.QName(SOAP, "Header"))
    etree.SubElement(envelope, etree.QName(SOAP, "Body")).append(child)
    return etree.tostring(envelope, xml_declaration=True, encoding="UTF-8")


def fault(subcode: str, reason: str) -> bytes:
    node = etree.Element(etree.QName(SOAP, "Fault"))
    code = etree.SubElement(node, etree.QName(SOAP, "Code"))
    etree.SubElement(code, etree.QName(SOAP, "Value")).text = "s:Sender"
    etree.SubElement(etree.SubElement(code, etree.QName(SOAP, "Subcode")), etree.QName(SOAP, "Value")).text = subcode
    reason_node = etree.SubElement(node, etree.QName(SOAP, "Reason"))
    text = etree.SubElement(reason_node, etree.QName(SOAP, "Text"))
    text.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
    text.text = reason
    return envelope(node)


def _text(parent: etree._Element, namespace: str, name: str, value: object) -> etree._Element:
    child = etree.SubElement(parent, etree.QName(namespace, name))
    child.text = str(value).lower() if isinstance(value, bool) else str(value)
    return child


def _xaddr(service: str) -> str:
    return f"http://{settings.public_host}:{settings.PORT}/onvif/{service}"


def _assignments() -> list[dict]:
    return [a for a in runtime.assignments.values() if a.get("expose_via_onvif", True)]


def _profiles() -> list[tuple[str, dict, dict]]:
    return [
        (f"profile_cam_{camera['camera_id']}_{stream['profile']}", camera, stream)
        for camera in _assignments() for stream in camera.get("streams", [])
    ]


def _profile(token: str) -> tuple[str, dict, dict]:
    for item in _profiles():
        if item[0] == token:
            return item
    raise SoapFault("ter:InvalidToken", "Unknown media profile")


def _requested_token(operation: etree._Element) -> str:
    values = operation.xpath(".//*[local-name()='ProfileToken']/text()")
    if not values:
        raise SoapFault("ter:InvalidArgVal", "ProfileToken is required")
    return str(values[0])


def _device(operation: str) -> etree._Element:
    now = datetime.now(timezone.utc)
    if operation == "GetDeviceInformation":
        out = etree.Element(etree.QName(TDS, "GetDeviceInformationResponse"))
        for key, value in (("Manufacturer", "Shah-NVR"), ("Model", "Media Node"), ("FirmwareVersion", "0.1.0"),
                           ("SerialNumber", settings.NODE_NAME), ("HardwareId", settings.NODE_NAME)):
            _text(out, TDS, key, value)
        return out
    if operation == "GetSystemDateAndTime":
        out = etree.Element(etree.QName(TDS, "GetSystemDateAndTimeResponse"))
        system = etree.SubElement(out, etree.QName(TDS, "SystemDateAndTime"))
        _text(system, TT, "DateTimeType", "NTP")
        _text(system, TT, "DaylightSavings", False)
        utc = etree.SubElement(system, etree.QName(TT, "UTCDateTime"))
        tm = etree.SubElement(utc, etree.QName(TT, "Time"))
        for key, value in (("Hour", now.hour), ("Minute", now.minute), ("Second", now.second)):
            _text(tm, TT, key, value)
        date = etree.SubElement(utc, etree.QName(TT, "Date"))
        for key, value in (("Year", now.year), ("Month", now.month), ("Day", now.day)):
            _text(date, TT, key, value)
        return out
    if operation == "GetServices":
        out = etree.Element(etree.QName(TDS, "GetServicesResponse"))
        for namespace, xaddr in (
            (TDS, _xaddr("device_service")),
            (TRT, _xaddr("media_service")),
            (TRC, _xaddr("recording_service")),
            (TSE, _xaddr("search_service")),
        ):
            service = etree.SubElement(out, etree.QName(TDS, "Service"))
            _text(service, TDS, "Namespace", namespace)
            _text(service, TDS, "XAddr", xaddr)
            version = etree.SubElement(service, etree.QName(TDS, "Version"))
            _text(version, TT, "Major", 2); _text(version, TT, "Minor", 0)
        return out
    if operation == "GetCapabilities":
        out = etree.Element(etree.QName(TDS, "GetCapabilitiesResponse"))
        caps = etree.SubElement(out, etree.QName(TDS, "Capabilities"))
        device = etree.SubElement(caps, etree.QName(TT, "Device")); _text(device, TT, "XAddr", _xaddr("device_service"))
        media = etree.SubElement(caps, etree.QName(TT, "Media")); _text(media, TT, "XAddr", _xaddr("media_service"))
        extension = etree.SubElement(caps, etree.QName(TT, "Extension"))
        recording = etree.SubElement(extension, etree.QName(TT, "Recording"))
        _text(recording, TT, "XAddr", _xaddr("recording_service"))
        search = etree.SubElement(extension, etree.QName(TT, "Search"))
        _text(search, TT, "XAddr", _xaddr("search_service"))
        return out
    if operation == "GetServiceCapabilities":
        out = etree.Element(etree.QName(TDS, "GetServiceCapabilitiesResponse"))
        caps = etree.SubElement(out, etree.QName(TDS, "Capabilities"))
        network = etree.SubElement(caps, etree.QName(TDS, "Network"))
        network.set("IPFilter", "false"); network.set("ZeroConfiguration", "false")
        system = etree.SubElement(caps, etree.QName(TDS, "System"))
        system.set("DiscoveryResolve", "true"); system.set("DiscoveryBye", "false")
        return out
    if operation == "GetScopes":
        out = etree.Element(etree.QName(TDS, "GetScopesResponse"))
        values = ["onvif://www.onvif.org/type/Network_Video_Transmitter", "onvif://www.onvif.org/Profile/Streaming",
                  "onvif://www.onvif.org/name/" + quote(runtime.onvif_server_config.get("discovery_name") or "Shah-NVR")]
        if runtime.onvif_server_config.get("location"):
            values.append("onvif://www.onvif.org/location/" + quote(runtime.onvif_server_config["location"]))
        for value in values:
            scopes = etree.SubElement(out, etree.QName(TDS, "Scopes"))
            _text(scopes, TT, "ScopeDef", "Fixed"); _text(scopes, TT, "ScopeItem", value)
        return out
    if operation == "GetHostname":
        out = etree.Element(etree.QName(TDS, "GetHostnameResponse"))
        info = etree.SubElement(out, etree.QName(TDS, "HostnameInformation"))
        _text(info, TT, "FromDHCP", False); _text(info, TT, "Name", settings.NODE_NAME)
        return out
    if operation == "GetNetworkInterfaces":
        out = etree.Element(etree.QName(TDS, "GetNetworkInterfacesResponse"))
        interface = etree.SubElement(out, etree.QName(TDS, "NetworkInterfaces"))
        interface.set("token", "primary"); _text(interface, TT, "Enabled", True)
        info = etree.SubElement(interface, etree.QName(TT, "Info")); _text(info, TT, "Name", "primary")
        ipv4 = etree.SubElement(interface, etree.QName(TT, "IPv4")); _text(ipv4, TT, "Enabled", True)
        config = etree.SubElement(ipv4, etree.QName(TT, "Config"))
        manual = etree.SubElement(config, etree.QName(TT, "Manual"))
        _text(manual, TT, "Address", settings.public_host); _text(manual, TT, "PrefixLength", 24)
        _text(config, TT, "DHCP", False)
        return out
    raise SoapFault("ter:ActionNotSupported", f"Device action {operation} is not supported")


def _append_profile(out: etree._Element, token: str, camera: dict, stream: dict) -> None:
    profile = etree.SubElement(out, etree.QName(TRT, "Profiles"))
    profile.set("token", token); profile.set("fixed", "true")
    _text(profile, TT, "Name", f"{camera['camera_name']} - {stream['profile']}")
    source = etree.SubElement(profile, etree.QName(TT, "VideoSourceConfiguration"))
    source.set("token", f"source_cam_{camera['camera_id']}")
    _text(source, TT, "Name", camera["camera_name"]); _text(source, TT, "UseCount", 1)
    _text(source, TT, "SourceToken", f"source_cam_{camera['camera_id']}")


def _media(operation: str, request: etree._Element) -> etree._Element:
    if operation == "GetProfiles":
        out = etree.Element(etree.QName(TRT, "GetProfilesResponse"))
        for token, camera, stream in _profiles():
            _append_profile(out, token, camera, stream)
        return out
    if operation == "GetProfile":
        out = etree.Element(etree.QName(TRT, "GetProfileResponse"))
        _append_profile(out, *_profile(_requested_token(request)))
        return out
    if operation == "GetStreamUri":
        token, camera, stream = _profile(_requested_token(request))
        out = etree.Element(etree.QName(TRT, "GetStreamUriResponse"))
        uri = etree.SubElement(out, etree.QName(TRT, "MediaUri"))
        _text(uri, TT, "Uri", f"rtsp://{settings.public_host}:{settings.ONVIF_RTSP_PORT}/live/cam-{camera['camera_id']}/{stream['profile']}")
        _text(uri, TT, "InvalidAfterConnect", False); _text(uri, TT, "InvalidAfterReboot", False)
        _text(uri, TT, "Timeout", "PT60S")
        return out
    if operation in ("GetVideoEncoderConfigurations", "GetVideoSourceConfigurations", "GetVideoSources"):
        return etree.Element(etree.QName(TRT, operation + "Response"))
    if operation == "GetServiceCapabilities":
        out = etree.Element(etree.QName(TRT, "GetServiceCapabilitiesResponse"))
        etree.SubElement(out, etree.QName(TRT, "Capabilities"))
        return out
    raise SoapFault("ter:ActionNotSupported", f"Media action {operation} is not supported")


def dispatch(service: str, root: etree._Element) -> bytes:
    name, request = action(root)
    response = _device(name) if service == "device" else _media(name, request)
    return envelope(response)
