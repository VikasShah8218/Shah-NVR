"""ONVIF helpers on central: which cameras already exist for a device, default names/streams, device fields."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException

from app.cameras.models import Camera, CameraStream
from utilities.common import utcnow


def _address(host: str, port: int | None) -> tuple[str, int]:
    return host.lower(), int(port or 80)


async def cameras_by_address() -> tuple[dict[tuple[str, int], Camera], dict[str, Camera]]:
    """(host, ONVIF port) -> camera, and host -> camera for cameras added without ONVIF (from their stream URLs).

    The port matters: one IP can serve several cameras on different ports (a virtual camera server, an encoder, a
    port-mapping box), so a camera on 192.168.1.8:8004 does not make 192.168.1.8:8005 "already added"."""
    by_address: dict[tuple[str, int], Camera] = {}
    by_host: dict[str, Camera] = {}
    cameras = {c.id: c for c in await Camera.all()}
    for c in cameras.values():
        if c.onvif_host:
            by_address.setdefault(_address(c.onvif_host, c.onvif_port), c)
    for s in await CameraStream.all():
        cam = cameras.get(s.camera_id)  # type: ignore[attr-defined]
        host = urlsplit(s.source_url).hostname
        if host and cam and not cam.onvif_host:  # manual camera: only its IP is known
            by_host.setdefault(host.lower(), cam)
    return by_address, by_host


def match_existing(known: tuple[dict[tuple[str, int], Camera], dict[str, Camera]], host: str,
                   port: int | None) -> Camera | None:
    by_address, by_host = known
    return by_address.get(_address(host, port)) or by_host.get(host.lower())


async def find_existing(host: str, port: int | None, serial: str | None = None) -> Camera | None:
    if serial:
        for cam in await Camera.filter(serial=serial):
            # The same serial on the same IP but another port is a different camera of one box (virtual cameras
            # and encoders may repeat the serial); anywhere else it is this camera, maybe at a new address.
            if not (cam.onvif_host and cam.onvif_host.lower() == host.lower()
                    and int(cam.onvif_port or 80) != int(port or 80)):
                return cam
    return match_existing(await cameras_by_address(), host, port)


def default_name(info: dict, host: str) -> str:
    model = (info.get("model") or "").strip()
    maker = (info.get("manufacturer") or "").strip()
    label = model if maker.lower() in model.lower() else f"{maker} {model}".strip()
    return f"{label or 'Camera'} ({host})"[:128]


def pick_streams(probe: dict, picks: list[dict] | None) -> list[dict]:
    """StreamIn-like dicts from the probe. Default: suggested main (recorded) + sub (live only)."""
    by_token = {p["token"]: p for p in probe["profiles"]}
    if picks is None:
        sug = probe["suggested"]
        if not sug.get("main"):
            raise HTTPException(422, {"code": "no_video_profile",
                                      "message": "The camera offers no H.264/H.265 profile with an RTSP address"})
        picks = [{"profile": "main", "token": sug["main"], "record": True}]
        if sug.get("sub"):
            picks.append({"profile": "sub", "token": sug["sub"], "record": False})
    streams = []
    for pick in picks:
        prof = by_token.get(pick["token"])
        if prof is None or not prof.get("rtsp"):
            raise HTTPException(422, {"code": "unknown_profile",
                                      "message": f"Profile '{pick['token']}' not found on the camera (or has no RTSP address)"})
        streams.append({"profile": pick["profile"], "source_url": prof["rtsp"], "record": pick["record"],
                        "onvif_profile_token": prof["token"],
                        "audio_advertised": bool(prof.get("has_audio")),
                        "audio_codec": prof.get("audio_codec"),
                        "audio_codec_raw": prof.get("audio_encoding"),
                        "audio_sample_rate": prof.get("audio_sample_rate"),
                        "audio_channels": prof.get("audio_channels"),
                        "audio_bitrate_kbps": prof.get("audio_bitrate_kbps")})
    return streams


def device_fields(host: str, port: int, info: dict | None = None, services: list[str] | None = None,
                  clock: dict | None = None, network: dict | None = None, has_ptz: bool | None = None) -> dict:
    """Camera columns from a probe / device refresh (only what is known)."""
    out: dict = {"onvif_host": host, "onvif_port": port, "onvif_reachable": True, "onvif_checked_at": utcnow()}
    if info:
        out.update(manufacturer=info.get("manufacturer"), model=info.get("model"),
                   firmware=info.get("firmwareversion"), serial=info.get("serialnumber"))
    if services is not None:
        out["onvif_services"] = services
    if clock is not None:
        out["clock_offset_seconds"] = clock.get("offset_seconds")
    if network and network.get("mac"):
        out["mac"] = network["mac"]
    if has_ptz is not None:  # only when the device refresh could actually determine it (preserves manual override)
        out["has_ptz"] = has_ptz
    return out


EVENT_KINDS = ("motion", "tamper", "digital_input")


def onvif_events_setting(camera: Camera) -> dict | None:
    """What the node needs to subscribe to the camera's events (docs/ONVIF_EVENTS_PLAN.md D3), or None."""
    if not camera.onvif_events_enabled or not camera.onvif_host:
        return None
    return {"kinds": list(camera.onvif_event_kinds or EVENT_KINDS), "store_other": camera.onvif_events_store_other,
            "username": camera.username or "", "password": camera.password or ""}


async def apply_onvif_events_status(node_id: int, reports: list) -> None:
    """Heartbeat: the event subscription state of cameras this node owns (and that still have events on)."""
    if not reports:
        return
    from app.assignments.models import CameraAssignment

    owned = set(await CameraAssignment.filter(node_id=node_id).values_list("camera_id", flat=True))
    for r in reports:
        if r.camera_id in owned:
            await Camera.filter(id=r.camera_id, onvif_events_enabled=True).update(
                onvif_events_status=r.model_dump(mode="json", exclude={"camera_id"}))


def device_target(camera: Camera) -> tuple[str, int]:
    """Where the camera's ONVIF service is: saved address, else the host of its first stream on port 80."""
    if camera.onvif_host:
        return camera.onvif_host, camera.onvif_port or 80
    for s in camera.streams:  # prefetched
        host = urlsplit(s.source_url).hostname
        if host:
            return host, 80
    raise HTTPException(422, {"code": "no_onvif_address", "message": "The camera has no address to reach over ONVIF"})


async def apply_onvif_health(node_id: int, reports: list) -> None:
    """Heartbeat: store reachability + clock offset for cameras this node owns (others are ignored)."""
    if not reports:
        return
    from app.assignments.models import CameraAssignment

    owned = set(await CameraAssignment.filter(node_id=node_id).values_list("camera_id", flat=True))
    for r in reports:
        if r.camera_id in owned:
            fields = {"onvif_reachable": r.reachable, "onvif_checked_at": r.checked_at}
            if r.reachable and r.clock_offset_seconds is not None:
                fields["clock_offset_seconds"] = r.clock_offset_seconds
            await Camera.filter(id=r.camera_id).update(**fields)
