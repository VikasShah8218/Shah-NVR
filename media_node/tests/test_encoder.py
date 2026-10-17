"""H2 simulated devices: no physical cameras are contacted."""
import asyncio
import copy
import sys

import httpx
import pytest
from fastapi import HTTPException
from lxml import etree
from pydantic import ValidationError

from app.onvif import encoder
from app.onvif.encoder_schemas import EncoderState, EncoderValues
from app.onvif.services import OnvifDevice
from app.onvif.soap import NS, NotAuthorized, SoapClient


def xml(text):
    return etree.fromstring(('<root xmlns:tt="' + NS["tt"] + '" xmlns:trt="' + NS["trt"] +
                             '" xmlns:tr2="' + NS["tr2"] + '">' + text + '</root>').encode())


def config(ns="tr2"):
    attrs = ' GovLength="50" Profile="Main"' if ns == "tr2" else ""
    quality = "<tt:Quality>5</tt:Quality>"
    return xml(f'<{ns}:Configuration token="enc&amp;1"{attrs}><tt:Name>Main</tt:Name><tt:UseCount>1</tt:UseCount>'
               '<tt:Encoding>H264</tt:Encoding><tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>'
               + (quality if ns == "trt" else "") +
               '<tt:RateControl ConstantBitRate="false"><tt:FrameRateLimit>25</tt:FrameRateLimit>' +
               ('<tt:EncodingInterval>1</tt:EncodingInterval>' if ns == "trt" else '') +
               '<tt:BitrateLimit>4096</tt:BitrateLimit></tt:RateControl>' +
               ('<tt:H264><tt:GovLength>50</tt:GovLength><tt:H264Profile>Main</tt:H264Profile></tt:H264>' if ns == "trt" else "") +
               '<tt:Multicast><tt:Port>1234</tt:Port></tt:Multicast>' + (quality if ns == "tr2" else "") +
               '<tt:Extension vendor="preserve"/>' +
               f'</{ns}:Configuration>')[0]


def options(ns="tr2"):
    limits = ('<tt:ResolutionsAvailable><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:ResolutionsAvailable>'
              '<tt:ResolutionsAvailable><tt:Width>640</tt:Width><tt:Height>360</tt:Height></tt:ResolutionsAvailable>')
    quality = '<tt:QualityRange><tt:Min>1</tt:Min><tt:Max>10</tt:Max></tt:QualityRange>'
    bitrate = '<tt:BitrateRange><tt:Min>128</tt:Min><tt:Max>8192</tt:Max></tt:BitrateRange>'
    if ns == "tr2":
        return xml("".join(f'<tr2:Options GovLengthRange="1 150" FrameRatesSupported="25 12.5 5" '
                          f'ProfilesSupported="Main" ConstantBitRateSupported="true"><tt:Encoding>{c}</tt:Encoding>'
                          f'{quality}{limits}{bitrate}</tr2:Options>' for c in ("H264", "H265")))
    return xml(f'<trt:Options>{quality}<tt:H264>{limits}'
               '<tt:GovLengthRange><tt:Min>1</tt:Min><tt:Max>100</tt:Max></tt:GovLengthRange>'
               '<tt:FrameRateRange><tt:Min>1</tt:Min><tt:Max>30</tt:Max></tt:FrameRateRange>'
               '<tt:H264ProfilesSupported>Main</tt:H264ProfilesSupported></tt:H264>'
               f'<tt:Extension><tt:H264>{bitrate}</tt:H264></tt:Extension></trt:Options>')


