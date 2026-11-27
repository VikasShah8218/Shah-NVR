"""ONVIF (H1): discover cameras, probe them, add them without typing RTSP URLs, and manage the device.

Every call goes central -> media node (`app/nodes/client.py`) -> camera, because the node sits on the cameras' LAN.
Errors carry {"code", "message"}: not_authorized (wrong login, never retried: cameras lock accounts),
unreachable, not_supported, fault, node_offline / node_unreachable / node_timeout, no_node_online.
"""

import asyncio

from fastapi import APIRouter, HTTPException, Response, status

from app.cameras.models import Camera
from app.cameras.schemas import CameraOut
from app.cameras.services import create_camera_with_streams
from app.groups.services import check_group_id
from app.cameras.utils import camera_to_out
from app.nodes.client import call_node, online_nodes, pick_node
from app.auth import scope as access
from app.groups.services import camera_scope
from app.onvif.schemas import (ClockOut, DeviceIn, DeviceStateOut, DiscoveredOut, DiscoverIn, EventProbeOut,
                               EventsApplyIn, EventsApplyOut, MessageOut, NtpIn, OnvifCameraCreate, ProbeOut,
                               SnapshotIn)
from tortoise.expressions import Q
from app.onvif.services import (cameras_by_address, default_name, device_fields, device_target, find_existing,
                                match_existing, pick_streams)
from settings.settings import settings
from utilities.common import utcnow

router = APIRouter(prefix="/api/v1/onvif", tags=["ONVIF"])

DISCOVER_EXTRA_SECONDS = 10
PROBE_TIMEOUT = 45.0


def _device_body(body: DeviceIn) -> dict:
    return body.model_dump(include={"host", "port", "xaddr", "username", "password"})


@router.post("/discover", response_model=list[DiscoveredOut], summary="Find ONVIF cameras on the nodes' LANs")
async def discover(body: DiscoverIn):
    nodes = [await pick_node(body.node_id)] if body.node_id is not None else await online_nodes()
    if not nodes:
        raise HTTPException(409, {"code": "no_node_online", "message": "No media node is online"})
    results = await asyncio.gather(
        *(call_node(n, "/api/v1/onvif/discover", {"seconds": body.seconds}, timeout=body.seconds + DISCOVER_EXTRA_SECONDS)
          for n in nodes), return_exceptions=True)
    if all(isinstance(r, Exception) for r in results):
        raise results[0]  # type: ignore[misc]
    existing = await cameras_by_address()
    seen: dict[str, dict] = {}
    for node, found in zip(nodes, results):
        if isinstance(found, Exception):
            continue  # another node answered; a single offline node does not fail the scan
        for d in found:
            if d["endpoint"] in seen:
                continue
            cam = match_existing(existing, d["host"], d.get("port"))
            seen[d["endpoint"]] = {**d, "node_id": node.id, "node_name": node.name,
                                   "camera_id": cam.id if cam else None, "camera_name": cam.name if cam else None}
    return list(seen.values())


@router.post("/probe", response_model=ProbeOut, summary="Identity, clock and stream profiles of one device")
async def probe(body: DeviceIn):
    node = await pick_node(body.node_id)
    result = await call_node(node, "/api/v1/onvif/probe", _device_body(body), timeout=PROBE_TIMEOUT)
    cam = await find_existing(body.host, body.port, (result.get("info") or {}).get("serialnumber"))
    return {**result, "node_id": node.id, "camera_id": cam.id if cam else None}


@router.post("/snapshot", summary="Preview JPEG of a profile (through the node)", response_class=Response,
             responses={200: {"content": {"image/jpeg": {}}}})
async def snapshot(body: SnapshotIn):
    node = await pick_node(body.node_id)
    r = await call_node(node, "/api/v1/onvif/snapshot", {**_device_body(body), "uri": body.uri}, raw=True)
    return Response(r.content, media_type=r.headers.get("content-type", "image/jpeg"),
                    headers={"Cache-Control": "no-store"})


@router.post("/cameras", response_model=CameraOut, status_code=status.HTTP_201_CREATED,
             summary="Add a camera from ONVIF: streams filled from its profiles (main recorded, sub live)")
async def add_camera(body: OnvifCameraCreate):
    await check_group_id(body.group_id)
    node = await pick_node(body.node_id)
    result = await call_node(node, "/api/v1/onvif/probe", _device_body(body), timeout=PROBE_TIMEOUT)
    info = result.get("info") or {}
    if not body.allow_duplicate:
        cam = await find_existing(body.host, body.port, info.get("serialnumber"))
        if cam:
            raise HTTPException(409, {"code": "already_added", "message": f"Already added as '{cam.name}'",
                                      "camera_id": cam.id})
    streams = pick_streams(result, [s.model_dump() for s in body.streams] if body.streams is not None else None)
    # Auto-detect PTZ: a profile that carries a PTZConfiguration (node sets has_ptz per profile during probe).
    has_ptz = any((p or {}).get("has_ptz") for p in (result.get("profiles") or []))
    camera = await create_camera_with_streams(
        {
            "name": body.name or default_name(info, body.host),
            "description": body.description,
            "username": body.username or None,
            "password": body.password or None,
            "enabled": body.enabled,
            "has_ptz": has_ptz,
            "group_id": body.group_id,
            "retention_days": body.retention_days if "retention_days" in body.model_fields_set
            else settings.DEFAULT_RETENTION_DAYS,
            **device_fields(body.host, body.port, info, result.get("services"), result.get("clock")),
        },
        streams,
    )
    return await camera_to_out(camera)


