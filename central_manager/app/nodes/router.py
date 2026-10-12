import logging
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status

from app.assignments.models import CameraAssignment
from app.cameras.models import CameraStream
from app.cameras.utils import build_source_url
from app.nodes.models import MediaNode, NodeState
from app.nodes.schemas import (
    AssignmentsOut,
    CameraAssignmentOut,
    HeartbeatIn,
    HeartbeatOut,
    NodeOut,
    NodeRegisterIn,
    NodeRegisterOut,
    NodeUpdate,
    StreamAssignment,
    StreamStatusBatchIn,
)
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
    return NodeOut(**{k: getattr(node, k) for k in NodeOut.model_fields if k != "assigned_cameras"},
                   assigned_cameras=count)


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
    if "storage_quota_gb" in data:
        gb = data.pop("storage_quota_gb")
        node.storage_quota_bytes = int(gb * 1024**3) if gb is not None else None
    if data:
        node.update_from_dict(data)
    await node.save()
    return await _node_out(node)


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
    node.metrics = body.model_dump()
    await node.save(update_fields=["state", "last_heartbeat_at", "metrics", "updated_at"])

    return HeartbeatOut(
        node_id=node.id,
        state=node.state,
        lease_expires_at=lease_expires_at,
        assignments=assigned,
        storage_quota_bytes=node.storage_quota_bytes,
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
        await CameraStream.filter(camera_id=item.camera_id, profile=item.profile).update(
            status=item.status,
            status_detail=item.detail,
            bytes_received=item.bytes_received,
            last_status_at=now,
        )
