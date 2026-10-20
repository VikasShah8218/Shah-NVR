"""ONVIF client: parsers on XML recorded from real cameras (tests/fixtures/onvif), fault mapping, lockout safety."""

import asyncio
import base64
import hashlib
from pathlib import Path

import httpx
import pytest
from lxml import etree

from app.onvif import discovery, services
from app.onvif.soap import NS, Fault, NotAuthorized, NotSupported, SoapClient, classify_fault, parse_response, security_header

FIX = Path(__file__).parent / "fixtures" / "onvif"


def body(name: str) -> etree._Element:
    status = int(name.rsplit("_http", 1)[1]) if "_http" in name else 200
    return parse_response(status, (FIX / f"{name}.xml").read_bytes())


# ---------------------------------------------------------------- discovery
def test_probe_match_axis_skips_link_local_and_decodes_scopes():
    [dev] = discovery.parse_probe_match((FIX / "probematch_192.168.1.241.xml").read_bytes(), "192.168.1.241")
    assert dev["xaddr"] == "http://192.168.1.241/onvif/device_service"  # 169.254.x listed first by the camera
    assert dev["host"] == "192.168.1.241" and dev["port"] == 80
    assert dev["name"] == "AXIS M1125" and dev["hardware"] == "M1125"
    assert dev["profiles"] == ["Streaming", "G"]
    assert dev["endpoint"].startswith("urn:uuid:")


def test_probe_match_prefers_http_and_ignores_empty_scopes():
    [dev] = discovery.parse_probe_match((FIX / "probematch_192.168.1.190.xml").read_bytes(), "192.168.1.190")
    assert dev["xaddr"] == "http://192.168.1.190:80/onvif/device_service"
    assert dev["name"] is None and dev["location"] is None  # "name/" and "location/country/" carry nothing
    assert dev["hardware"] == "SC-IND42XP-I(Z)(S)"
    assert dev["profiles"] == ["Streaming", "T", "G", "M"]


def test_all_lab_devices_parse():
    hosts = set()
    for f in FIX.glob("probematch_*.xml"):
        ip = f.stem.split("_", 1)[1]
        for dev in discovery.parse_probe_match(f.read_bytes(), ip):
            hosts.add(dev["host"])
    assert len(hosts) == 10 and not any(h.startswith("169.254.") for h in hosts)


def test_non_camera_reply_is_ignored():
    printer = (b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
               b'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"><s:Body><d:ProbeMatches><d:ProbeMatch>'
               b"<d:Types>wsdp:Device print:PrintDeviceType</d:Types><d:XAddrs>http://192.168.1.12:5357/x</d:XAddrs>"
               b"</d:ProbeMatch></d:ProbeMatches></s:Body></s:Envelope>")
    assert discovery.parse_probe_match(printer, "192.168.1.12") == []
    assert discovery.parse_probe_match(b"garbage", "1.2.3.4") == []


# ---------------------------------------------------------------- device replies
def test_clock_offset():
    clock = services.parse_clock(body("time_192.168.1.241_http200"), node_now=0)
    assert clock["source"] == "NTP" and clock["offset_seconds"] > 1e9  # camera time - epoch 0
    assert clock["camera_utc"].endswith("+00:00")


def test_time_requiring_http_auth_is_not_authorized():
    with pytest.raises(NotAuthorized):
        body("time_192.168.1.190_http401")


def test_axis_identity_services_profiles():
    info = services.parse_device_info(body("axis_GetDeviceInformation_http200"))
    assert info["manufacturer"] == "AXIS" and info["model"] == "AXIS M1125" and info["serialnumber"] == "ACCC8E23943A"
    svc = services.parse_services(body("axis_GetServices_http200"))
    assert NS["trt"] in svc and NS["tr2"] not in svc
    caps = services.parse_capabilities(body("axis_GetCapabilities_http200"))
    assert NS["trt"] in caps
    profiles = services.parse_media1_profiles(body("axis_Media1_GetProfiles_http200"))
    assert [(p["token"], p["encoding"], p["width"], p["height"], p["fps"]) for p in profiles] == [
        ("profile_1_h264", "H264", 1280, 720, 30), ("profile_1_jpeg", "JPEG", 1280, 720, 30)]
    assert profiles[0]["bitrate_kbps"] is None  # 2147483647 = unlimited
    uri = services.parse_uri(body("axis_Media1_GetStreamUri_http200"))
    assert uri.startswith("rtsp://192.168.1.241/onvif-media/media.amp?profile=profile_1_h264")
    assert services.parse_uri(body("axis_Media1_GetSnapshotUri_http200")).startswith("http://192.168.1.241/")


