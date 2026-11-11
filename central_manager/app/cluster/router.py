from datetime import timedelta

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth import scope
from app.cameras.models import Camera, CameraStream
from app.cluster.alerts import AlertCounts, AlertOut, camera_alerts, count_levels
from app.nodes.models import MediaNode
from app.recordings.models import RecordingSegment
from utilities.common import utcnow
from utilities.pagination import Page, PageParams, page_of

router = APIRouter(prefix="/api/v1/cluster", tags=["Cluster"])


class ClusterHealthOut(BaseModel):
    cameras_total: int
    cameras_enabled: int
    record_streams: int  # streams set to record on enabled cameras (the "Recording x / y" KPI)
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
        record_streams=await CameraStream.filter(record=True, camera__enabled=True).count(),
        streams_by_status=_count([getattr(s, "value", s) for s in stream_states]),
        nodes_by_state=_count([getattr(s, "value", s) for s in node_states]),
        segments_last_hour=await RecordingSegment.filter(end_time__gte=utcnow() - timedelta(hours=1)).count(),
        segments_total=await RecordingSegment.all().count(),
    )


class AlertPage(Page[AlertOut]):
    counts: AlertCounts  # over all camera alerts, whatever `level` filter is applied


@router.get("/alerts", response_model=AlertPage, summary="Camera alerts for the dashboard (paged, danger first)")
async def cluster_alerts(
    page: PageParams = Depends(),
    level: Literal["danger", "warning"] | None = Query(default=None, description="Only this level"),
):
    """Enabled cameras that are unassigned, not recording, not answering ONVIF or whose clock drifts.
    Node alerts (unreachable, disk, storage) are built by the clients from `GET /api/v1/nodes`."""
    alerts = await camera_alerts()
    if (visible := await scope.camera_q()) is not None:  # only the caller's cameras
        ids = set(await Camera.filter(visible).values_list("id", flat=True))
        alerts = [a for a in alerts if a.camera_id in ids]
    shown = [a for a in alerts if level is None or a.level == level]
    paged = page_of(shown, page)
    return AlertPage(**paged.model_dump(), counts=count_levels(alerts))
