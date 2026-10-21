import json

import httpx
import pytest
import respx

from app.core.api.central import CentralApi
from app.core.api.errors import ApiError
from app.features.dashboard.alerts import build_alerts
from app.features.onvif.helpers import (format_offset, onvif_error_text, parse_address, profile_labels,
                                        profile_options, service_names)

BASE = "http://central.test"

DISCOVERED = {
    "endpoint": "urn:uuid:axis", "host": "192.168.1.241", "port": 80,
    "xaddr": "http://192.168.1.241/onvif/device_service", "name": "Gate", "hardware": "M1125",
    "location": None, "mac": "AC:CC:8E:23:94:3A", "profiles": ["Streaming", "T"],
    "node_id": 2, "node_name": "node-2", "camera_id": None, "camera_name": None,
}
PROFILE = {
    "token": "main-token", "name": "Main", "api": "media1", "encoding": "H264", "width": 1280,
    "height": 720, "fps": 30, "bitrate_kbps": 2048, "has_audio": False, "has_ptz": False,
    "rtsp": "rtsp://192.168.1.241/onvif-media", "snapshot": "http://192.168.1.241/snapshot.jpg",
}
PROBE = {
    "node_id": 2, "host": "192.168.1.241", "port": 80,
    "device_url": "http://192.168.1.241/onvif/device_service",
    "clock": {"offset_seconds": -12.4, "source": "NTP", "timezone": "UTC+05:30", "camera_utc": "2026-10-16T00:00:00Z"},
    "info": {"manufacturer": "AXIS", "model": "M1125", "firmwareversion": "6.50.1.3",
             "serialnumber": "ACCC8E23943A", "hardwareid": "M1125"},
    "services": ["http://www.onvif.org/ver10/media/wsdl"], "profiles": [PROFILE],
    "suggested": {"main": "main-token", "sub": None}, "camera_id": None,
}


def test_address_profile_and_device_helpers():
    assert parse_address("192.168.1.64:8080/path") == ("192.168.1.64", 8080)
    assert parse_address("https://camera.local/onvif") == ("camera.local", 80)
    assert parse_address(" ") is None
    assert profile_labels(["Streaming", "T", "Streaming"]) == ["S", "T"]
    assert profile_options([PROFILE])[0] == {
        "value": "main-token", "label": "Main · H264 · 1280x720 · 30 fps · 2048 kbps"
    }
    assert service_names(["http://www.onvif.org/ver20/media/wsdl", "http://www.onvif.org/ver20/ptz/wsdl"]) == ["Media2", "PTZ"]


def test_clock_offset_formatting():
    assert format_offset(0.2) == "In sync"
    assert format_offset(-563) == "-9 min 23 s"
    assert format_offset(86400 * 10) == "+10 days"


def test_onvif_error_is_lockout_safe_and_friendly():
    error = ApiError(401, "Sender not authorized", code="not_authorized")
    text = onvif_error_text(error)
    assert "Wrong username or password" in text
    assert "Not retried automatically" in text


@respx.mock
def test_discover_probe_and_snapshot_api_contract():
    discover = respx.post(f"{BASE}/api/v1/onvif/discover").mock(return_value=httpx.Response(200, json=[DISCOVERED]))
    probe = respx.post(f"{BASE}/api/v1/onvif/probe").mock(return_value=httpx.Response(200, json=PROBE))
    respx.post(f"{BASE}/api/v1/onvif/snapshot").mock(return_value=httpx.Response(200, content=b"jpeg"))
    api = CentralApi(BASE)
    assert api.onvif_discover(2)[0].profiles == ["Streaming", "T"]
    assert discover.calls.last.request.content == b'{"node_id":2,"seconds":3.0}'
    body = {"node_id": 2, "host": "192.168.1.241", "port": 80, "xaddr": DISCOVERED["xaddr"],
            "username": "root", "password": "secret"}
    result = api.onvif_probe(body)
    assert result.info.model == "M1125" and result.suggested.main == "main-token"
    assert json.loads(probe.calls.last.request.content) == body
    assert api.onvif_snapshot({**body, "uri": PROFILE["snapshot"]}) == b"jpeg"


@respx.mock
def test_structured_onvif_error_keeps_code_and_detail():
    respx.post(f"{BASE}/api/v1/onvif/probe").mock(return_value=httpx.Response(
        401, json={"detail": {"code": "not_authorized", "message": "One login attempt failed"}}))
    with pytest.raises(ApiError) as caught:
        CentralApi(BASE).onvif_probe({"host": "camera", "username": "x", "password": "bad"})
    assert caught.value.code == "not_authorized"
    assert caught.value.detail["message"] == "One login attempt failed"


def test_onvif_dashboard_alerts_link_to_device_tab():
    camera = {
        "id": 4, "name": "Gate", "enabled": True, "assignment": {"node_id": 1}, "streams": [],
        "onvif_reachable": False, "clock_offset_seconds": -563,
    }
    alerts = build_alerts([camera], [])
    assert {alert["title"] for alert in alerts} == {
        "Gate: ONVIF is not answering", "Gate: camera clock is off",
    }
    assert all(alert["tab"] == "device" for alert in alerts)


@respx.mock
def test_add_device_and_management_api_contracts():
    from tests.test_api import CAMERA

    device = {"camera_id": 1, "node_id": 2, "host": "192.168.1.241", "port": 80,
              "clock": PROBE["clock"], "info": PROBE["info"], "services": PROBE["services"],
              "ntp": {"from_dhcp": False, "servers": ["clock.local"]}, "hostname": "gate",
              "network": None, "checked_at": "2026-10-16T00:00:00Z"}
    add = respx.post(f"{BASE}/api/v1/onvif/cameras").mock(return_value=httpx.Response(200, json={
        **CAMERA, "model": "M1125", "manufacturer": "AXIS", "onvif_host": "192.168.1.241"}))
    respx.get(f"{BASE}/api/v1/onvif/cameras/1/device").mock(return_value=httpx.Response(200, json=device))
    sync = respx.post(f"{BASE}/api/v1/onvif/cameras/1/time-sync").mock(
        return_value=httpx.Response(200, json=PROBE["clock"]))
    ntp = respx.post(f"{BASE}/api/v1/onvif/cameras/1/ntp").mock(
        return_value=httpx.Response(200, json={"message": "saved"}))
    reboot = respx.post(f"{BASE}/api/v1/onvif/cameras/1/reboot").mock(
        return_value=httpx.Response(200, json={"message": "rebooting"}))
    api = CentralApi(BASE)
    try:
        body = {"node_id": 2, "host": "192.168.1.241", "port": 80, "username": "admin", "password": "test",
                "name": "Gate", "enabled": True, "allow_duplicate": False,
                "streams": [{"profile": "main", "token": "main-token", "record": True}]}
        assert api.create_onvif_camera(body).to_qml()["model"] == "M1125"
        assert json.loads(add.calls.last.request.content) == body
        assert api.onvif_device(1).ntp.servers == ["clock.local"]
        assert api.onvif_time_sync(1).offset_seconds == -12.4
        assert sync.call_count == 1
        api.onvif_set_ntp(1, False, ["clock.local"])
        assert json.loads(ntp.calls.last.request.content) == {"from_dhcp": False, "servers": ["clock.local"]}
        assert api.onvif_reboot(1)["message"] == "rebooting"
        assert reboot.call_count == 1
    finally:
        api.close()


@pytest.mark.parametrize("address", ["camera:0", "camera:70000", "bad host", "ftp://camera", "http://user:pass@camera"])
def test_invalid_manual_addresses(address):
    assert parse_address(address) is None