# ------------------------------------------------------------------ one camera's device
async def _camera(camera_id: int) -> Camera:
    camera = await Camera.get_or_none(id=camera_id).prefetch_related("streams")
    if camera is None:
        raise HTTPException(404, "Camera not found")
    return camera


async def _camera_call(camera: Camera, path: str, extra: dict | None = None, timeout: float = PROBE_TIMEOUT):
    host, port = device_target(camera)
    node = await pick_node(camera_id=camera.id)
    body = {"host": host, "port": port, "username": camera.username or "", "password": camera.password or "",
            **(extra or {})}
    try:
        return node, await call_node(node, path, body, timeout=timeout)
    except HTTPException as exc:
        code = exc.detail.get("code") if isinstance(exc.detail, dict) else None
        if code == "unreachable":
            await Camera.filter(id=camera.id).update(onvif_reachable=False, onvif_checked_at=utcnow())
        raise


@router.get("/cameras/{camera_id}/device", response_model=DeviceStateOut,
            summary="Live device info, clock and settings (also refreshes the saved device fields)")
async def camera_device(camera_id: int):
    camera = await _camera(camera_id)
    node, state = await _camera_call(camera, "/api/v1/onvif/device")
    host, port = device_target(camera)
    fields = device_fields(host, port, state.get("info"), state.get("services"), state.get("clock"),
                           state.get("network"), state.get("has_ptz"))
    await Camera.filter(id=camera.id).update(**fields)
    return {**state, "camera_id": camera.id, "node_id": node.id, "host": host, "port": port,
            "checked_at": fields["onvif_checked_at"]}


@router.post("/cameras/{camera_id}/time-sync", response_model=ClockOut, summary="Set the camera clock to the node's time")
async def camera_time_sync(camera_id: int):
    camera = await _camera(camera_id)
    _, clock = await _camera_call(camera, "/api/v1/onvif/device/time-sync")
    await Camera.filter(id=camera.id).update(clock_offset_seconds=clock.get("offset_seconds"), onvif_checked_at=utcnow())
    return clock


@router.post("/cameras/{camera_id}/ntp", summary="Point the camera at NTP servers (or the ones DHCP gives)")
async def camera_ntp(camera_id: int, body: NtpIn):
    if not body.from_dhcp and not body.servers:
        raise HTTPException(422, {"code": "invalid", "message": "Give NTP servers or choose DHCP"})
    camera = await _camera(camera_id)
    _, result = await _camera_call(camera, "/api/v1/onvif/device/ntp", body.model_dump())
    await Camera.filter(id=camera.id).update(clock_offset_seconds=result["clock"].get("offset_seconds"),
                                             onvif_checked_at=utcnow())
    return result


@router.post("/cameras/{camera_id}/reboot", response_model=MessageOut, summary="Reboot the camera")
async def camera_reboot(camera_id: int):
    camera = await _camera(camera_id)
    _, result = await _camera_call(camera, "/api/v1/onvif/device/reboot")
    return result


# ------------------------------------------------------------------ camera events (docs/ONVIF_EVENTS_PLAN.md §6)
@router.post("/cameras/{camera_id}/events/probe", response_model=EventProbeOut,
             summary="Detect which camera events (motion, tamper, inputs) the camera offers")
async def camera_events_probe(camera_id: int):
    camera = await _camera(camera_id)
    _node, result = await _camera_call(camera, "/api/v1/onvif/events/probe")
    status_ = dict(camera.onvif_events_status or {})
    status_.update(topics=result.get("topics") or {}, offered=result.get("offered") or [],
                   analytics=result.get("analytics") or [], detected_at=utcnow().isoformat())
    status_.setdefault("state", "detected")
    await Camera.filter(id=camera.id).update(onvif_events_status=status_)
    return {**result, "camera_id": camera.id}


@router.post("/events/apply", response_model=EventsApplyOut,
             summary="Switch camera events on/off for cameras and/or a group (with sub-groups); only visible cameras")
async def camera_events_apply(body: EventsApplyIn):
    target = Q(id__in=list(set(body.camera_ids))) if body.camera_ids else None
    if body.group_id is not None:
        group_q = await camera_scope(body.group_id, False, body.include_subgroups)
        target = group_q if target is None else (target | group_q)
    qs = Camera.filter(target)
    if (visible := await access.camera_q()) is not None:
        qs = qs.filter(visible)
    fields: dict = {"onvif_events_enabled": body.enabled}
    if body.enabled:
        fields["onvif_event_kinds"] = body.kinds
        if body.store_other is not None:
            fields["onvif_events_store_other"] = body.store_other
    # off keeps the last status (see cameras/router.py update_camera)
    return EventsApplyOut(updated=await qs.update(**fields))
