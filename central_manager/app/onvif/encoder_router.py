"""H2 control-plane journal. Camera settings are always read/written through a media node."""
import hashlib
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from tortoise.exceptions import IntegrityError

from app.cameras.models import Camera, CameraStream, EncoderChange
from app.nodes.client import call_node, pick_node
from app.onvif.encoder_schemas import EncoderState, EncoderWrite
from app.onvif.router import _camera
from app.onvif.services import device_target
from utilities.common import utcnow

router = APIRouter(prefix="/api/v1/cameras", tags=["Encoder"])


class ChangeResult(BaseModel):
    after: EncoderState | None = None
    message: str
    recovery: dict[str, str] = {}


class ChangeOut(BaseModel):
    id: str
    status: str
    created_at: datetime
    before: EncoderState | None = None
    result: ChangeResult | None = None


class HistoryOut(BaseModel):
    changes: list[ChangeOut]
    pending: ChangeOut | None


class RecoveryOut(BaseModel):
    status: str
    fresh_status: bool
    new_recording: bool | None
    recording_expected: bool
    last_status_at: datetime | None
    last_segment_at: datetime | None
    message: str


def error(code, message, status=409):
    raise HTTPException(status, {"code": code, "message": message})


def device_key(camera):
    host, port = device_target(camera)
    return hashlib.sha256(f"{host.lower().rstrip('.')}:{port}".encode()).hexdigest()


def payload(camera, token):
    host, port = device_target(camera)
    return {"host": host, "port": port, "username": camera.username or "", "password": camera.password or "",
            "profile_token": token}


async def target(camera_id, profile):
    camera = await _camera(camera_id)
    stream = next((s for s in camera.streams if s.profile == profile), None)
    if stream is None:
        error("stream_not_found", "Camera stream not found.", 404)
    return camera, stream


async def read(camera, stream, node=None):
    node = node or await pick_node(camera_id=camera.id)
    return await call_node(node, "/api/v1/onvif/encoder/read", payload(camera, stream.onvif_profile_token), timeout=60)


def public_change(row):
    return {"id": row.id, "status": row.status, "created_at": row.created_at, "before": row.before, "result": row.result}


@router.get("/{camera_id}/streams/{profile}/encoder", response_model=EncoderState)
async def get_encoder(camera_id: int, profile: str):
    camera, stream = await target(camera_id, profile)
    try:
        return await read(camera, stream)
    except HTTPException as exc:
        if not isinstance(exc.detail, dict) or exc.detail.get("code") != "profile_mapping_required":
            raise
        # A camera reset may remove the previously saved token. Offer explicit remapping rather
        # than trapping the user on an error screen or silently selecting another profile.
        stream.onvif_profile_token = None
        state = await read(camera, stream)
        state.setdefault("warnings", []).append("Saved ONVIF profile is no longer present. Select its replacement explicitly.")
        return state


class MappingIn(BaseModel):
    profile_token: str = Field(min_length=1, max_length=128)


@router.put("/{camera_id}/streams/{profile}/encoder/mapping", response_model=EncoderState)
async def map_encoder(camera_id: int, profile: str, body: MappingIn):
    camera, stream = await target(camera_id, profile)
    key = device_key(camera)
    node = await pick_node(camera_id=camera_id)
    try:
        row = await EncoderChange.create(id=str(uuid4()), camera_id=camera_id, profile=profile,
                                         profile_token=body.profile_token, device_key=key, active_key=key,
                                         node_id=node.id, request={"mapping": body.profile_token})
    except IntegrityError:
        error("encoder_busy", "Resolve the outstanding encoder operation before changing the mapping.")
    try:
        stream.onvif_profile_token = body.profile_token
        state = await read(camera, stream, node)  # never guess from resolution or list order
        await stream.save(update_fields=["onvif_profile_token"])
        row.status = "mapped"
        row.result = {"after": state, "message": "Profile mapping saved. No camera settings changed."}
        return state
    finally:
        row.active_key = None
        if row.status == "pending":
            row.status = "failed"
        await row.save(update_fields=["status", "result", "active_key", "updated_at"])


async def prepare(camera, stream, body):
    if not stream.onvif_profile_token:
        error("profile_mapping_required", "Select the ONVIF profile for this stream first.", 422)
    values = body.values.model_dump(exclude_none=True)
    if body.restore_from:
        previous = await EncoderChange.get_or_none(id=body.restore_from, camera_id=camera.id, profile=stream.profile)
        if (not previous or not previous.before or previous.profile_token != stream.onvif_profile_token
                or previous.device_key != device_key(camera)):
            error("restore_unavailable", "No matching previous configuration is available.", 422)
        values = {k: v for k, v in previous.before["current"].items() if v is not None}
    return {**payload(camera, stream.onvif_profile_token), "revision": body.revision,
            "values": values, "acknowledge_shared": body.acknowledge_shared}


@router.post("/{camera_id}/streams/{profile}/encoder/check", response_model=EncoderState)
async def check_encoder(camera_id: int, profile: str, body: EncoderWrite):
    camera, stream = await target(camera_id, profile)
    node = await pick_node(camera_id=camera_id)
    return await call_node(node, "/api/v1/onvif/encoder/check", await prepare(camera, stream, body), timeout=60)


