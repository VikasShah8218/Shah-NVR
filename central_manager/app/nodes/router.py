import logging
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status

from app.assignments.models import CameraAssignment
from app.cameras.models import CameraStream
from app.cameras.utils import build_source_url
from app.nodes import volumes as vol
from app.nodes.models import MediaNode, NodeState, StorageVolume
from app.nodes.schemas import (
    AssignmentsOut,
    CameraAssignmentOut,
    HeartbeatIn,
    HeartbeatOut,
    NodeOut,
    NodeRegisterIn,
    NodeRegisterOut,
    NodeUpdate,
    OnvifServerOut,
    OnvifServerUpdate,
    StreamAssignment,
    StreamStatusBatchIn,
    VolumeCreate,
    VolumeOrder,
    VolumeOut,
    VolumeUpdate,
)
from app.nodes.utils import gb_to_bytes, total_quota
from app.onvif.services import apply_onvif_health
from app.recordings.models import RecordingSegment
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("central.nodes")

router = APIRouter(prefix="/api/v1/nodes", tags=["Media Nodes"])
internal_router = APIRouter(prefix="/internal/v1/nodes", tags=["Internal: Media Nodes"])

HEALTHY_STATES = (NodeState.READY, NodeState.ACTIVE, NodeState.UNREACHABLE)


async def _get_node(node_id: int) -> MediaNode:
    node = await MediaNode.get_or_none(id=node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    return node


async def _node_out(node: MediaNode) -> NodeOut:
    count = await CameraAssignment.filter(node_id=node.id).count()
    volumes = await vol.node_volumes(node.id)
    fields = {k: getattr(node, k) for k in NodeOut.model_fields if k not in ("assigned_cameras", "volumes")}
    if volumes:  # the cap lives on the volumes now
        fields["storage_quota_bytes"] = total_quota([v.quota_bytes for v in volumes])
    return NodeOut(**fields, volumes=[vol.volume_out(v) for v in volumes], assigned_cameras=count)


# ================================================================ public API


@router.get("", response_model=list[NodeOut])
async def list_nodes():
    return [await _node_out(n) for n in await MediaNode.all()]


@router.get("/{node_id}", response_model=NodeOut)
async def get_node(node_id: int):
    return await _node_out(await _get_node(node_id))


@router.patch("/{node_id}", response_model=NodeOut)
async def update_node(node_id: int, body: NodeUpdate):
    node = await _get_node(node_id)
    data = body.model_dump(exclude_unset=True)
    if "storage_quota_gb" in data:  # deprecated: caps the default volume (older clients)
        quota = gb_to_bytes(data.pop("storage_quota_gb"))
        node.storage_quota_bytes = quota
        await StorageVolume.filter(node_id=node.id, is_default=True).update(quota_bytes=quota)
    enabled = data.get("public_enabled", node.public_enabled)
    public_api_url = data.get("public_api_url", node.public_api_url)
    public_media_host = data.get("public_media_host", node.public_media_host)
    if enabled and (not public_api_url or not public_media_host):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Public Node API URL and public media host are required before public access can be enabled",
        )
    if data:
        node.update_from_dict(data)
    await node.save()
    return await _node_out(node)


def _onvif_server_out(node: MediaNode) -> OnvifServerOut:
    runtime = (node.metrics or {}).get("onvif_server") or {}
    return OnvifServerOut(
        node_id=node.id,
        enabled=node.onvif_server_enabled,
        discovery_name=node.onvif_server_name,
        location=node.onvif_server_location,
        status=runtime.get("status", "disabled" if not node.onvif_server_enabled else "pending"),
        credentials_configured=bool(runtime.get("credentials_configured", False)),
        xaddr=runtime.get("xaddr"),
        rtsp_address=runtime.get("rtsp_address"),
        exposed_cameras=int(runtime.get("exposed_cameras") or 0),
        exposed_profiles=int(runtime.get("exposed_profiles") or 0),
        last_error=runtime.get("last_error"),
    )


@router.get("/{node_id}/onvif-server", response_model=OnvifServerOut)
async def get_onvif_server(node_id: int):
    return _onvif_server_out(await _get_node(node_id))


@router.patch("/{node_id}/onvif-server", response_model=OnvifServerOut)
async def update_onvif_server(node_id: int, body: OnvifServerUpdate):
    node = await _get_node(node_id)
    data = body.model_dump(exclude_unset=True)
    if "enabled" in data:
        node.onvif_server_enabled = data["enabled"]
    if "discovery_name" in data:
        node.onvif_server_name = data["discovery_name"].strip()
    if "location" in data:
        node.onvif_server_location = data["location"].strip() if data["location"] else None
    await node.save()
    return _onvif_server_out(node)


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a retired node")
async def delete_node(node_id: int, force: bool = False):
    """Refused while cameras are assigned. Refused if the node still has recordings in the
    catalog unless force=true (which also removes that recordings index). A node that is still
    running will register itself again."""
    node = await _get_node(node_id)
    if await CameraAssignment.filter(node_id=node.id).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "Node still has cameras assigned. Drain it first.")
    if not force and await RecordingSegment.filter(node_id=node.id).exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Node has recordings in the catalog. Use force=true to delete the node and its recordings index.",
        )
    await node.delete()
    logger.info("Node %s (%s) deleted by admin (force=%s)", node.id, node.name, force)