class CameraSimulator:
    def __init__(self, ns="tr2", shared=False, fail_set=None, ignore_set=False, no_readback=False):
        self.ns, self.conf = ns, config(ns)
        self.shared, self.fail_set, self.ignore_set, self.no_readback = shared, fail_set, ignore_set, no_readback
        self.sets, self.requests = 0, []

    def handle(self, req):
        root = etree.fromstring(req.content)
        action = root.find("s:Body", NS)[0]
        name = etree.QName(action).localname
        self.requests.append(name)
        ns = self.ns
        if name == "SetVideoEncoderConfiguration":
            self.sets += 1
            sent = action.find(ns + ":Configuration", NS)
            assert sent.get("token") == "enc&1"
            assert sent.find("tt:Extension", NS).get("vendor") == "preserve"
            assert (action.find("trt:ForcePersistence", NS) is not None) == (ns == "trt")
            if not self.ignore_set:
                self.conf = copy.deepcopy(sent)
            if self.fail_set:
                raise httpx.ReadTimeout("simulated lost Set response", request=req)
            payload = f'<{ns}:SetVideoEncoderConfigurationResponse/>'
        elif name == "GetProfiles":
            if self.sets and self.no_readback:
                raise httpx.ConnectError("offline after write", request=req)
            if etree.QName(action).namespace == NS["tr2"] and ns == "trt":
                payload = '<s:Fault><s:Code><s:Value>s:Receiver</s:Value></s:Code><s:Reason><s:Text>ActionNotSupported</s:Text></s:Reason></s:Fault>'
            else:
                conf = copy.deepcopy(self.conf)
                conf.tag = etree.QName(NS[ns] if ns == "tr2" else NS["tt"], "VideoEncoder" if ns == "tr2" else "VideoEncoderConfiguration")
                conftext = etree.tostring(conf, encoding="unicode")
                p = f'<{ns}:Configurations>{conftext}</{ns}:Configurations>' if ns == "tr2" else conftext
                tokens = ["profile&amp;one", "shared"] if self.shared else ["profile&amp;one"]
                payload = f'<{ns}:GetProfilesResponse>' + "".join(f'<{ns}:Profiles token="{t}">{p}</{ns}:Profiles>' for t in tokens) + f'</{ns}:GetProfilesResponse>'
        elif name == "GetVideoEncoderConfigurationOptions":
            payload = etree.tostring(options(ns), encoding="unicode")
        else:
            conf = copy.deepcopy(self.conf)
            conf.tag = etree.QName(NS[ns], "Configurations" if ns == "tr2" else "Configuration")
            payload = etree.tostring(conf, encoding="unicode")
        envelope = ('<s:Envelope ' + " ".join(f'xmlns:{k}="{v}"' for k, v in NS.items()) +
                    '><s:Body>' + payload + '</s:Body></s:Envelope>')
        return httpx.Response(200, text=envelope)

    async def device(self):
        dev = OnvifDevice("camera")
        await dev._http.aclose()
        dev._http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
        dev.soap = SoapClient(dev._http, "user", "password")
        dev._services = {NS["tr2"]: "http://camera/media2", NS["trt"]: "http://camera/media1"}
        return dev


@pytest.mark.parametrize("ns", ["tr2", "trt"])
def test_read_validate_apply_preserves_config(ns):
    async def go():
        sim = CameraSimulator(ns)
        async with await sim.device() as dev:
            state, _, _ = await encoder.read(dev, "profile&one")
            EncoderState.model_validate(state)
            assert state["encoder_token"] == "enc&1" and state["api"] == ns
            assert state["options"][0]["bitrate_range"] == [128, 8192]
            result = await encoder.apply(dev, "profile&one", state["revision"], {"bitrate_kbps": 2048}, False)
            assert result["outcome"] == "verified" and sim.sets == 1
            assert result["after"]["current"]["bitrate_kbps"] == 2048
    asyncio.run(go())


def test_media2_codec_switch_fractional_fps_and_mode():
    async def go():
        sim = CameraSimulator()
        async with await sim.device() as dev:
            state, _, _ = await encoder.read(dev, "profile&one")
            result = await encoder.apply(dev, "profile&one", state["revision"],
                                         {"encoding": "H265", "fps": 12.5, "rate_control": "CBR"}, False)
            assert result["outcome"] == "verified"
            assert result["after"]["current"]["encoding"] == "H265"
    asyncio.run(go())


