from datetime import timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from app.cameras.models import Camera, CameraStream
from app.nodes.models import MediaNode
from app.recordings.models import RecordingSegment
from utilities.common import utcnow

router = APIRouter(prefix="/api/v1/cluster", tags=["Cluster"])


class ClusterHealthOut(BaseModel):
    cameras_total: int
    cameras_enabled: int
    streams_by_status: dict[str, int]
    nodes_by_state: dict[str, int]
    segments_last_hour: int
    segments_total: int


def _count(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


@router.get("/health", response_model=ClusterHealthOut)
async def cluster_health():
    stream_states = await CameraStream.all().values_list("status", flat=True)
    node_states = await MediaNode.all().values_list("state", flat=True)
    return ClusterHealthOut(
        cameras_total=await Camera.all().count(),
        cameras_enabled=await Camera.filter(enabled=True).count(),
        streams_by_status=_count([getattr(s, "value", s) for s in stream_states]),
        nodes_by_state=_count([getattr(s, "value", s) for s in node_states]),
        segments_last_hour=await RecordingSegment.filter(end_time__gte=utcnow() - timedelta(hours=1)).count(),
        segments_total=await RecordingSegment.all().count(),
    )
