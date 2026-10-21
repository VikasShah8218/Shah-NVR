import asyncio
import time
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from lxml import etree
from pydantic import ValidationError
from app.onvif import ptz, ptz_router, illustra_ptz
from app.onvif.ptz_schemas import PtzCommand, PtzState
from app.onvif.soap import Fault, NotAuthorized, Unreachable


def xml(text):
    return etree.fromstring(f'<root xmlns:p="{ptz.PTZ}" xmlns:tt="{ptz.NS["tt"]}" xmlns:trt="{ptz.NS["trt"]}">{text}</root>')


STATUS = '<p:PTZStatus><tt:Position><tt:PanTilt x="21631" y="-9000"/><tt:Zoom x="100"/></tt:Position><tt:MoveStatus><tt:PanTilt>IDLE</tt:PanTilt><tt:Zoom>IDLE</tt:Zoom></tt:MoveStatus></p:PTZStatus>'


class Device:
    host = "camera"
    port = 80

    def __init__(self):
        async def media(*args):
            return xml('<trt:Profiles token="profile_1"><tt:PTZConfiguration token="cfg"/></trt:Profiles>')
        self.soap = SimpleNamespace(username="user", offset=3, http_digest=False, auth_failed=None, call=media)

    async def clock(self):
        pass

    async def services(self):
        return {ptz.PTZ: "http://camera/ptz", ptz.NS["trt"]: "http://camera/media"}


@pytest.fixture
def camera(monkeypatch):
    ptz.sessions.clear(); ptz.actors.clear()
    log = []
    async def call(dev, url, req):
        action = etree.QName(req).localname
        log.append((action, etree.tostring(req).decode()))
        if action == "GetConfigurations":
            return xml('<p:PTZConfiguration token="cfg"><tt:NodeToken>node</tt:NodeToken></p:PTZConfiguration>')
        if action == "GetNodes":
            return xml('<p:PTZNode token="node" FixedHomePosition="true"><tt:MaximumNumberOfPresets>300</tt:MaximumNumberOfPresets><tt:HomeSupported>false</tt:HomeSupported></p:PTZNode>')
        if action == "GetConfigurationOptions":
            spaces = ""
            for prefix, axes in (("PanTilt", ("X", "Y")), ("Zoom", ("X",))):
                ranges = ''.join(f'<tt:{a}Range><tt:Min>-1</tt:Min><tt:Max>1</tt:Max></tt:{a}Range>' for a in axes)
                spaces += f'<tt:Continuous{prefix}VelocitySpace><tt:URI>http://www.onvif.org/ver10/tptz/{prefix}Spaces/VelocityGenericSpace</tt:URI>{ranges}</tt:Continuous{prefix}VelocitySpace>'
            return xml(f'<tt:Spaces>{spaces}</tt:Spaces><tt:PTZTimeout><tt:Min>PT10S</tt:Min><tt:Max>PT4H0M0S</tt:Max></tt:PTZTimeout>')
        if action == "GetStatus":
            return xml(STATUS)
        if action == "GetPresets":
            return xml('<p:Preset token="existing"><tt:Name>Gate</tt:Name></p:Preset>')
        return xml("")
    monkeypatch.setattr(ptz, "call", call)
    monkeypatch.setattr(ptz, "PULSE_SECONDS", .001)
    return Device(), log, call


def command(sid, action="move", sequence=1, **kw):
    return PtzCommand(session_id=sid, action=action, sequence=sequence, **kw)


def test_illustra_status_and_device_gate():
    status = illustra_ptz.parse_status("pan=253.95\r\ntilt=-62.65\r\nzoom=1.00\r\npansp=0\r\ntiltsp=0\r\nzoomsp=0\r\n")
    assert status["pan_tilt_state"] == status["zoom_state"] == "IDLE"
    assert status["pan"] == 253.95 and not status["position_valid"]
    with pytest.raises(Fault):
        illustra_ptz.parse_status("pan=1\ntilt=2\nzoom=3")
    assert illustra_ptz.supported_device({"manufacturer": "Tyco Security Products", "model": "Illustra Pro4 4k IRPTZ Out"})
    assert not illustra_ptz.supported_device({"manufacturer": "Other", "model": "Illustra Pro4"})