@pytest.mark.parametrize("patch", [{"fps": 26}, {"width": 123}, {"bitrate_kbps": 99999}, {"gop": 500},
                                   {"quality": 11}, {"codec_profile": "Unsupported"}])
def test_reject_unsupported_before_write(patch):
    async def go():
        sim = CameraSimulator()
        async with await sim.device() as dev:
            state, _, _ = await encoder.read(dev, "profile&one")
            with pytest.raises(HTTPException):
                await encoder.apply(dev, "profile&one", state["revision"], patch, False)
            assert sim.sets == 0
    asyncio.run(go())


def test_stale_and_shared_encoder_protection():
    async def go():
        sim = CameraSimulator(shared=True)
        async with await sim.device() as dev:
            state, _, _ = await encoder.read(dev, "profile&one")
            with pytest.raises(HTTPException):
                await encoder.apply(dev, "profile&one", "0" * 64, {"fps": 5}, True)
            with pytest.raises(HTTPException) as e:
                await encoder.apply(dev, "profile&one", state["revision"], {"fps": 5}, False)
            assert e.value.detail["code"] == "shared_encoder" and sim.sets == 0
            assert (await encoder.apply(dev, "profile&one", state["revision"], {"fps": 5}, True))["outcome"] == "verified"
    asyncio.run(go())


@pytest.mark.parametrize("fail_set,ignore_set,no_readback,expected", [
    (True, False, False, "verified"), (True, True, False, "unknown"),
    (False, True, False, "mismatch"), (False, False, True, "unknown")])
def test_timeout_and_readback_never_repeat_set(fail_set, ignore_set, no_readback, expected):
    async def go():
        sim = CameraSimulator(fail_set=fail_set, ignore_set=ignore_set, no_readback=no_readback)
        async with await sim.device() as dev:
            state, _, _ = await encoder.read(dev, "profile&one")
            result = await encoder.apply(dev, "profile&one", state["revision"], {"fps": 5}, False)
            assert result["outcome"] == expected and sim.sets == 1
    asyncio.run(go())


def test_unmapped_returns_choices_without_guessing():
    async def go():
        sim = CameraSimulator()
        async with await sim.device() as dev:
            state, conf, _ = await encoder.read(dev, None)
            assert conf is None and state.get("current") is None
            assert state["profiles"][0]["token"] == "profile&one"
    asyncio.run(go())


def test_nonfinite_and_extra_fields_rejected():
    for value in ({"fps": float("nan")}, {"fps": float("inf")}, {"bitrate_kbps": -1}, {"bitrate_kbps": 0}, {"unknown": 1}):
        with pytest.raises(ValidationError):
            EncoderValues(**value)


@pytest.mark.parametrize("ns", ["tr2", "trt"])
@pytest.mark.parametrize("reported", ["0", "-1", "NaN", "INF", "broken", "4096.5"])
def test_invalid_reported_bitrate_is_unknown_not_a_response_failure(ns, reported):
    conf = config(ns)
    conf.find("tt:RateControl/tt:BitrateLimit", NS).text = reported
    warnings = []
    current = encoder.values(conf, ns, warnings)
    EncoderValues.model_validate(current)
    assert current["bitrate_kbps"] is None
    assert current["fps"] == 25 and current["width"] == 1920
    assert len(warnings) == 1 and "Storage estimate is unavailable" in warnings[0]
    assert conf.find("tt:RateControl/tt:BitrateLimit", NS).text == reported


@pytest.mark.parametrize("key,path,reported", [
    ("width", "tt:Resolution/tt:Width", "0"),
    ("height", "tt:Resolution/tt:Height", "1080.5"),
    ("fps", "tt:RateControl/tt:FrameRateLimit", "-1"),
    ("gop", "tt:H264/tt:GovLength", "0"),
    ("quality", "tt:Quality", "NaN"),
])
def test_other_malformed_numeric_read_fields_are_unavailable(key, path, reported):
    conf = config("trt")
    conf.find(path, NS).text = reported
    warnings = []
    current = encoder.values(conf, "trt", warnings)
    EncoderValues.model_validate(current)
    assert current[key] is None and len(warnings) == 1