def test_axis_settings():
    assert services.parse_ntp(body("axis_GetNTP_http200"))["from_dhcp"] is True
    assert services.parse_hostname(body("axis_GetHostname_http200"))
    net = services.parse_network(body("axis_GetNetworkInterfaces_http200"))
    assert net["mac"].lower() == "ac:cc:8e:23:94:3a" and net["ip"] == "192.168.1.241" and net["dhcp"] is False


def test_axis_media2_fault_is_a_fault():
    with pytest.raises(Fault):
        body("axis_Media2_GetProfiles_http500")


def test_media1_audio_configuration_is_reported():
    xml = etree.fromstring(b'''<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
      xmlns:trt="http://www.onvif.org/ver10/media/wsdl" xmlns:tt="http://www.onvif.org/ver10/schema">
      <s:Body><trt:GetProfilesResponse><trt:Profiles token="p1"><tt:Name>Main</tt:Name>
      <tt:VideoEncoderConfiguration token="v1"><tt:Encoding>H264</tt:Encoding></tt:VideoEncoderConfiguration>
      <tt:AudioEncoderConfiguration token="a1"><tt:Encoding>AAC</tt:Encoding><tt:Bitrate>128</tt:Bitrate>
      <tt:SampleRate>48000</tt:SampleRate><tt:Channels>2</tt:Channels></tt:AudioEncoderConfiguration>
      </trt:Profiles></trt:GetProfilesResponse></s:Body></s:Envelope>''')
    [profile] = services.parse_media1_profiles(xml.find("{http://www.w3.org/2003/05/soap-envelope}Body"))
    assert profile["has_audio"] is True
    assert profile["audio_encoder_token"] == "a1"
    assert profile["audio_codec"] == "aac"
    assert profile["audio_bitrate_kbps"] == 128
    assert profile["audio_sample_rate"] == 48000
    assert profile["audio_channels"] == 2


@pytest.mark.parametrize("status,text,kind", [
    (400, "SOAP-ENV:Sender ter:NotAuthorized Sender not authorized", NotAuthorized),
    (400, "Sender not Authorized. Invalid username or password! You still have 0 attempt(s).", NotAuthorized),
    (401, "", NotAuthorized),
    (400, "env:Sender ter:ActionNotSupported", NotSupported),
    (405, "", NotSupported),
    (500, "SOAP-ENV:Receiver ter:Action Action failed", Fault),
])
def test_fault_classification(status, text, kind):
    assert type(classify_fault(status, text)) is kind


def test_suggest_main_and_sub():
    p = lambda t, w, h, enc="H264", fps=25: {"token": t, "width": w, "height": h, "encoding": enc, "fps": fps, "rtsp": "rtsp://x"}  # noqa: E731
    assert services.suggest_streams([p("a", 640, 360), p("b", 1920, 1080), p("c", 1920, 1080, "JPEG")]) == {"main": "b", "sub": "a"}
    assert services.suggest_streams([p("only", 1280, 720)]) == {"main": "only", "sub": None}
    assert services.suggest_streams([p("j", 1280, 720, "JPEG")]) == {"main": None, "sub": None}
    assert services.suggest_streams([p("a", 1280, 720, fps=15), p("b", 1280, 720, fps=30)]) == {"main": "b", "sub": None}


