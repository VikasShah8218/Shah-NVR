from fastapi import APIRouter

from app.mediamtx.utils import mtx
from app.node.schemas import NodeStatusOut
from app.node.services import disk_info
from app.node.utils import runtime
from app.recordings.models import LocalSegment
from settings.settings import settings

router = APIRouter(prefix="/api/v1", tags=["Node"])


@router.get("/status", response_model=NodeStatusOut)
async def node_status():
    return NodeStatusOut(
        node_name=settings.NODE_NAME,
        node_id=runtime.node_id,
        api_url=settings.api_url,
        central_url=settings.CENTRAL_URL,
        central_online=runtime.central_online,
        last_central_contact=runtime.last_central_contact,
        mediamtx_running=runtime.mediamtx_running,
        mediamtx_version=runtime.mediamtx_version,
        recordings_dir=str(settings.RECORDINGS_DIR),
        disk=disk_info(),
        assigned_cameras=len(runtime.assignments),
        ready_paths=sorted(runtime.ready_since),
        pending_uploads=await LocalSegment.filter(uploaded=False).count(),
        local_segments=await LocalSegment.all().count(),
    )


@router.get("/assignments", summary="Cameras this node is currently running (cached from central)")
async def node_assignments():
    return list(runtime.assignments.values())


@router.get("/mediamtx/paths", summary="Live MediaMTX path state (debug)")
async def mediamtx_paths():
    return list((await mtx.list_runtime_paths()).values())