def test_valid_zero_quality_fractional_fps_and_unlimited_sentinel_are_preserved():
    conf = config()
    conf.find("tt:Quality", NS).text = "0"
    conf.find("tt:RateControl/tt:FrameRateLimit", NS).text = "12.5"
    conf.find("tt:RateControl/tt:BitrateLimit", NS).text = "2147483647"
    warnings = []
    current = encoder.values(conf, "tr2", warnings)
    assert current["quality"] == 0 and current["fps"] == 12.5 and current["bitrate_kbps"] == 2147483647
    assert not warnings


@pytest.mark.parametrize("ns", ["tr2", "trt"])
def test_ptz_zero_bitrate_other_edits_preserve_xml_and_readback(ns):
    async def go():
        sim = CameraSimulator(ns, shared=True)
        sim.conf.find("tt:RateControl/tt:BitrateLimit", NS).text = "0"
        async with await sim.device() as dev:
            state, original, _ = await encoder.read(dev, "profile&one")
            EncoderState.model_validate(state)
            assert state["current"]["bitrate_kbps"] is None
            assert any("bitrate limit" in w for w in state["warnings"])
            # Unknown fields cannot be written, even if options advertise a range.
            with pytest.raises(HTTPException) as exc:
                await encoder.apply(dev, "profile&one", state["revision"], {"bitrate_kbps": 2048}, True)
            assert exc.value.detail["code"] == "unsupported" and sim.sets == 0
            with pytest.raises(HTTPException) as exc:
                await encoder.apply(dev, "profile&one", state["revision"], {"fps": 5}, False)
            assert exc.value.detail["code"] == "shared_encoder" and sim.sets == 0
            result = await encoder.apply(dev, "profile&one", state["revision"], {"fps": 5}, True)
            assert result["outcome"] == "verified" and sim.sets == 1
            EncoderState.model_validate(result["after"])
            assert sim.conf.find("tt:RateControl/tt:BitrateLimit", NS).text == "0"
            # Revisions continue to cover raw XML, not the normalized public values.
            sim.conf.find("tt:RateControl/tt:BitrateLimit", NS).text = "-1"
            next_state, _, _ = await encoder.read(dev, "profile&one")
            assert next_state["current"]["bitrate_kbps"] is None
            assert next_state["revision"] != result["after"]["revision"]
    asyncio.run(go())


def test_use_count_requires_ack_even_when_other_profiles_are_hidden():
    async def go():
        sim = CameraSimulator()
        sim.conf.find("tt:UseCount", NS).text = "2"
        async with await sim.device() as dev:
            state, _, _ = await encoder.read(dev, "profile&one")
            assert len(state["shared_profiles"]) == 1 and state["use_count"] == 2
            with pytest.raises(HTTPException) as e:
                await encoder.apply(dev, "profile&one", state["revision"], {"fps": 5}, False)
            assert e.value.detail["code"] == "shared_encoder" and sim.sets == 0
    asyncio.run(go())


def test_revision_ignores_namespace_prefixes_and_whitespace():
    a = config()
    b = etree.fromstring(etree.tostring(a, pretty_print=True))
    assert encoder.semantic(a) == encoder.semantic(b)


def test_missing_media1_bitrate_options_are_not_invented():
    body = options("trt")
    body[0].remove(body[0].find("tt:Extension", NS))
    assert encoder.parse_options(body, "trt")[0]["bitrate_range"] is None