def test_illustra_fallback_only_on_confirmed_http503(camera, monkeypatch):
    async def run():
        dev, _, old_call = camera
        async def broken(dev, url, req):
            if etree.QName(req).localname == "GetConfigurations":
                raise Fault("HTTP 503: not a SOAP reply")
            return await old_call(dev, url, req)
        async def info():
            return {"manufacturer": "Tyco Security Products", "model": "Illustra Pro4 4k IRPTZ Out"}
        async def caps(dev):
            return dict(pan_tilt=True, zoom=True, presets=False, home=False, home_set=False, camera_timeout_seconds=None)
        async def state(dev):
            return dict(pan=100, tilt=0, zoom=1, position_valid=False, pan_tilt_state="IDLE", zoom_state="IDLE")
        log = []
        async def move(dev, pan, tilt, zoom):
            log.append(("move", pan, tilt, zoom))
        async def stop(dev):
            log.append(("stop",))
        dev.info = info
        monkeypatch.setattr(ptz, "call", broken)
        monkeypatch.setattr(illustra_ptz, "capabilities", caps)
        monkeypatch.setattr(illustra_ptz, "status", state)
        monkeypatch.setattr(illustra_ptz, "move", move)
        monkeypatch.setattr(illustra_ptz, "stop", stop)
        opened = await ptz.open_session(dev, "profile_1")
        sid = opened["session_id"]
        assert opened["capabilities"]["pan_tilt"] and not opened["capabilities"]["presets"]
        assert ptz.sessions[sid].backend == "illustra_iapi"
        await ptz.command(dev, "profile_1", command(sid, pan=.1))
        assert log == [("move", .1, 0, 0), ("stop",)]
        log.clear()
        await ptz.command(dev, "profile_1", command(sid, "stop", 2))
        assert log == [("stop",)]
        async def other_info():
            return {"manufacturer": "Other", "model": "Camera"}
        dev.info = other_info
        with pytest.raises(Fault):
            await ptz.open_session(dev, "profile_1")
    asyncio.run(run())


def test_capabilities_preserve_raw_tyco_position_without_enabling_absolute(camera):
    async def run():
        dev, log, _ = camera
        state = await ptz.open_session(dev, "profile_1")
        PtzState.model_validate(state)
        assert state["status"]["pan"] == 21631 and not state["status"]["position_valid"]
        assert state["capabilities"] == dict(pan_tilt=True, zoom=True, presets=True, home=False, home_set=False, camera_timeout_seconds=10)
        assert "10s" in state["warnings"][1]
        assert state["presets"][0]["token"] == "existing"
        assert all(not name.startswith(("Set", "Goto", "Continuous")) for name, _ in log)
    asyncio.run(run())


@pytest.mark.parametrize("values", [{"pan": float("nan")}, {"zoom": .6}, {"pan": 0}, {"pan": .1, "sequence": 0},
    {"action": "preset_remove", "preset_token": "existing"}, {"action": "home_set"}, {"action": "preset_save", "preset_name": " "}])
def test_invalid_commands_rejected(values):
    with pytest.raises(ValidationError):
        PtzCommand.model_validate({"session_id": "a" * 24, "sequence": 1, "action": "move", **values})


def test_move_has_timeout_axis_only_and_final_stop(camera):
    async def run():
        dev, log, _ = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        result = await ptz.command(dev, "profile_1", command(sid, zoom=.1))
        move = next(text for action, text in log if action == "ContinuousMove")
        assert "PT10S" in move and "Zoom" in move and "PanTilt" not in move
        assert [x[0] for x in log][-2:] == ["Stop", "GetStatus"]
        assert result["status"]["pan_tilt_state"] == "IDLE"
    asyncio.run(run())


@pytest.mark.parametrize("error", [Unreachable("timeout"), Fault("503")])
def test_dispatch_failure_still_sends_stop_and_blocks_further_moves(camera, monkeypatch, error):
    async def run():
        dev, log, original = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        async def call(d, u, req):
            if etree.QName(req).localname == "ContinuousMove":
                raise error
            return await original(d, u, req)
        monkeypatch.setattr(ptz, "call", call)
        with pytest.raises(type(error)):
            await ptz.command(dev, "profile_1", command(sid, pan=.1))
        assert log[-1][0] == "Stop"
        with pytest.raises(HTTPException) as e:
            await ptz.command(dev, "profile_1", command(sid, sequence=2, pan=.1))
        assert e.value.detail["code"] == "ptz_session_expired"
    asyncio.run(run())


