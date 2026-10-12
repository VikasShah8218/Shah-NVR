from typing import Literal

from fastapi import APIRouter, Query

from app.mediamtx.utils import mtx
from app.node.schemas import NodeStatusOut
from app.node.services import disk_info
from app.node.utils import runtime
from app.recordings.models import LocalSegment
from settings.settings import settings
from utilities.logbuffer import log_buffer

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


def _tail_file(path, lines: int) -> list[str]:
    if not path.exists():
        return []
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 256 * 1024))
        data = f.read().decode("utf-8", "replace")
    return data.splitlines()[-lines:]


@router.get("/logs", summary="Recent log lines of the agent or MediaMTX")
async def node_logs(
    source: Literal["agent", "mediamtx"] = "agent",
    lines: int = Query(default=200, ge=1, le=2000),
):
    if source == "agent":
        out = log_buffer.tail(lines)
    else:
        out = _tail_file(settings.DATA_DIR / "logs" / "mediamtx.log", lines)
    return {"source": source, "lines": out}