def test_auth_failure_stops_readback(monkeypatch):
    async def go():
        sim = CameraSimulator()
        async with await sim.device() as dev:
            state, _, _ = await encoder.read(dev, "profile&one")
            original = encoder.call
            async def call(d, url, el):
                if etree.QName(el).localname.startswith("Set"):
                    raise NotAuthorized("denied")
                return await original(d, url, el)
            monkeypatch.setattr(encoder, "call", call)
            with pytest.raises(NotAuthorized):
                await encoder.apply(dev, "profile&one", state["revision"], {"fps": 5}, False)
    asyncio.run(go())


def test_lock_serializes_device_alias_case_and_cleans_up():
    lock = encoder.device_lock("CAMERA.", 80)
    assert lock is encoder.device_lock("camera", 80)


def alternative_state():
    full = encoder.parse_options(options(), "tr2")[0]
    full.update(frame_rates=[25], resolutions=[[1920, 1080]])
    low = {**copy.deepcopy(full), "frame_rates": [5], "resolutions": [[640, 360]], "bitrate_range": [128, 2048]}
    return {"api": "tr2", "current": encoder.values(config(), "tr2"), "options": [low, full],
            "shared_profiles": ["main"], "use_count": 1}


def test_multiple_options_match_second_complete_entry():
    state = alternative_state()
    changes, target = encoder.validate(state, {"bitrate_kbps": 6000})
    assert changes == {"bitrate_kbps": 6000} and target["width"] == 1920


def test_multiple_options_allow_switching_to_another_complete_combination():
    state = alternative_state()
    patch = {"width": 640, "height": 360, "fps": 5, "bitrate_kbps": 1024}
    assert encoder.validate(state, patch)[0] == patch


@pytest.mark.parametrize("patch,field", [
    ({"fps": 5, "bitrate_kbps": 1024}, "fps"),
    ({"width": 640, "height": 360, "fps": 5, "bitrate_kbps": 6000}, "bitrate_kbps"),
    ({"quality": 99}, "quality"),
])
def test_mixed_alternative_limits_are_rejected(patch, field):
    state = alternative_state()
    with pytest.raises(HTTPException) as exc:
        encoder.validate(state, patch)
    assert exc.value.detail["code"] == "unsupported"
    assert field in exc.value.detail["message"]
    assert "complete settings combination" in exc.value.detail["message"]


def test_missing_options_has_distinct_actionable_error():
    state = alternative_state()
    state["options"] = []
    with pytest.raises(HTTPException) as exc:
        encoder.validate(state, {"bitrate_kbps": 2048})
    assert "did not advertise encoder options for H264" in exc.value.detail["message"]


def test_unknown_limits_preserved_only_for_unchanged_same_codec_fields():
    state = alternative_state()
    state["options"] = [state["options"][1]]
    state["options"][0]["bitrate_range"] = None
    assert encoder.validate(state, {"quality": 4})[0] == {"quality": 4}
    with pytest.raises(HTTPException):
        encoder.validate(state, {"bitrate_kbps": 2048})


@pytest.mark.parametrize("key,choices,bad", [
    ("codec_profile", "codec_profiles", "High"), ("rate_control", "rate_controls", "CBR"),
])
def test_unchanged_profile_or_mode_cannot_borrow_another_options_limits(key, choices, bad):
    state = alternative_state()
    state["current"][key] = bad
    for option in state["options"]:
        option[choices] = ["Main"] if key == "codec_profile" else ["VBR"]
    with pytest.raises(HTTPException) as exc:
        encoder.validate(state, {"bitrate_kbps": 2048})
    assert key in exc.value.detail["message"]


