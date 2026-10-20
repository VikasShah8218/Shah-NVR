"""ONVIF helpers on central: which cameras already exist for a device, default names/streams, device fields."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import HTTPException

from app.cameras.models import Camera, CameraStream
from utilities.common import utcnow


async def cameras_by_host() -> dict[str, Camera]:
    """host -> camera, from the ONVIF address and from every stream URL (manually added cameras count too)."""
    out: dict[str, Camera] = {}
    cameras = {c.id: c for c in await Camera.all()}
    for c in cameras.values():
        if c.onvif_host:
            out.setdefault(c.onvif_host.lower(), c)
    for s in await CameraStream.all():
        host = urlsplit(s.source_url).hostname
        if host and s.camera_id in cameras:  # type: ignore[attr-defined]
            out.setdefault(host.lower(), cameras[s.camera_id])  # type: ignore[attr-defined]
    return out


async def find_existing(host: str, serial: str | None = None) -> Camera | None:
    if serial:
        cam = await Camera.filter(serial=serial).first()
        if cam:
            return cam
    return (await cameras_by_host()).get(host.lower())


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
                  clock: dict | None = None, network: dict | None = None) -> dict:
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
    return out


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
