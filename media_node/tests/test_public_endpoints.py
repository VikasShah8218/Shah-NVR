from app.node.services import desired_webrtc_hosts
from utilities import netaddr


def test_public_webrtc_host_is_added_without_losing_lan_host(monkeypatch):
    monkeypatch.setattr(netaddr, "_current", "192.168.1.115")
    assert desired_webrtc_hosts({"webrtc_additional_hosts": ["192.168.1.115", "nvr.example.com", "nvr.example.com"]}) == [
        "192.168.1.115", "nvr.example.com",
    ]
