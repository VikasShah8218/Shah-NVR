"""WS-Discovery for ONVIF cameras: a multicast Probe sent from every LAN interface of this node.

Own implementation instead of the WSDiscovery library: in the lab that library also returned link-local (169.254.x)
duplicates and Windows WSD printers, and it sends from whatever interface the OS prefers (VPN / Hyper-V adapters).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
import uuid
from urllib.parse import unquote, urlsplit

from lxml import etree

from app.onvif.soap import NS
from utilities.netaddr import list_addresses

MULTICAST = ("239.255.255.250", 3702)
PROBE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<s:Envelope xmlns:s="{NS["s"]}" xmlns:a="{NS["wsa"]}" xmlns:d="{NS["d"]}" xmlns:dn="{NS["dn"]}">'
    '<s:Header><a:Action s:mustUnderstand="1">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>'
    "<a:MessageID>uuid:{mid}</a:MessageID><a:ReplyTo><a:Address>"
    "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</a:Address></a:ReplyTo>"
    '<a:To s:mustUnderstand="1">urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To></s:Header>'
    "<s:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></s:Body></s:Envelope>"
)
_LINK_LOCAL = ipaddress.ip_network("169.254.0.0/16")
_SCOPE_KEYS = {"name": "name", "hardware": "hardware", "location": "location", "mac": "mac"}


def parse_probe_match(data: bytes, from_ip: str) -> list[dict]:
    """ProbeMatches -> devices. Only NetworkVideoTransmitter entries; scopes decoded; best XAddr chosen."""
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError:
        return []
    out = []
    for m in root.iterfind(".//d:ProbeMatch", NS):
        types = (m.findtext("d:Types", namespaces=NS) or "").split()
        if not any(t.split(":")[-1] == "NetworkVideoTransmitter" for t in types):
            continue
        xaddrs = (m.findtext("d:XAddrs", namespaces=NS) or "").split()
        xaddr = pick_xaddr(xaddrs, from_ip)
        if not xaddr:
            continue
        info: dict = {
            "endpoint": (m.findtext("wsa:EndpointReference/wsa:Address", namespaces=NS) or "").strip() or from_ip,
            "xaddr": xaddr,
            "host": urlsplit(xaddr).hostname,
            "port": urlsplit(xaddr).port or (443 if xaddr.startswith("https") else 80),
            "name": None, "hardware": None, "location": None, "mac": None, "profiles": [],
        }
        for scope in (m.findtext("d:Scopes", namespaces=NS) or "").split():
            if not scope.lower().startswith("onvif://www.onvif.org/"):
                continue
            key, _, value = scope[len("onvif://www.onvif.org/"):].partition("/")
            value = unquote(value).strip()
            if not value or value.endswith("/"):  # "name/", "location/country/": nothing filled in
                continue
            if key.lower() == "profile":
                if value not in info["profiles"]:
                    info["profiles"].append(value)
            elif key.lower() in _SCOPE_KEYS and not info[_SCOPE_KEYS[key.lower()]]:
                info[_SCOPE_KEYS[key.lower()]] = value
        out.append(info)
    return out


def pick_xaddr(xaddrs: list[str], from_ip: str) -> str | None:
    """Prefer the plain-http address on the IP the reply came from; never a link-local one."""

    def host_ok(x: str) -> bool:
        try:
            return ipaddress.ip_address(urlsplit(x).hostname or "") not in _LINK_LOCAL
        except ValueError:
            return True  # a hostname

    usable = [x for x in xaddrs if x.startswith(("http://", "https://")) and host_ok(x)]
    for pred in (lambda x: urlsplit(x).hostname == from_ip and x.startswith("http://"),
                 lambda x: urlsplit(x).hostname == from_ip,
                 lambda x: x.startswith("http://"),
                 lambda x: True):
        for x in usable:
            if pred(x):
                return x
    return None


def _probe_interface(bind_ip: str, seconds: float) -> list[tuple[bytes, str]]:
    replies: list[tuple[bytes, str]] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        if bind_ip != "0.0.0.0":
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(bind_ip))
        sock.bind((bind_ip, 0))
        sock.settimeout(0.25)
        for _ in range(2):  # UDP may drop one
            sock.sendto(PROBE.format(mid=uuid.uuid4()).encode(), MULTICAST)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                data, (ip, _port) = sock.recvfrom(65535)
                replies.append((data, ip))
            except (socket.timeout, ConnectionResetError):
                continue
    except OSError:
        pass  # interface went away
    finally:
        sock.close()
    return replies


def interfaces_to_probe() -> list[str]:
    ips = [a["ip"] for a in list_addresses() if a["usable"]]
    return ips or ["0.0.0.0"]


async def discover(seconds: float = 3.0) -> list[dict]:
    """All ONVIF devices answering on this node's LAN interfaces, sorted by IP, one entry per endpoint."""
    ips = interfaces_to_probe()
    results = await asyncio.gather(*(asyncio.to_thread(_probe_interface, ip, seconds) for ip in ips))
    found: dict[str, dict] = {}
    for bind_ip, replies in zip(ips, results):
        for data, from_ip in replies:
            for dev in parse_probe_match(data, from_ip):
                dev["interface_ip"] = bind_ip
                found.setdefault(dev["endpoint"], dev)

    def sort_key(d: dict):
        try:
            return (0, ipaddress.ip_address(d["host"]))
        except ValueError:
            return (1, d["host"])

    return sorted(found.values(), key=sort_key)