# ---------------------------------------------------------------- storage volumes


async def _get_volume(node_id: int, volume_id: int) -> StorageVolume:
    volume = await StorageVolume.get_or_none(id=volume_id, node_id=node_id)
    if volume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Storage volume not found")
    return volume


@router.get("/{node_id}/volumes", response_model=list[VolumeOut], summary="Where this node may record")
async def list_volumes(node_id: int):
    await _get_node(node_id)
    return [vol.volume_out(v) for v in await vol.node_volumes(node_id)]


@router.post("/{node_id}/volumes", response_model=VolumeOut, status_code=status.HTTP_201_CREATED,
             summary="Allow the node to record in another folder, drive or network share")
async def add_volume(node_id: int, body: VolumeCreate):
    """Added at the end of the fill order. The node checks the folder on its next heartbeat (state
    PENDING until then; OK, or ERROR/UNAVAILABLE with the reason). For a network share, save its
    credentials on the node PC first (cmdkey) - they are never stored here."""
    await _get_node(node_id)
    if await StorageVolume.exists(node_id=node_id, path=body.path):
        raise HTTPException(status.HTTP_409_CONFLICT, "This node already has that storage folder")
    last = await StorageVolume.filter(node_id=node_id).order_by("-position").first()
    volume = await StorageVolume.create(
        node_id=node_id, path=body.path, position=(last.position + 1) if last else 0,
        quota_bytes=gb_to_bytes(body.quota_gb), accepting=body.accepting,
    )
    logger.info("Node %s: storage volume %s added (cap %s)", node_id, volume.path, volume.quota_bytes)
    return vol.volume_out(volume)


@router.patch("/{node_id}/volumes/{volume_id}", response_model=VolumeOut, summary="Change a volume's cap or pause it")
async def update_volume(node_id: int, volume_id: int, body: VolumeUpdate):
    volume = await _get_volume(node_id, volume_id)
    data = body.model_dump(exclude_unset=True)
    if "quota_gb" in data:
        volume.quota_bytes = gb_to_bytes(data["quota_gb"])
        if volume.is_default:
            await MediaNode.filter(id=node_id).update(storage_quota_bytes=volume.quota_bytes)
    if data.get("accepting") is not None:
        volume.accepting = data["accepting"]
    await volume.save()
    return vol.volume_out(volume)


@router.post("/{node_id}/volumes/reorder", response_model=list[VolumeOut], summary="Set the fill order")
async def reorder_volumes(node_id: int, body: VolumeOrder):
    current = {v.id for v in await vol.node_volumes(node_id)}
    if set(body.volume_ids) != current or len(body.volume_ids) != len(current):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Send every volume id of this node exactly once")
    await vol.renumber(node_id, body.volume_ids)
    return [vol.volume_out(v) for v in await vol.node_volumes(node_id)]


@router.delete("/{node_id}/volumes/{volume_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Stop using a storage folder")
async def delete_volume(node_id: int, volume_id: int, force: bool = False):
    """The node's default folder cannot be removed (pause it instead). Refused while recordings on this
    volume are in the catalog unless force=true, which also removes their index (files stay on disk)."""
    volume = await _get_volume(node_id, volume_id)
    if volume.is_default:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "The node's default folder cannot be removed. Stop new recordings on it instead.")
    if await RecordingSegment.filter(volume_id=volume.id).exists():
        if not force:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Recordings are stored on this volume. Stop new recordings and let retention empty it, "
                "or use force=true to remove it together with its recordings index.",
            )
        await RecordingSegment.filter(volume_id=volume.id).delete()
    await volume.delete()
    logger.info("Node %s: storage volume %s removed (force=%s)", node_id, volume.path, force)


async def _set_state(node_id: int, new_state: NodeState) -> NodeOut:
    node = await _get_node(node_id)
    node.state = new_state
    await node.save(update_fields=["state", "updated_at"])
    logger.info("Node %s (%s) state set to %s by admin", node.id, node.name, new_state.value)
    return await _node_out(node)


@router.post("/{node_id}/drain", response_model=NodeOut, summary="Move all cameras away from this node")
async def drain_node(node_id: int):
    return await _set_state(node_id, NodeState.DRAINING)


@router.post("/{node_id}/cordon", response_model=NodeOut, summary="Keep current cameras, accept no new ones")
async def cordon_node(node_id: int):
    return await _set_state(node_id, NodeState.CORDONED)


@router.post("/{node_id}/activate", response_model=NodeOut, summary="Return node to normal scheduling")
async def activate_node(node_id: int):
    return await _set_state(node_id, NodeState.READY)


