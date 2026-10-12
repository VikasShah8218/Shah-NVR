from fastapi import APIRouter, HTTPException, status

from app.assignments.models import AssignmentHistory, CameraAssignment
from app.assignments.schemas import AssignmentHistoryOut, AssignmentOut, ManualAssignIn
from app.assignments.services import assign_camera, scheduler_tick
from app.cameras.models import Camera
from app.nodes.models import MediaNode, NodeState

router = APIRouter(prefix="/api/v1/assignments", tags=["Assignments"])


def _out(a: CameraAssignment) -> AssignmentOut:
    return AssignmentOut(
        camera_id=a.camera_id,
        camera_name=a.camera.name,
        node_id=a.node_id,
        node_name=a.node.name if a.node else None,
        generation=a.generation,
        lease_expires_at=a.lease_expires_at,
        reason=a.reason,
        updated_at=a.updated_at,
    )


@router.get("", response_model=list[AssignmentOut])
async def list_assignments(node_id: int | None = None):
    qs = CameraAssignment.all().prefetch_related("camera", "node").order_by("camera_id")
    if node_id is not None:
        qs = qs.filter(node_id=node_id)
    return [_out(a) for a in await qs]


@router.put("/{camera_id}", response_model=AssignmentOut, summary="Manually move a camera to a node")
async def manual_assign(camera_id: int, body: ManualAssignIn):
    camera = await Camera.get_or_none(id=camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    if not camera.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Camera is disabled")
    node = await MediaNode.get_or_none(id=body.node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    if node.state not in (NodeState.READY, NodeState.ACTIVE, NodeState.CORDONED):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Node is {node.state.value}")
    a = await assign_camera(camera_id, node, "manual")
    await a.fetch_related("camera", "node")
    return _out(a)


@router.get("/{camera_id}/history", response_model=list[AssignmentHistoryOut])
async def assignment_history(camera_id: int, limit: int = 50):
    rows = await AssignmentHistory.filter(camera_id=camera_id).limit(limit)
    return [
        AssignmentHistoryOut(
            camera_id=r.camera_id, node_id=r.node_id, generation=r.generation,
            reason=r.reason, started_at=r.started_at, ended_at=r.ended_at,
        )
        for r in rows
    ]


@router.post("/run-scheduler", status_code=status.HTTP_204_NO_CONTENT, summary="Run one scheduler cycle now")
async def run_scheduler_now():
    await scheduler_tick()
