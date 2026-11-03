"""Low-latency PTZ over a persistent WebSocket (direct client -> node).

Why this exists next to ptz.py: the REST path (ptz.command) is a safe *pulse* model
-- every move is a ~0.35 s ContinuousMove that the node force-Stops, re-opening a fresh
SOAP client per request. That is robust for one-shot nudges but feels jerky for hold-to-pan.
This module keeps ONE OnvifDevice (and thus one SOAP connection + the camera clock offset)
alive for the whole control session and issues *true* continuous moves, so holding a button
pans smoothly. A dead-man's switch keeps it safe:

  - every move carries the camera's own ONVIF `Timeout` (>= 1 s), so the camera auto-stops
    if the node ever goes silent;
  - the client re-sends `move` every ~0.4 s while a button is held (keepalive);
  - a node watchdog Stops the camera if no move arrives for WATCHDOG_STOP seconds;
  - the WS closing (release, tab close, network drop) Stops the camera and tears the
    session down, evicting the in-memory credentials immediately.

Credentials: central mints a session (POST /ws/open, creds in the body as for the REST
path) and the node holds the resolved endpoint + the live OnvifDevice (which carries the
creds) in process memory for the life of the WS only -- never on disk, never sent to the
browser. The browser connects with the opaque session id alone.

Auto speed: pan/tilt velocity is derived from the live zoom (wide = fast, tele = slow),
exactly like the ptz_gui prototype, but computed here on the node so the client only ever
sends a direction (-1/0/+1). Zoom itself uses a fixed velocity.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from lxml import etree

from app.onvif import illustra_ptz, ptz
from app.onvif.services import OnvifDevice
from app.onvif.soap import NS, OnvifError

logger = logging.getLogger("node.ptz_ws")

# --- tuning ------------------------------------------------------------------
SPEED_MAX = 0.5        # pan/tilt velocity at wide end (0% zoom); within every advertised space
SPEED_MIN = 0.08       # pan/tilt velocity at full tele (100% zoom)
ZOOM_FIXED = 0.4       # fixed zoom velocity for the zoom in/out buttons
POSE_INTERVAL = 0.4    # seconds between status pushes (pan/tilt/zoom + derived speed)
WATCHDOG_CHECK = 0.3   # how often the watchdog runs
WATCHDOG_STOP = 0.9    # stop the camera if no move keepalive for this long (> client keepalive)
UNCLAIMED_TTL = 60     # a session opened but never connected over WS is reaped after this
MAX_SESSIONS = 256

ws_sessions: dict[str, "WsSession"] = {}

_ERR_STATUS = {"not_authorized": 401, "unreachable": 504, "not_supported": 501, "fault": 502}
_ERR_MESSAGE = {
    "not_authorized": "Camera rejected PTZ authentication; not retried automatically.",
    "unreachable": "Camera PTZ request timed out or is unreachable.",
    "not_supported": "Requested PTZ feature or mapped profile is unsupported.",
    "fault": "Camera PTZ service rejected the request or is unavailable. Reload before retrying.",
}


@dataclass
class WsSession:
    session_id: str
    dev: OnvifDevice
    profile: str
    url: str
    spaces: dict
    caps: dict
    backend: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created: float = field(default_factory=time.monotonic)
    connected: bool = False
    moving: bool = False
    last_move: float = 0.0
    last_zoom: float | None = None
    zoom_lo: float | None = None
    zoom_hi: float | None = None


# --- helpers (pure; unit-tested) --------------------------------------------
def sign(value) -> int:
    """A move message carries only a direction. Collapse any number to -1 / 0 / +1."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    return 1 if v > 1e-3 else (-1 if v < -1e-3 else 0)


def observe_zoom(session: WsSession, zoom) -> None:
    """Track the observed zoom range so auto-speed works without knowing the camera's units."""
    if zoom is None:
        return
    session.last_zoom = zoom
    session.zoom_lo = zoom if session.zoom_lo is None else min(session.zoom_lo, zoom)
    session.zoom_hi = zoom if session.zoom_hi is None else max(session.zoom_hi, zoom)


def zoom_fraction(session: WsSession) -> float | None:
    """0.0 at the observed wide end, 1.0 at the observed tele end; None until a range is seen."""
    z, lo, hi = session.last_zoom, session.zoom_lo, session.zoom_hi
    if z is None or lo is None or hi is None or hi - lo < 1e-9:
        return None
    return min(1.0, max(0.0, (z - lo) / (hi - lo)))


