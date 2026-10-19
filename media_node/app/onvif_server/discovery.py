"""WS-Discovery responder for the H5 virtual ONVIF NVR."""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from urllib.parse import quote

from lxml import etree

from app.node.utils import runtime
from settings.settings import settings

logger = logging.getLogger("node.onvif-discovery-server")
GROUP, PORT = "239.255.255.250", 3702
SOAP = "http://www.w3.org/2003/05/soap-envelope"
WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
WSD = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
TDS = "http://www.onvif.org/ver10/device/wsdl"
DN = "http://www.onvif.org/ver10/network/wsdl"


def response_xml(device_uuid: str, relates_to: str, resolve: bool = False) -> bytes:
    ns = {"s": SOAP, "a": WSA, "d": WSD, "tds": TDS, "dn": DN}
    env = etree.Element(etree.QName(SOAP, "Envelope"), nsmap=ns)
    head = etree.SubElement(env, etree.QName(SOAP, "Header"))
    etree.SubElement(head, etree.QName(WSA, "MessageID")).text = "urn:uuid:" + str(uuid.uuid4())
    etree.SubElement(head, etree.QName(WSA, "RelatesTo")).text = relates_to
    etree.SubElement(head, etree.QName(WSA, "To")).text = "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous"
    kind = "ResolveMatches" if resolve else "ProbeMatches"
    etree.SubElement(head, etree.QName(WSA, "Action")).text = f"{WSD}/{kind}"
    body = etree.SubElement(env, etree.QName(SOAP, "Body"))
    matches = etree.SubElement(body, etree.QName(WSD, kind))
    match = etree.SubElement(matches, etree.QName(WSD, "ResolveMatch" if resolve else "ProbeMatch"))
    ref = etree.SubElement(match, etree.QName(WSA, "EndpointReference"))
    etree.SubElement(ref, etree.QName(WSA, "Address")).text = "urn:uuid:" + device_uuid
    etree.SubElement(match, etree.QName(WSD, "Types")).text = "dn:NetworkVideoTransmitter tds:Device"
    name = quote(runtime.onvif_server_config.get("discovery_name") or "Shah-NVR")
    scopes = ["onvif://www.onvif.org/type/Network_Video_Transmitter", "onvif://www.onvif.org/Profile/Streaming",
              f"onvif://www.onvif.org/name/{name}"]
    if runtime.onvif_server_config.get("location"):
        scopes.append("onvif://www.onvif.org/location/" + quote(runtime.onvif_server_config["location"]))
    etree.SubElement(match, etree.QName(WSD, "Scopes")).text = " ".join(scopes)
    etree.SubElement(match, etree.QName(WSD, "XAddrs")).text = f"http://{settings.public_host}:{settings.PORT}/onvif/device_service"
    etree.SubElement(match, etree.QName(WSD, "MetadataVersion")).text = "1"
    return etree.tostring(env, xml_declaration=True, encoding="UTF-8")


class Protocol(asyncio.DatagramProtocol):
    def __init__(self, device_uuid: str):
        self.device_uuid, self.transport = device_uuid, None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr):
        try:
            root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))
            probe = bool(root.xpath(".//*[local-name()='Probe']"))
            resolve = bool(root.xpath(".//*[local-name()='Resolve']"))
            if not probe and not resolve:
                return
            ids = root.xpath(".//*[local-name()='MessageID']/text()")
            relates = str(ids[0]) if ids else ""
            self.transport.sendto(response_xml(self.device_uuid, relates, resolve), addr)
        except Exception as exc:
            logger.debug("Ignored malformed WS-Discovery datagram from %s: %s", addr, exc)


def multicast_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", PORT))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(GROUP) + socket.inet_aton("0.0.0.0"))
    sock.setblocking(False)
    return sock