def test_stop_fences_late_move_and_stop_remains_available_after_expiry(camera):
    async def run():
        dev, log, _ = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        await ptz.command(dev, "profile_1", command(sid, "stop", 2))
        with pytest.raises(HTTPException):
            await ptz.command(dev, "profile_1", command(sid, pan=.1))
        ptz.sessions[sid].touched = time.monotonic() - 121
        await ptz.command(dev, "profile_1", command(sid, "stop", 3))
        assert not any(a == "ContinuousMove" for a, _ in log)
    asyncio.run(run())


def test_http_cancellation_cannot_cancel_stop(camera, monkeypatch):
    async def run():
        dev, log, original = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        dispatched = asyncio.Event()
        async def call(d, u, req):
            result = await original(d, u, req)
            if etree.QName(req).localname == "ContinuousMove":
                dispatched.set()
                await asyncio.sleep(.02)
            return result
        monkeypatch.setattr(ptz, "call", call)
        task = asyncio.create_task(ptz.command(dev, "profile_1", command(sid, pan=.1)))
        await dispatched.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert any(a == "Stop" for a, _ in log)
    asyncio.run(run())


def test_stop_failure_is_not_reported_as_success(camera, monkeypatch):
    async def run():
        dev, _, original = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        async def call(d, u, req):
            if etree.QName(req).localname == "Stop":
                raise Unreachable("stop timeout")
            return await original(d, u, req)
        monkeypatch.setattr(ptz, "call", call)
        with pytest.raises(Unreachable):
            await ptz.command(dev, "profile_1", command(sid, pan=.1))
        assert ptz.sessions[sid].failed
    asyncio.run(run())


def test_unsupported_home_and_foreign_profile_never_dispatch(camera):
    async def run():
        dev, log, _ = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        with pytest.raises(HTTPException):
            await ptz.command(dev, "profile_2", command(sid, pan=.1))
        with pytest.raises(ptz.NotSupported):
            await ptz.command(dev, "profile_1", command(sid, "home_goto"))
        assert not any(a == "GotoHomePosition" for a, _ in log)
    asyncio.run(run())


def test_no_auth_retry_after_failed_session(camera):
    async def run():
        dev, log, _ = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        ptz.sessions[sid].auth_failed = True
        size = len(log)
        with pytest.raises(NotAuthorized):
            await ptz.command(dev, "profile_1", command(sid, "stop"))
        assert len(log) == size
    asyncio.run(run())


def test_node_http_fault_is_sanitized(monkeypatch):
    async def broken(*args):
        raise Fault("password=secret camera <xml>")
    monkeypatch.setattr(ptz, "open_session", broken)
    app = FastAPI(); app.include_router(ptz_router.router)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://node") as client:
            r = await client.post("/api/v1/onvif/ptz/open", json={"host": "camera", "profile_token": "profile_1", "password": "secret"})
            assert r.status_code == 502 and "secret" not in r.text and "<xml>" not in r.text
    asyncio.run(run())


@pytest.mark.parametrize("minimum, maximum", [("PT11S", "PT1H"), (None, "PT1H"), ("bad", "PT1H"), ("PT10S", "PT5S")])
def test_missing_or_unsafe_timeout_disables_continuous(camera, monkeypatch, minimum, maximum):
    async def run():
        dev, _, original = camera
        async def call(d, u, req):
            reply = await original(d, u, req)
            if etree.QName(req).localname == "GetConfigurationOptions":
                reply.find(".//tt:PTZTimeout/tt:Min", ptz.N).text = minimum
                reply.find(".//tt:PTZTimeout/tt:Max", ptz.N).text = maximum
            return reply
        monkeypatch.setattr(ptz, "call", call)
        state = await ptz.open_session(dev, "profile_1")
        assert not state["capabilities"]["pan_tilt"] and not state["capabilities"]["zoom"]
    asyncio.run(run())


def test_preset_name_is_xml_escaped_and_never_overwrites_existing(camera):
    async def run():
        dev, log, _ = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        await ptz.command(dev, "profile_1", command(sid, "preset_save", preset_name="Gate <&>"))
        saved = next(text for action, text in log if action == "SetPreset")
        assert "Gate &lt;&amp;&gt;" in saved and "PresetToken" not in saved
    asyncio.run(run())


def test_remove_preset_requires_known_token(camera):
    async def run():
        dev, log, _ = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        with pytest.raises(HTTPException) as e:
            await ptz.command(dev, "profile_1", command(sid, "preset_remove", preset_token="missing", confirm=True))
        assert e.value.status_code == 404
        assert not any(a == "RemovePreset" for a, _ in log)
    asyncio.run(run())


