"""Capability-gated PTZ with bounded pulses, ordering fences and explicit Stop.

No credentials are cached. Sessions pin the discovered endpoint/profile/clock for
120 seconds of inactivity. One process per node is required (as for MediaMTX).
"""
import asyncio
import math
import re
import time
import secrets
from dataclasses import dataclass, field

from fastapi import HTTPException
from lxml import etree

from app.onvif.soap import NS, Fault, NotSupported, NotAuthorized, OnvifError
from app.onvif import illustra_ptz

PTZ = "http://www.onvif.org/ver20/ptz/wsdl"
N = {**NS, "p": PTZ}
TTL = 120
PULSE_SECONDS = .35
sessions = {}
actors = {}


def fail(code, message, status=409):
    raise HTTPException(status, {"code": code, "message": message})


@dataclass
class Actor:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    epoch: int = 0


@dataclass
class Session:
    key: tuple
    url: str
    profile: str
    offset: float
    digest: bool
    caps: dict
    spaces: dict
    backend: str = "onvif"
    touched: float = field(default_factory=time.monotonic)
    sequence: int = 0
    failed: bool = False
    auth_failed: bool = False


def key(dev, profile):
    return (dev.host.lower().rstrip('.'), dev.port, dev.soap.username, profile)


def request(action, profile=None, **fields):
    root = etree.Element(etree.QName(PTZ, action), nsmap={"tptz": PTZ, "tt": NS["tt"]})
    if profile is not None:
        fields = {"ProfileToken": profile, **fields}
    for name, value in fields.items():
        etree.SubElement(root, etree.QName(PTZ, name)).text = str(value)
    return root


async def call(dev, url, req):
    return await dev.soap.call(url, etree.tostring(req, encoding="unicode"))


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def duration(value):
    match = re.fullmatch(r"PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?", value or "")
    if not match or not any(match.groups()):
        return None
    return sum(float(v or 0) * scale for v, scale in zip(match.groups(), (3600, 60, 1)))


def parse_status(reply):
    pt = reply.find(".//tt:Position/tt:PanTilt", N)
    z = reply.find(".//tt:Position/tt:Zoom", N)
    x, y = (number(pt.get(a)) if pt is not None else None for a in ("x", "y"))
    zoom = number(z.get("x")) if z is not None else None
    # Tyco reports raw motor units under generic-space URIs. Preserve for display,
    # never clamp/convert or feed these values to AbsoluteMove.
    valid = (x is not None and y is not None and zoom is not None and
             -1 <= x <= 1 and -1 <= y <= 1 and 0 <= zoom <= 1)
    return {"pan": x, "tilt": y, "zoom": zoom, "position_valid": valid,
            "pan_tilt_state": reply.findtext(".//tt:MoveStatus/tt:PanTilt", namespaces=N),
            "zoom_state": reply.findtext(".//tt:MoveStatus/tt:Zoom", namespaces=N)}


def parse_presets(reply):
    return [{"token": p.get("token"), "name": p.findtext("tt:Name", namespaces=N) or p.get("token")}
            for p in reply.findall(".//p:Preset", N) if p.get("token")]


def velocity_space(options, tag):
    suffix = "PanTiltSpaces/VelocityGenericSpace" if "PanTilt" in tag else "ZoomSpaces/VelocityGenericSpace"
    for e in options.findall(f".//tt:{tag}", N):
        uri = e.findtext("tt:URI", namespaces=N) or ""
        axes = ("X", "Y") if "PanTilt" in tag else ("X",)
        limits = [(number(e.findtext(f"tt:{a}Range/tt:{b}", namespaces=N))) for a in axes for b in ("Min", "Max")]
        if uri == "http://www.onvif.org/ver10/tptz/" + suffix and all(v is not None for v in limits):
            if all(limits[i] <= -.5 and limits[i+1] >= .5 for i in range(0, len(limits), 2)):
                return uri
    return None