def test_rehost():
    assert services.rehost("http://169.254.1.2/onvif/services", "192.168.1.241") == "http://192.168.1.241/onvif/services"
    assert services.rehost("http://10.0.0.5:8000/a?b=1", "192.168.1.9") == "http://192.168.1.9:8000/a?b=1"
    assert services.rehost("rtsp://192.168.1.241/x", "192.168.1.241") == "rtsp://192.168.1.241/x"


# ---------------------------------------------------------------- SOAP client
def test_security_header_digest_and_clock_offset():
    nonce = b"0123456789abcdef"
    h = security_header("root", "pw", offset=-3600, nonce=nonce, now=1_800_000_000)
    created = "2027-01-15T07:00:00.000Z"  # 1_800_000_000 - 1 h
    assert f"<wsu:Created>{created}</wsu:Created>" in h
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + b"pw").digest()).decode()
    assert digest in h and "<wsse:Username>root</wsse:Username>" in h


def run(coro):
    return asyncio.run(coro)


def test_no_second_login_after_auth_failure():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(400, content=(FIX / "time_192.168.1.190_http401.xml").read_bytes().replace(
            b"Error 401: HTTP 401 Unauthorized", b"ter:NotAuthorized Sender not authorized"))

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            soap = SoapClient(http, "root", "wrong")
            with pytest.raises(NotAuthorized):
                await soap.call("http://cam/onvif/device_service", "<tds:GetDeviceInformation/>")
            with pytest.raises(NotAuthorized):
                await soap.call("http://cam/onvif/device_service", "<tds:GetProfiles/>")

    run(go())
    assert len(calls) == 1  # the second call never reached the camera


def test_http_digest_fallback():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request.headers.get("authorization", ""))
        if not request.headers.get("authorization"):
            return httpx.Response(401, headers={"WWW-Authenticate": 'Digest realm="cam", qop="auth", nonce="abc"'},
                                  content=(FIX / "time_192.168.1.190_http401.xml").read_bytes())
        return httpx.Response(200, content=(FIX / "axis_GetDeviceInformation_http200.xml").read_bytes())

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            soap = SoapClient(http, "admin", "pw")
            reply = await soap.call("http://cam/onvif/device_service", "<tds:GetDeviceInformation/>")
            assert services.parse_device_info(reply)["model"] == "AXIS M1125"
            assert soap.http_digest

    run(go())
    assert seen[0] == "" and any(s.startswith("Digest ") for s in seen[1:])


def test_unauthenticated_failure_does_not_block_logins():
    async def go():
        responses = iter([httpx.Response(401, content=(FIX / "time_192.168.1.190_http401.xml").read_bytes()),
                          httpx.Response(200, content=(FIX / "axis_GetDeviceInformation_http200.xml").read_bytes())])
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: next(responses))) as http:
            soap = SoapClient(http, "root", "pw")
            with pytest.raises(NotAuthorized):
                await soap.call("http://cam/x", "<tds:GetSystemDateAndTime/>", auth=False)
            assert soap.auth_failed is None
            await soap.call("http://cam/x", "<tds:GetDeviceInformation/>")

    run(go())


# ---------------------------------------------------------------- health loop
def test_health_reports_survive_a_failed_heartbeat():
    from app.onvif import health

    health.pending.clear()
    health.pending[1] = first = {"camera_id": 1, "reachable": True}
    sent = health.take_reports()
    health.pending[1] = newer = {"camera_id": 1, "reachable": False}  # a newer check while the heartbeat was in flight
    health.ack_reports(sent)
    assert health.pending == {1: newer} and first is not newer
    health.ack_reports(health.take_reports())
    assert health.pending == {}


def test_health_check_never_logs_in(monkeypatch):
    from app.onvif import health

    seen = []

    class FakeDevice:
        def __init__(self, host, port, *args, **kw):
            seen.append((host, port, args, kw))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def clock(self):
            raise NotAuthorized("wants login")

    monkeypatch.setattr(health, "OnvifDevice", FakeDevice)
    r = asyncio.run(health.check_camera(7, "192.168.1.190", 80))
    assert r["reachable"] is True and r["clock_offset_seconds"] is None
    assert seen == [("192.168.1.190", 80, (), {})]  # no username / password passed