def auto_speed(session: WsSession) -> float:
    """Wide end -> SPEED_MAX, tele end -> SPEED_MIN, linear in between. Full speed until a range is seen."""
    frac = zoom_fraction(session)
    return SPEED_MAX if frac is None else SPEED_MAX - frac * (SPEED_MAX - SPEED_MIN)


def telemetry(session: WsSession) -> dict:
    """Fields the client overlay shows: the applied pan/tilt speed and the zoom position %."""
    frac = zoom_fraction(session)
    return {"speed": round(auto_speed(session), 3), "zoom_pct": None if frac is None else round(frac * 100)}


# --- camera I/O (always under session.lock) ---------------------------------
async def _send(session: WsSession, action: str, **fields):
    return await ptz.call(session.dev, session.url, ptz.request(action, session.profile, **fields))


async def read_status(session: WsSession) -> dict:
    if session.backend == "illustra_iapi":
        return await illustra_ptz.status(session.dev)
    return ptz.parse_status(await _send(session, "GetStatus"))


async def read_presets(session: WsSession) -> list:
    if session.backend == "illustra_iapi" or not session.caps.get("presets"):
        return []
    try:
        return ptz.parse_presets(await _send(session, "GetPresets"))
    except OnvifError:
        return []


async def do_stop(session: WsSession) -> None:
    if session.backend == "illustra_iapi":
        await illustra_ptz.stop(session.dev)
    else:
        await _send(session, "Stop", PanTilt="true", Zoom="true")


async def do_move(session: WsSession, pan: int, tilt: int, zoom: int) -> None:
    """One continuous move. pan/tilt are directions scaled by the zoom-derived speed; zoom is fixed."""
    speed = auto_speed(session)
    pan_tilt = (pan or tilt) and session.caps.get("pan_tilt")
    use_zoom = zoom and session.caps.get("zoom")
    if not pan_tilt and not use_zoom:
        return  # requested axis is unsupported, or a bare zero: ignore (release uses stop)

    if session.backend == "illustra_iapi":
        # No continuous velocity on this firmware's native API: a finite relative step,
        # repeated by the client's keepalive, approximates a hold.
        await illustra_ptz.move(session.dev, (pan * speed) if pan_tilt else 0.0,
                                (tilt * speed) if pan_tilt else 0.0,
                                (zoom * ZOOM_FIXED) if use_zoom else 0.0)
        return

    req = ptz.request("ContinuousMove", session.profile)
    velocity = etree.SubElement(req, etree.QName(ptz.PTZ, "Velocity"))
    if pan_tilt:
        etree.SubElement(velocity, etree.QName(NS["tt"], "PanTilt"),
                         x=f"{pan * speed:.3f}", y=f"{tilt * speed:.3f}", space=session.spaces["pan_tilt"])
    if use_zoom:
        etree.SubElement(velocity, etree.QName(NS["tt"], "Zoom"),
                         x=f"{zoom * ZOOM_FIXED:.3f}", space=session.spaces["zoom"])
    timeout = session.caps.get("camera_timeout_seconds")
    if timeout:
        etree.SubElement(req, etree.QName(ptz.PTZ, "Timeout")).text = f"PT{timeout:g}S"
    await ptz.call(session.dev, session.url, req)


# --- session lifecycle -------------------------------------------------------
async def reap() -> None:
    """Close sessions that were opened by central but never claimed by a WebSocket."""
    now = time.monotonic()
    for sid, s in list(ws_sessions.items()):
        if not s.connected and now - s.created > UNCLAIMED_TTL and not s.lock.locked():
            ws_sessions.pop(sid, None)
            await close_session(s, stop=False)


async def close_session(session: WsSession, *, stop: bool) -> None:
    if stop:
        try:
            async with session.lock:
                if session.moving:
                    await do_stop(session)
                session.moving = False
        except Exception:
            pass
    try:
        await session.dev.__aexit__(None, None, None)
    except Exception:
        pass