async def open_session(dev, profile):
    await dev.clock()
    services = await dev.services()
    url = services.get(PTZ)
    if not url:
        raise NotSupported("Camera does not advertise an ONVIF PTZ service")
    # Resolve the PTZ configuration from THIS mapped media profile, not the first
    # device configuration. Media2-only devices are supported as well.
    config = None
    for ns, path, config_path in (("trt", ".//trt:Profiles", "tt:PTZConfiguration"),
                                   ("tr2", ".//tr2:Profiles", "tr2:Configurations/tr2:PTZ")):
        if NS[ns] not in services:
            continue
        body = f'<{ns}:GetProfiles/>' if ns == "trt" else '<tr2:GetProfiles><tr2:Type>All</tr2:Type></tr2:GetProfiles>'
        try:
            reply = await dev.soap.call(services[NS[ns]], body)
        except (Fault, NotSupported):
            continue
        matched = next((p for p in reply.findall(path, N) if p.get("token") == profile), None)
        if matched is not None:
            config = matched.find(config_path, N)
            if config is not None:
                break
    if config is None or not config.get("token"):
        raise NotSupported("Mapped ONVIF profile has no PTZ configuration; check stream mapping in Video")
    token = config.get("token")
    try:
        configs = await call(dev, url, request("GetConfigurations"))
    except Fault as exc:
        # This Pro4 firmware advertises ONVIF PTZ but its PTZ endpoint returns
        # HTTP 503 while its own iAPI remains healthy. Never route an arbitrary
        # camera or a SOAP/auth fault to a vendor-specific control protocol.
        if not str(exc).startswith("HTTP 503") or not illustra_ptz.supported_device(await dev.info()):
            raise
        caps = await illustra_ptz.capabilities(dev)
        status = await illustra_ptz.status(dev)
        if not (caps["pan_tilt"] or caps["zoom"]):
            raise NotSupported("Illustra iAPI does not advertise relative PTZ movement")
        sid = create_session(dev, profile, url, caps, {}, "illustra_iapi")
        return {"session_id": sid, "capabilities": caps, "status": status, "presets": [],
                "warnings": ["Camera ONVIF PTZ returned HTTP 503. Using Illustra's native PTZ API with finite relative steps; presets and home are unavailable."]}
    conf = next((c for c in configs.findall(".//p:PTZConfiguration", N) if c.get("token") == token), None)
    if conf is None:
        raise NotSupported("Mapped PTZ configuration is unavailable")
    node_token = conf.findtext("tt:NodeToken", namespaces=N)
    nodes = await call(dev, url, request("GetNodes"))
    node = next((n for n in nodes.findall(".//p:PTZNode", N) if n.get("token") == node_token), None)
    if node is None:
        raise NotSupported("Mapped PTZ node is unavailable")
    options = await call(dev, url, request("GetConfigurationOptions", ConfigurationToken=token))
    spaces = {"pan_tilt": velocity_space(options, "ContinuousPanTiltVelocitySpace"),
              "zoom": velocity_space(options, "ContinuousZoomVelocitySpace")}
    lo = duration(options.findtext(".//tt:PTZTimeout/tt:Min", namespaces=N))
    hi = duration(options.findtext(".//tt:PTZTimeout/tt:Max", namespaces=N))
    timeout = max(1., lo) if lo is not None else None
    safe_timeout = timeout is not None and hi is not None and 0 <= lo <= timeout <= min(hi, 10)
    caps = {"pan_tilt": bool(spaces["pan_tilt"]) and safe_timeout,
            "zoom": bool(spaces["zoom"]) and safe_timeout,
            "presets": (number(node.findtext("tt:MaximumNumberOfPresets", namespaces=N)) or 0) > 0,
            "home": node.findtext("tt:HomeSupported", namespaces=N) in ("true", "1"),
            "camera_timeout_seconds": timeout if safe_timeout else None}
    caps["home_set"] = caps["home"] and node.get("FixedHomePosition") in ("false", "0")
    status = parse_status(await call(dev, url, request("GetStatus", profile)))
    warnings = []
    if not status["position_valid"]:
        warnings.append("Camera position is missing or outside normalized ranges. Absolute positioning is disabled; raw values are not converted.")
    if not safe_timeout:
        warnings.append("No supported camera timeout of 10 seconds or less. Continuous controls are disabled.")
    elif timeout > 1:
        warnings.append(f"Camera minimum timeout is {timeout:g}s. Node stops each pulse after {PULSE_SECONDS:g}s; a node/network failure may allow motion until the camera timeout.")
    presets = []
    if caps["presets"]:
        presets = parse_presets(await call(dev, url, request("GetPresets", profile)))
    sid = create_session(dev, profile, url, caps, spaces)
    return {"session_id": sid, "capabilities": caps, "status": status, "presets": presets, "warnings": warnings}