# ================================================================ internal API (called by media nodes)


@internal_router.post("/register", response_model=NodeRegisterOut)
async def register_node(body: NodeRegisterIn):
    data = body.model_dump()
    node = await MediaNode.get_or_none(name=body.name)
    if node is None:
        node = await MediaNode.create(**data, state=NodeState.READY, last_heartbeat_at=utcnow())
        logger.info("Node registered: %s (id=%s)", node.name, node.id)
    else:
        node.update_from_dict(data)
        node.last_heartbeat_at = utcnow()
        if node.state in (NodeState.UNREACHABLE,):
            node.state = NodeState.READY
        await node.save()
        logger.info("Node re-registered: %s (id=%s, state=%s)", node.name, node.id, node.state.value)
    return NodeRegisterOut(
        node_id=node.id, state=node.state, heartbeat_interval_seconds=max(1, settings.HEARTBEAT_TIMEOUT_SECONDS // 3)
    )


@internal_router.post("/{node_id}/heartbeat", response_model=HeartbeatOut)
async def heartbeat(node_id: int, body: HeartbeatIn):
    node = await _get_node(node_id)
    now = utcnow()
    lease_expires_at = now + timedelta(seconds=settings.LEASE_TTL_SECONDS)

    # Renew the lease of every camera this node currently owns.
    assigned = await CameraAssignment.filter(node_id=node.id).update(lease_expires_at=lease_expires_at)

    if node.state in HEALTHY_STATES:
        if node.state == NodeState.UNREACHABLE:
            logger.info("Node %s (%s) is reachable again", node.id, node.name)
        node.state = NodeState.ACTIVE if assigned else NodeState.READY
    node.last_heartbeat_at = now
    node.metrics = body.model_dump(exclude={"volumes", "onvif"})
    await node.save(update_fields=["state", "last_heartbeat_at", "metrics", "updated_at"])

    await vol.ensure_default_volume(node, body.default_recordings_dir)
    await vol.apply_reports(node.id, body.volumes)
    volumes = await vol.node_volumes(node.id)
    await apply_onvif_health(node.id, body.onvif)

    return HeartbeatOut(
        node_id=node.id,
        state=node.state,
        lease_expires_at=lease_expires_at,
        assignments=assigned,
        storage_quota_bytes=node.storage_quota_bytes,
        volumes=[vol.volume_config(v) for v in volumes],
        onvif_server={
            "enabled": node.onvif_server_enabled,
            "discovery_name": node.onvif_server_name,
            "location": node.onvif_server_location,
        },
        webrtc_additional_hosts=list(dict.fromkeys(
            [node.media_host] + ([node.public_media_host] if node.public_enabled and node.public_media_host else [])
        )),
    )


@internal_router.get("/{node_id}/assignments", response_model=AssignmentsOut)
async def node_assignments(node_id: int):
    """Desired state for a node: every camera stream it must pull (and record)."""
    node = await _get_node(node_id)
    assignments = await CameraAssignment.filter(node_id=node.id, camera__enabled=True).prefetch_related(
        "camera", "camera__streams"
    )
    cameras = []
    for a in assignments:
        cam = a.camera
        cameras.append(
            CameraAssignmentOut(
                camera_id=cam.id,
                camera_name=cam.name,
                generation=a.generation,
                streams=[
                    StreamAssignment(
                        profile=s.profile,
                        path_name=s.path_name(),
                        source_url=build_source_url(s, cam),
                        record=s.record,
                        rtsp_transport=s.rtsp_transport,
                    )
                    for s in cam.streams
                ],
                onvif_host=cam.onvif_host,
                onvif_port=cam.onvif_port,
                expose_via_onvif=cam.expose_via_onvif,
            )
        )
    return AssignmentsOut(node_id=node.id, state=node.state, cameras=cameras)


@internal_router.post("/{node_id}/stream-status", status_code=status.HTTP_204_NO_CONTENT)
async def report_stream_status(node_id: int, body: StreamStatusBatchIn):
    """Per-stream runtime state. Ignored for cameras this node no longer owns."""
    await _get_node(node_id)
    owned = set(await CameraAssignment.filter(node_id=node_id).values_list("camera_id", flat=True))
    now = utcnow()
    for item in body.items:
        if item.camera_id not in owned:
            continue
        fields = dict(
            status=item.status,
            status_detail=item.detail,
            bytes_received=item.bytes_received,
            last_status_at=now,
        )
        if item.audio is not None:
            audio = item.audio.model_dump()
            fields.update(
                audio_observed=audio["observed"],
                audio_last_observed_at=now,
            )
            if audio["observed"]:
                fields.update(
                    audio_codec=audio["codec"],
                    audio_codec_raw=audio["codec_raw"],
                    audio_sample_rate=audio["sample_rate"],
                    audio_channels=audio["channels"],
                )
        await CameraStream.filter(camera_id=item.camera_id, profile=item.profile).update(**fields)
