"""Which IP address this node gives to clients (cameras' live/playback links are built from it).

Rule: every link uses this PC's real LAN address (e.g. 192.168.x.x). VPN/overlay addresses
(100.64.0.0/10), loopback, link-local and virtual adapters (VMware, Hyper-V, WSL, Docker, VPN clients) are
never used: clients on the normal network cannot reach them. This holds even if PUBLIC_HOST in .env names
such an address; it is ignored with a warning.
"""

from __future__ import annotations

import ipaddress
import logging
import socket

import psutil

logger = logging.getLogger("node.netaddr")

# Address ranges that are never a LAN address clients can reach.
_EXCLUDED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),     # loopback
    ipaddress.ip_network("169.254.0.0/16"),  # link-local (no DHCP)
    ipaddress.ip_network("100.64.0.0/10"),   # CGNAT range used by VPN overlays
]
# Interface names of VPN / virtual adapters (compared lower-case, substring); never advertised.
_EXCLUDED_ADAPTERS = ("tailscale", "zerotier", "wireguard", "vmware", "virtualbox", "vethernet", "hyper-v",
                      "wsl", "docker", "loopback", "npcap", "vpn", "tap-", "tun")
_PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12")]


def _usable(interface: str, ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if any(addr in net for net in _EXCLUDED_NETS):
        return False
    name = interface.lower()
    return not any(tag in name for tag in _EXCLUDED_ADAPTERS)


def list_addresses() -> list[dict]:
    """Every IPv4 address of an interface that is up: [{"interface", "ip", "usable"}]."""
    stats = psutil.net_if_stats()
    out = []
    for interface, addrs in psutil.net_if_addrs().items():
        if interface in stats and not stats[interface].isup:
            continue
        for a in addrs:
            if a.family == socket.AF_INET:
                out.append({"interface": interface, "ip": a.address, "usable": _usable(interface, a.address)})
    return out


def _default_route_ip() -> str | None:
    """Source address the OS would use for the internet (no packet is sent by a UDP connect)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def choose_lan_ip(addresses: list[dict], default_route_ip: str | None) -> str:
    """Pure decision (unit-tested): default-route IP if it is a usable LAN address, else the first private
    address, else any usable address, else 127.0.0.1."""
    usable = [a for a in addresses if a["usable"]]
    if default_route_ip and any(a["ip"] == default_route_ip for a in usable):
        return default_route_ip
    for a in usable:
        if any(ipaddress.ip_address(a["ip"]) in net for net in _PRIVATE_NETS):
            return a["ip"]
    if usable:
        return usable[0]["ip"]
    return "127.0.0.1"


def detect_lan_ip() -> str:
    ip = choose_lan_ip(list_addresses(), _default_route_ip())
    if ip == "127.0.0.1":
        logger.warning("No LAN address found: clients on other PCs will not reach this node (set PUBLIC_HOST)")
    return ip


def _is_lan_ip_or_hostname(value: str) -> bool:
    """A hostname, or an IP that is not loopback / link-local / VPN-overlay."""
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return True  # a hostname: the admin's choice
    return not any(addr in net for net in _EXCLUDED_NETS)


def resolve_public_host(setting: str) -> str:
    """PUBLIC_HOST value -> the host put into client links ("auto" = this PC's LAN IP).

    A VPN/loopback/link-local IP is never used, even when written in .env: the LAN IP is used instead."""
    value = (setting or "").strip()
    if value.lower() in ("", "auto"):
        return detect_lan_ip()
    if not _is_lan_ip_or_hostname(value):
        lan = detect_lan_ip()
        logger.warning("PUBLIC_HOST=%s is not a LAN address; using this PC's LAN IP %s instead "
                       "(set PUBLIC_HOST=auto in .env)", value, lan)
        return lan
    return value


_current: str | None = None


def public_host(setting: str) -> str:
    """The advertised host, resolved once and cached (see refresh_public_host)."""
    global _current
    if _current is None:
        _current = resolve_public_host(setting)
    return _current


def refresh_public_host(setting: str) -> bool:
    """Re-detect (e.g. DHCP gave a new address). Returns True when the advertised host changed."""
    global _current
    new = resolve_public_host(setting)
    changed = _current is not None and new != _current
    _current = new
    return changed