@pytest.mark.parametrize("action", ["preset_goto", "preset_remove"])
def test_preset_operations_use_camera_token(camera, action):
    async def run():
        dev, log, _ = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        await ptz.command(dev, "profile_1", command(sid, action, preset_token="existing", confirm=True))
        expected = "GotoPreset" if action == "preset_goto" else "RemovePreset"
        sent = next(text for a, text in log if a == expected)
        assert "existing" in sent and "profile_1" in sent
        if action == "preset_goto":
            assert any(a == "Stop" for a, _ in log)
    asyncio.run(run())


def test_home_only_exposed_when_supported_and_not_fixed(camera, monkeypatch):
    async def run():
        dev, log, original = camera
        async def call(d, u, req):
            reply = await original(d, u, req)
            if etree.QName(req).localname == "GetNodes":
                reply.find(".//p:PTZNode", ptz.N).set("FixedHomePosition", "false")
                reply.find(".//tt:HomeSupported", ptz.N).text = "true"
            return reply
        monkeypatch.setattr(ptz, "call", call)
        state = await ptz.open_session(dev, "profile_1")
        assert state["capabilities"]["home_set"]
        sid = state["session_id"]
        await ptz.command(dev, "profile_1", command(sid, "home_set", confirm=True))
        await ptz.command(dev, "profile_1", command(sid, "home_goto", sequence=2))
        assert any(a == "SetHomePosition" for a, _ in log)
        assert any(a == "GotoHomePosition" for a, _ in log)
        assert any(a == "Stop" for a, _ in log)
    asyncio.run(run())


def test_busy_camera_rejects_other_session_instead_of_queueing_moves(camera, monkeypatch):
    async def run():
        dev, _, original = camera
        first = (await ptz.open_session(dev, "profile_1"))["session_id"]
        second = (await ptz.open_session(dev, "profile_1"))["session_id"]
        dispatched, finish = asyncio.Event(), asyncio.Event()
        async def call(d, u, req):
            if etree.QName(req).localname == "ContinuousMove":
                dispatched.set(); await finish.wait()
            return await original(d, u, req)
        monkeypatch.setattr(ptz, "call", call)
        running = asyncio.create_task(ptz.command(dev, "profile_1", command(first, pan=.1)))
        await dispatched.wait()
        with pytest.raises(HTTPException) as e:
            await ptz.command(dev, "profile_1", command(second, pan=.1))
        assert e.value.detail["code"] == "ptz_busy"
        finish.set(); await running
    asyncio.run(run())


def test_stop_before_dispatch_fences_pending_move(camera):
    async def run():
        dev, log, _ = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        moving = asyncio.create_task(ptz.command(dev, "profile_1", command(sid, pan=.1)))
        await asyncio.sleep(0)  # command registered; its shielded execute task has not run
        stopping = asyncio.create_task(ptz.command(dev, "profile_1", command(sid, "stop", sequence=2)))
        results = await asyncio.gather(moving, stopping, return_exceptions=True)
        assert not isinstance(results[1], Exception)
        assert any(a == "Stop" for a, _ in log)
        # Either already dispatched bounded pulse, or fenced before dispatch; never a move after final Stop.
        actions = [a for a, _ in log]
        if "ContinuousMove" in actions:
            assert actions.index("ContinuousMove") < max(i for i, a in enumerate(actions) if a == "Stop")
    asyncio.run(run())


def test_release_during_preflight_cannot_dispatch_late_move(camera, monkeypatch):
    async def run():
        dev, log, original = camera
        sid = (await ptz.open_session(dev, "profile_1"))["session_id"]
        reading, finish = asyncio.Event(), asyncio.Event()
        async def call(d, u, req):
            if etree.QName(req).localname == "GetStatus":
                reading.set(); await finish.wait()
            return await original(d, u, req)
        monkeypatch.setattr(ptz, "call", call)
        moving = asyncio.create_task(ptz.command(dev, "profile_1", command(sid, pan=.1)))
        await reading.wait()
        stopping = asyncio.create_task(ptz.command(dev, "profile_1", command(sid, "stop", sequence=2)))
        await asyncio.sleep(0)
        finish.set()
        result = await asyncio.gather(moving, stopping, return_exceptions=True)
        assert isinstance(result[0], HTTPException) and result[0].detail["code"] == "ptz_stale_command"
        assert not isinstance(result[1], Exception)
        assert not any(a == "ContinuousMove" for a, _ in log)
        assert not ptz.sessions[sid].failed
    asyncio.run(run())
