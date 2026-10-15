from utilities import netaddr
from utilities.netaddr import choose_lan_ip, resolve_public_host


def addrs(*pairs):
    return [{"interface": i, "ip": ip, "usable": netaddr._usable(i, ip)} for i, ip in pairs]


def test_skips_tailscale_and_prefers_lan():
    table = addrs(("Tailscale", "100.64.182.102"), ("Ethernet", "192.168.1.3"))
    assert choose_lan_ip(table, "100.64.182.102") == "192.168.1.3"


def test_skips_virtual_adapters():
    table = addrs(("VMware Network Adapter VMnet1", "192.168.10.1"), ("vEthernet (WSL)", "172.20.0.1"),
                  ("WiFi", "192.168.0.5"))
    assert choose_lan_ip(table, None) == "192.168.0.5"


def test_default_route_wins_when_usable():
    table = addrs(("Ethernet 2", "10.0.0.7"), ("WiFi", "192.168.0.5"))
    assert choose_lan_ip(table, "192.168.0.5") == "192.168.0.5"


def test_cgnat_range_is_skipped_even_with_a_plain_adapter_name():
    table = addrs(("Ethernet", "100.100.1.2"), ("Ethernet 2", "192.168.1.3"))
    assert choose_lan_ip(table, None) == "192.168.1.3"


def test_only_loopback():
    assert choose_lan_ip(addrs(("Loopback Pseudo-Interface 1", "127.0.0.1")), None) == "127.0.0.1"


def test_explicit_value_is_kept(monkeypatch):
    monkeypatch.setattr(netaddr, "detect_lan_ip", lambda: "192.168.1.3")
    assert resolve_public_host("nvr-server.local") == "nvr-server.local"
    assert resolve_public_host("auto") == "192.168.1.3"
    assert resolve_public_host("") == "192.168.1.3"