@pytest.mark.parametrize("duplicate", [True, False])
def test_media2_multiple_h265_entries_end_to_end(monkeypatch, duplicate):
    original = options
    def multi_options(ns="tr2"):
        result = original(ns)
        if ns == "tr2":
            result[1].set("FrameRatesSupported", "18")
            result[1].set("GovLengthRange", "2 255")
            result[1].find("tt:BitrateRange/tt:Min", NS).text = "1024"
            result[1].find("tt:BitrateRange/tt:Max", NS).text = "8000"
            result[1].find("tt:QualityRange/tt:Min", NS).text = "0"
            result[1].find("tt:QualityRange/tt:Max", NS).text = "5"
            alternative = copy.deepcopy(result[1])
            if not duplicate:
                # First H265 entry deliberately cannot support the current resolution/rate.
                result[1].find("tt:ResolutionsAvailable/tt:Width", NS).text = "1280"
                result[1].set("FrameRatesSupported", "5")
            result.append(alternative)
        return result
    monkeypatch.setattr(sys.modules[__name__], "options", multi_options)
    async def go():
        sim = CameraSimulator()
        sim.conf.find("tt:Encoding", NS).text = "H265"
        sim.conf.find("tt:RateControl/tt:FrameRateLimit", NS).text = "18"
        sim.conf.find("tt:RateControl/tt:BitrateLimit", NS).text = "1024"
        sim.conf.set("GovLength", "20")
        sim.conf.attrib.pop("Profile")
        async with await sim.device() as dev:
            state, _, _ = await encoder.read(dev, "profile&one")
            assert len([o for o in state["options"] if o["encoding"] == "H265"]) == 2
            result = await encoder.apply(dev, "profile&one", state["revision"], {"bitrate_kbps": 4096}, False)
            assert result["outcome"] == "verified" and sim.sets == 1
    asyncio.run(go())


@pytest.mark.parametrize("zero_bitrate", [False, True])
def test_node_http_contract_preflight_apply_and_invalid_body(monkeypatch, zero_bitrate):
    from fastapi import FastAPI
    from app.onvif import router
    from app.mediamtx import services
    sim = CameraSimulator()
    if zero_bitrate:
        sim.conf.find("tt:RateControl/tt:BitrateLimit", NS).text = "0"
    class SimDevice(OnvifDevice):
        def __init__(self, *args, **kwargs):
            self.host = "camera"
            self.device_url = "http://camera/device"
            self._http = httpx.AsyncClient(transport=httpx.MockTransport(sim.handle))
            self.soap = SoapClient(self._http, "user", "password")
            self._services = {NS["tr2"]: "http://camera/media2"}
        async def clock(self):
            return {}
    async def restart(ids):
        return {"cam-1/main": "pending"}
    monkeypatch.setattr(router, "OnvifDevice", SimDevice)
    monkeypatch.setattr(services, "restart_camera_paths", restart)
    app = FastAPI()
    app.include_router(router.router)
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://node") as client:
            body = {"host": "camera", "profile_token": "profile&one"}
            response = await client.post("/api/v1/onvif/encoder/read", json=body)
            assert response.status_code == 200, response.text
            state = response.json()
            if zero_bitrate:
                assert state["current"]["bitrate_kbps"] is None
                assert any("bitrate limit" in w for w in state["warnings"])
            write = {**body, "revision": state["revision"], "values": {"fps": 5} if zero_bitrate else {"bitrate_kbps": 2048}, "camera_ids": [1]}
            assert (await client.post("/api/v1/onvif/encoder/check", json=write)).status_code == 200
            assert sim.sets == 0
            invalid = {**write, "values": {"password": "not-an-encoder-field"}}
            assert (await client.post("/api/v1/onvif/encoder/apply", json=invalid)).status_code == 422
            invalid_bitrate = {**write, "values": {"bitrate_kbps": 0}}
            assert (await client.post("/api/v1/onvif/encoder/check", json=invalid_bitrate)).status_code == 422
            assert (await client.post("/api/v1/onvif/encoder/apply", json=invalid_bitrate)).status_code == 422
            result = await client.post("/api/v1/onvif/encoder/apply", json=write)
            assert result.status_code == 200, result.text
            assert result.json()["outcome"] == "verified"
            assert result.json()["recovery"] == {"cam-1/main": "pending"}
            assert sim.sets == 1
    asyncio.run(go())