def create_session(dev, profile, url, caps, spaces, backend="onvif"):
    now = time.monotonic()
    for sid, old in list(sessions.items()):
        actor = actors[old.key[:2]]
        if now - old.touched > TTL and not actor.lock.locked():
            del sessions[sid]
    used = {s.key[:2] for s in sessions.values()}
    for actor_key in list(actors):
        if actor_key not in used and not actors[actor_key].lock.locked():
            del actors[actor_key]
    if len(sessions) >= 256:
        fail("ptz_busy", "Too many PTZ sessions. Close controls and retry later.", 429)
    sid = secrets.token_urlsafe(24)
    k = key(dev, profile)
    actors.setdefault(k[:2], Actor())
    sessions[sid] = Session(k, url, profile, dev.soap.offset, dev.soap.http_digest, caps, spaces, backend)
    return sid


async def command(dev, profile, cmd):
    session = sessions.get(cmd.session_id)
    if session is None or session.key != key(dev, profile):
        fail("ptz_session_expired", "Reload PTZ controls before issuing commands.")
    if session.auth_failed:
        raise NotAuthorized("PTZ session authentication previously failed; no retry sent")
    if cmd.action != "stop" and (time.monotonic() - session.touched > TTL or session.failed):
        fail("ptz_session_expired", "PTZ session expired or failed. Reload before another command.")
    if cmd.sequence <= session.sequence:
        fail("ptz_stale_command", "Out-of-order PTZ command rejected.")
    session.sequence = cmd.sequence
    session.touched = time.monotonic()
    actor = actors[session.key[:2]]
    if cmd.action == "stop":
        actor.epoch += 1  # fence commands that have not reached the camera yet
    elif actor.lock.locked():
        fail("ptz_busy", "Another PTZ command is in progress.")
    epoch = actor.epoch
    dev.soap.offset, dev.soap.http_digest = session.offset, session.digest

    async def send(action, **fields):
        return await call(dev, session.url, request(action, profile, **fields))

    async def stop():
        await send("Stop", PanTilt="true", Zoom="true")

    async def execute():
        async with actor.lock:
            if cmd.action != "stop" and (epoch != actor.epoch or cmd.sequence != session.sequence):
                fail("ptz_stale_command", "Command superseded by Stop.")
            if session.backend == "illustra_iapi":
                if cmd.action == "stop":
                    await illustra_ptz.stop(dev)
                    return {"message": "Stop acknowledged by camera."}
                if cmd.action == "refresh":
                    return {"message": "PTZ refreshed.", "status": await illustra_ptz.status(dev), "presets": []}
                if cmd.action != "move":
                    raise NotSupported("This camera's native PTZ fallback supports movement only")
                if ((cmd.pan or cmd.tilt) and not session.caps["pan_tilt"]) or (cmd.zoom and not session.caps["zoom"]):
                    raise NotSupported("Requested PTZ axis is unavailable")
                initial = await illustra_ptz.status(dev)
                if initial["pan_tilt_state"] != "IDLE" or initial["zoom_state"] != "IDLE":
                    fail("ptz_not_idle", "Camera must report IDLE before a new movement. Stop and refresh.")
                if epoch != actor.epoch or cmd.sequence != session.sequence:
                    fail("ptz_stale_command", "Command superseded by Stop.")
                try:
                    await illustra_ptz.move(dev, cmd.pan, cmd.tilt, cmd.zoom)
                    await asyncio.sleep(PULSE_SECONDS)
                finally:
                    await illustra_ptz.stop(dev)
                state = await illustra_ptz.status(dev)
                if state["pan_tilt_state"] != "IDLE" or state["zoom_state"] != "IDLE":
                    fail("ptz_stop_unconfirmed", "Stop sent, but camera did not confirm IDLE. Check the camera before further control.", 502)
                return {"message": "Finite step acknowledged; camera IDLE.", "status": state}
            if cmd.action == "stop":
                await stop()
                return {"message": "Stop acknowledged by camera."}
            if cmd.action == "refresh":
                return {"message": "PTZ refreshed.", "status": parse_status(await send("GetStatus")),
                        "presets": parse_presets(await send("GetPresets")) if session.caps["presets"] else []}
            if cmd.action.startswith("preset_") and not session.caps["presets"]:
                raise NotSupported("Camera does not advertise presets")
            if cmd.action.startswith("home_") and not session.caps["home_set" if cmd.action == "home_set" else "home"]:
                raise NotSupported("Camera does not advertise this home operation")
            if cmd.action in ("preset_goto", "preset_remove"):
                presets = parse_presets(await send("GetPresets"))
                if not any(p["token"] == cmd.preset_token for p in presets):
                    fail("ptz_preset_missing", "Preset no longer exists. Refresh the list.", 404)
            if cmd.action in ("preset_save", "home_set"):
                state = parse_status(await send("GetStatus"))
                if state["pan_tilt_state"] != "IDLE" or state["zoom_state"] != "IDLE":
                    fail("ptz_not_idle", "Camera must report IDLE before saving a position.")
                await send("SetPreset", PresetName=cmd.preset_name.strip()) if cmd.action == "preset_save" else await send("SetHomePosition")
            elif cmd.action == "preset_remove":
                await send("RemovePreset", PresetToken=cmd.preset_token)
            else:
                if cmd.action == "move":
                    if ((cmd.pan or cmd.tilt) and not session.caps["pan_tilt"]) or (cmd.zoom and not session.caps["zoom"]):
                        raise NotSupported("Requested PTZ axis or safe timeout is unavailable")
                    initial = parse_status(await send("GetStatus"))
                    if initial["pan_tilt_state"] != "IDLE" or initial["zoom_state"] != "IDLE":
                        fail("ptz_not_idle", "Camera must report IDLE before a new movement. Stop and refresh.")
                    req = request("ContinuousMove", profile)
                    velocity = etree.SubElement(req, etree.QName(PTZ, "Velocity"))
                    if cmd.pan or cmd.tilt:
                        etree.SubElement(velocity, etree.QName(NS["tt"], "PanTilt"), x=str(cmd.pan), y=str(cmd.tilt), space=session.spaces["pan_tilt"])
                    if cmd.zoom:
                        etree.SubElement(velocity, etree.QName(NS["tt"], "Zoom"), x=str(cmd.zoom), space=session.spaces["zoom"])
                    etree.SubElement(req, etree.QName(PTZ, "Timeout")).text = f'PT{session.caps["camera_timeout_seconds"]:g}S'
                else:
                    req = request("GotoPreset", profile, PresetToken=cmd.preset_token) if cmd.action == "preset_goto" else request("GotoHomePosition", profile)
                # Stop even when dispatch times out: the camera may have acted.
                # Cancellation of the HTTP caller must not cancel cleanup.
                try:
                    # Stop may arrive while the preflight status/preset read is
                    # awaiting I/O. Recheck immediately before dispatching motion.
                    if epoch != actor.epoch or cmd.sequence != session.sequence:
                        fail("ptz_stale_command", "Command superseded by Stop.")
                    await call(dev, session.url, req)
                    if cmd.action == "move":
                        await asyncio.sleep(PULSE_SECONDS)
                    else:
                        deadline = time.monotonic() + 4
                        for _ in range(20):
                            await asyncio.sleep(.2)
                            state = parse_status(await send("GetStatus"))
                            if state["pan_tilt_state"] == state["zoom_state"] == "IDLE" or time.monotonic() >= deadline:
                                break
                finally:
                    await stop()
                for _ in range(4):
                    state = parse_status(await send("GetStatus"))
                    if state["pan_tilt_state"] == state["zoom_state"] == "IDLE":
                        break
                    await asyncio.sleep(.1)
                else:
                    fail("ptz_stop_unconfirmed", "Stop sent, but camera did not confirm IDLE. Check the camera before further control.", 502)
                return {"message": "Stop acknowledged and camera IDLE. Preset/home travel is time-limited; check the resulting view.", "status": state}
            return {"message": "Camera operation acknowledged.",
                    "presets": parse_presets(await send("GetPresets")) if session.caps["presets"] else []}

    async def guarded():
        try:
            return await execute()
        except OnvifError:
            session.failed = True  # no automatic auth/motion retry on subsequent pulses
            session.auth_failed = dev.soap.auth_failed is not None
            raise
        except HTTPException as exc:
            if exc.detail.get("code") not in ("ptz_stale_command", "ptz_busy", "ptz_preset_missing"):
                session.failed = True
            raise

    task = asyncio.create_task(guarded())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task  # keep device HTTP client alive until Stop completes
        raise