async def open_ws_session(host: str, port: int, username: str, password: str, profile: str) -> dict:
    """Resolve the camera's PTZ endpoint and hold a live session. Returns the PtzState shape.

    Reuses ptz.open_session for the (vetted) discovery, then migrates that transient REST
    session into a WsSession that owns the still-open OnvifDevice.
    """
    await reap()
    if len(ws_sessions) >= MAX_SESSIONS:
        raise HTTPException(429, {"code": "ptz_busy", "message": "Too many PTZ sessions. Close controls and retry."})
    dev = OnvifDevice(host, port, username, password, timeout=5.0)
    try:
        state = await ptz.open_session(dev, profile)
    except OnvifError as exc:
        await close_session_dev(dev)
        code = exc.code
        raise HTTPException(_ERR_STATUS[code], {"code": code, "message": _ERR_MESSAGE[code]}) from None
    except Exception:
        await close_session_dev(dev)
        raise
    rest = ptz.sessions.pop(state["session_id"], None)  # take discovery out of the REST registry
    if rest is None:  # pragma: no cover - open_session always registers one
        await close_session_dev(dev)
        raise HTTPException(500, {"code": "ptz_open_failed", "message": "PTZ session could not be established."})
    sid = secrets.token_urlsafe(24)
    ws_sessions[sid] = WsSession(sid, dev, profile, rest.url, rest.spaces, rest.caps, rest.backend)
    return {**state, "session_id": sid}


async def close_session_dev(dev: OnvifDevice) -> None:
    try:
        await dev.__aexit__(None, None, None)
    except Exception:
        pass


# --- WebSocket handler -------------------------------------------------------
async def serve(websocket: WebSocket) -> None:
    sid = websocket.query_params.get("session", "")
    await websocket.accept()
    session = ws_sessions.get(sid)
    if session is None:
        await websocket.send_json({"t": "error", "code": "ptz_session_expired",
                                   "message": "PTZ session expired. Reopen the controls."})
        await websocket.close()
        return
    if session.connected:
        await websocket.send_json({"t": "error", "code": "ptz_busy",
                                   "message": "This camera's PTZ is already being controlled."})
        await websocket.close()
        return
    session.connected = True
    pose_task = asyncio.create_task(_pose_loop(websocket, session))
    watchdog_task = asyncio.create_task(_watchdog_loop(session))
    try:
        async with session.lock:
            status = await read_status(session)
        observe_zoom(session, status.get("zoom"))
        await websocket.send_json({"t": "ready", "session_id": sid, "capabilities": session.caps,
                                   "status": status, "presets": await read_presets(session),
                                   **telemetry(session)})
        while True:
            await _handle(websocket, session, await websocket.receive_json())
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # malformed frame, camera gone mid-session, etc.
        logger.info("PTZ WS session ended: %s", exc)
    finally:
        pose_task.cancel()
        watchdog_task.cancel()
        await asyncio.gather(pose_task, watchdog_task, return_exceptions=True)
        ws_sessions.pop(sid, None)
        await close_session(session, stop=True)


async def _handle(websocket: WebSocket, session: WsSession, msg) -> None:
    if not isinstance(msg, dict):
        return
    action = msg.get("t")
    try:
        if action == "move":
            pan, tilt, zoom = sign(msg.get("pan")), sign(msg.get("tilt")), sign(msg.get("zoom"))
            if not (pan or tilt or zoom):
                return
            async with session.lock:
                await do_move(session, pan, tilt, zoom)
                session.moving = True
                session.last_move = time.monotonic()
        elif action == "stop":
            async with session.lock:
                if session.moving:
                    await do_stop(session)
                session.moving = False
            await websocket.send_json({"t": "stopped"})
        elif action == "refresh":
            async with session.lock:
                status = await read_status(session)
                presets = await read_presets(session)
            observe_zoom(session, status.get("zoom"))
            await websocket.send_json({"t": "status", "status": status, "presets": presets, **telemetry(session)})
        # unknown actions are ignored (forward-compatible: focus/presets land here later)
    except OnvifError as exc:
        session.moving = False
        await websocket.send_json({"t": "error", "code": exc.code, "message": _ERR_MESSAGE.get(exc.code, str(exc))})


async def _pose_loop(websocket: WebSocket, session: WsSession) -> None:
    try:
        while True:
            await asyncio.sleep(POSE_INTERVAL)
            try:
                async with session.lock:
                    status = await read_status(session)
            except OnvifError:
                continue
            observe_zoom(session, status.get("zoom"))
            try:
                await websocket.send_json({"t": "pose", "status": status, "moving": session.moving, **telemetry(session)})
            except Exception:
                return  # socket gone; serve()'s finally handles teardown
    except asyncio.CancelledError:
        pass


async def _watchdog_loop(session: WsSession) -> None:
    """Dead-man's switch: stop the camera if the client stops sending move keepalives."""
    try:
        while True:
            await asyncio.sleep(WATCHDOG_CHECK)
            if session.moving and time.monotonic() - session.last_move > WATCHDOG_STOP:
                try:
                    async with session.lock:
                        if session.moving:
                            await do_stop(session)
                        session.moving = False
                except Exception:
                    session.moving = False
    except asyncio.CancelledError:
        pass
