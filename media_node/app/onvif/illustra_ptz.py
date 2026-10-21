"""Illustra iAPI PTZ fallback for cameras whose advertised ONVIF PTZ is down.

The camera's own web UI uses this documented CGI. RelativeMove is deliberately
used for pulses: it is finite even if the node dies before its final Stop.
"""
import math

import httpx

from app.onvif.soap import Fault, NotAuthorized, NotSupported, Unreachable

PATH = "/iAPI/ptzfi.cgi"


def supported_device(info: dict) -> bool:
    return (info.get("manufacturer") or "").lower() == "tyco security products" and \
        (info.get("model") or "").lower().startswith("illustra pro4")


async def get(dev, action: str, **params) -> str:
    if dev.soap.auth_failed:
        raise dev.soap.auth_failed
    url = f"http://{dev.host}:{dev.port}{PATH}"
    try:
        response = await dev._http.get(
            url, params={"action": action, **params},
            auth=httpx.BasicAuth(dev.soap.username, dev.soap.password),
        )
    except httpx.TimeoutException:
        raise Unreachable("Illustra PTZ request timed out") from None
    except httpx.HTTPError:
        raise Unreachable("Illustra PTZ is unreachable") from None
    if response.status_code in (401, 403):
        dev.soap.auth_failed = NotAuthorized("Illustra PTZ authentication failed")
        raise dev.soap.auth_failed
    if response.status_code >= 400:
        raise Fault(f"Illustra PTZ HTTP {response.status_code}")
    result = response.text.strip()
    if result.upper().startswith(("ERROR", "FAIL")):
        raise Fault("Illustra PTZ rejected request")
    return result


def parse_status(body: str) -> dict:
    fields = dict(line.split("=", 1) for line in body.splitlines() if "=" in line)
    def value(name):
        try:
            n = float(fields[name])
            return n if math.isfinite(n) else None
        except (KeyError, ValueError):
            return None
    pan, tilt, zoom = (value(k) for k in ("pan", "tilt", "zoom"))
    speeds = tuple(value(k) for k in ("pansp", "tiltsp", "zoomsp"))
    if pan is None or tilt is None or zoom is None or any(v is None for v in speeds):
        raise Fault("Illustra PTZ status is incomplete")
    return {"pan": pan, "tilt": tilt, "zoom": zoom, "position_valid": False,
            "pan_tilt_state": "IDLE" if speeds[:2] == (0, 0) else "MOVING",
            "zoom_state": "IDLE" if speeds[2] == 0 else "MOVING"}


async def status(dev) -> dict:
    return parse_status(await get(dev, "Status"))


async def capabilities(dev) -> dict:
    explain = await get(dev, "Explain")
    commands = next((line.split("=", 1)[1] for line in explain.splitlines()
                     if line.startswith("RelativeMove=")), "")
    axes = set(commands.split(","))
    return {"pan_tilt": {"pan", "tilt"} <= axes, "zoom": "zoom" in axes,
            "presets": False, "home": False, "home_set": False,
            "camera_timeout_seconds": None}


async def stop(dev) -> None:
    result = await get(dev, "ContinuousMove", pansp=0, tiltsp=0, zoomsp=0)
    if result != "OK":
        raise Fault("Illustra PTZ Stop was not acknowledged")


async def move(dev, pan: float, tilt: float, zoom: float) -> None:
    # One request is a small, finite relative step, not open-ended velocity.
    # Positive pan/tilt and zoom directions match the camera's own web UI.
    params = {"units": "degrees"}
    if pan:
        params["pan"] = f"{pan * 2:.2f}"
    if tilt:
        params["tilt"] = f"{tilt * 2:.2f}"
    if zoom:
        params["zoom"] = f"{zoom * .5:.3f}"
    if len(params) == 1:
        raise NotSupported("No PTZ axis requested")
    result = await get(dev, "RelativeMove", **params)
    if result != "OK":
        raise Fault("Illustra PTZ movement was not acknowledged")