@router.put("/{camera_id}/streams/{profile}/encoder", response_model=ChangeOut)
async def put_encoder(camera_id: int, profile: str, body: EncoderWrite):
    camera, stream = await target(camera_id, profile)
    existing = await EncoderChange.get_or_none(id=body.operation_id)
    saved_request = body.model_dump()
    if existing:
        if existing.camera_id != camera_id or existing.profile != profile or existing.request != saved_request:
            error("operation_reused", "This operation ID was already used for a different request.")
        return public_change(existing)  # idempotent replay, including timeouts and pending operations
    data = await prepare(camera, stream, body)
    node = await pick_node(camera_id=camera_id)
    key = device_key(camera)
    try:
        row = await EncoderChange.create(id=body.operation_id, camera_id=camera_id, profile=profile,
                                         profile_token=stream.onvif_profile_token, device_key=key, active_key=key,
                                         node_id=node.id, request=saved_request)
    except IntegrityError:
        error("encoder_busy", "An encoder operation is already pending for this device. Check its result first.")
    writing = False
    try:
        # Mapping can complete between the initial stream read and acquiring the device mutex.
        await stream.refresh_from_db(fields=["onvif_profile_token"])
        if stream.onvif_profile_token != row.profile_token:
            error("stale_mapping", "The profile mapping changed. Reload the encoder before applying.")
        row.before = await call_node(node, "/api/v1/onvif/encoder/check", data, timeout=60)
        await row.save(update_fields=["before", "updated_at"])
        # Include duplicate camera entries for the same device; shared profiles may feed several NVR paths.
        affected = []
        for other in await Camera.all().prefetch_related("streams"):
            try:
                if device_key(other) == key:
                    affected.append(other.id)
            except HTTPException:
                pass
        writing = True
        result = await call_node(node, "/api/v1/onvif/encoder/apply", {**data, "camera_ids": affected}, timeout=100)
        row.result, row.status = result, result["outcome"]
        if row.status != "unknown":
            row.active_key = None
        await row.save(update_fields=["result", "status", "active_key", "updated_at"])
        return public_change(row)
    except HTTPException as exc:
        definite = exc.status_code in (401, 409, 422, 501)
        row.status = "unknown" if writing and not definite else "failed"
        row.result = {"message": "Outcome unknown; check readback before another write." if row.status == "unknown"
                      else "Preflight or camera rejected the operation.", "error": exc.detail}
        if row.status != "unknown":
            row.active_key = None
        await row.save(update_fields=["result", "status", "active_key", "updated_at"])
        raise
    # A process crash leaves the durable mutex in place. /resolve requires a fresh read on the same node.


@router.get("/{camera_id}/streams/{profile}/encoder/history", response_model=HistoryOut)
async def encoder_history(camera_id: int, profile: str):
    camera, _ = await target(camera_id, profile)
    history = await EncoderChange.filter(camera_id=camera_id, profile=profile).limit(20)
    pending = await EncoderChange.get_or_none(active_key=device_key(camera))
    return {"changes": [public_change(r) for r in history], "pending": public_change(pending) if pending else None}


@router.post("/{camera_id}/streams/{profile}/encoder/resolve")
async def resolve_encoder(camera_id: int, profile: str):
    camera, stream = await target(camera_id, profile)
    row = await EncoderChange.get_or_none(active_key=device_key(camera))
    if row is None:
        return {"message": "No pending operation."}
    # A central timeout/disconnect can leave the node running its bounded 90-second operation.
    if (utcnow() - row.updated_at).total_seconds() < 120:
        error("encoder_busy", "Allow two minutes for the outstanding request to finish, then check readback.")
    node = await pick_node(node_id=row.node_id)  # never resolve through a different node after failover
    state = await call_node(node, "/api/v1/onvif/encoder/read", payload(camera, row.profile_token), timeout=60)
    row.result = {**(row.result or {}), "after": state, "message": "Fresh readback obtained. Review before another write."}
    row.status, row.active_key = "resolved", None
    await row.save(update_fields=["result", "status", "active_key", "updated_at"])
    return public_change(row)


@router.get("/{camera_id}/streams/{profile}/encoder/recovery", response_model=RecoveryOut)
async def encoder_recovery(camera_id: int, profile: str):
    camera, stream = await target(camera_id, profile)
    last = await EncoderChange.filter(device_key=device_key(camera), before__not_isnull=True).first()
    since = last.updated_at if last else None
    fresh = bool(since and stream.last_status_at and stream.last_status_at > since)
    segment = bool(since and stream.last_segment_at and stream.last_segment_at > since)
    return {"status": stream.status, "fresh_status": fresh, "new_recording": segment if stream.record else None,
            "recording_expected": bool(camera.enabled and stream.record),
            "last_status_at": stream.last_status_at, "last_segment_at": stream.last_segment_at,
            "message": "A fresh heartbeat/recording is evidence of recovery, not proof of browser playback compatibility."}
