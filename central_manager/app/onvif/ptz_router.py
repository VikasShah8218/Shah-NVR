"""PTZ sessions pin Stop to the original node, device and ONVIF profile.

No schema migration: preset definitions live on the camera. Tickets/credentials
are transient process memory, never returned to clients or written to a journal.
"""
import time
from dataclasses import dataclass
from fastapi import APIRouter, HTTPException
from app.assignments.models import CameraAssignment
from app.nodes.models import MediaNode
from app.nodes.client import call_node, REACHABLE_STATES
from app.onvif.encoder_router import target, payload
from app.onvif.ptz_schemas import PtzCommand, PtzState, PtzResult

router = APIRouter(prefix="/api/v1/cameras", tags=["PTZ"])


@dataclass
class Pin:
    camera_id: int
    profile: str
    node_id: int
    generation: int
    body: dict
    touched: float


pins: dict[str, Pin] = {}


def fail(code, message, status=409):
    raise HTTPException(status, {"code": code, "message": message})


async def assigned(camera_id):
    assignment = await CameraAssignment.get_or_none(camera_id=camera_id).prefetch_related("node")
    if assignment is None or assignment.node is None or assignment.node.state not in REACHABLE_STATES:
        fail("ptz_node_unavailable", "PTZ requires an assigned, reachable media node.")
    return assignment


@router.post("/{camera_id}/streams/{profile}/ptz", response_model=PtzState)
async def open_ptz(camera_id: int, profile: str):
    camera, stream = await target(camera_id, profile)
    if not camera.enabled:
        fail("camera_disabled", "Enable the camera before using PTZ.")
    if not stream.onvif_profile_token:
        fail("profile_mapping_required", "Map this stream to its ONVIF profile in the Video tab first.")
    now = time.monotonic()
    for sid, pin in list(pins.items()):
        if now - pin.touched > 180:
            del pins[sid]
    if len(pins) >= 256:
        fail("ptz_busy", "Too many open PTZ sessions. Retry later.", 429)
    assignment = await assigned(camera_id)
    body = payload(camera, stream.onvif_profile_token)
    result = await call_node(assignment.node, "/api/v1/onvif/ptz/open", body, timeout=30)
    pins[result["session_id"]] = Pin(camera_id, profile, assignment.node_id, assignment.generation, body, time.monotonic())
    return result


@router.post("/{camera_id}/streams/{profile}/ptz/command", response_model=PtzResult)
async def ptz_command(camera_id: int, profile: str, body: PtzCommand):
    pin = pins.get(body.session_id)
    if pin is None or (pin.camera_id, pin.profile) != (camera_id, profile):
        fail("ptz_session_expired", "Reload PTZ controls before issuing commands.")
    if body.action != "stop":
        if time.monotonic() - pin.touched > 120:
            fail("ptz_session_expired", "PTZ session expired. Reload controls.")
        camera, stream = await target(camera_id, profile)
        assignment = await assigned(camera_id)
        if (not camera.enabled or assignment.node_id != pin.node_id or assignment.generation != pin.generation
                or payload(camera, stream.onvif_profile_token) != pin.body):
            fail("ptz_target_changed", "Camera assignment, credentials or mapping changed. Stop and reload PTZ.")
    # Stop deliberately bypasses current assignment/enabled state; never fail over
    # a movement command or Stop to a different node.
    node = await MediaNode.get_or_none(id=pin.node_id)
    if node is None:
        fail("ptz_node_unavailable", "Original PTZ node no longer exists.")
    pin.touched = time.monotonic()
    return await call_node(node, "/api/v1/onvif/ptz/command", {**pin.body, "command": body.model_dump()}, timeout=15)
