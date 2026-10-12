from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.cameras.models import StreamStatus
from app.nodes.models import NodeState

# ---------------------------------------------------------------- node -> central (internal)


class NodeRegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    api_url: str
    media_host: str
    rtsp_port: int = 8554
    hls_port: int = 8888
    webrtc_port: int = 8889
    capacity_cameras: int = Field(default=100, ge=1)
    version: str | None = None
    mediamtx_version: str | None = None


class NodeRegisterOut(BaseModel):
    node_id: int
    state: NodeState
    heartbeat_interval_seconds: int


class DiskInfo(BaseModel):
    path: str
    total_bytes: int
    free_bytes: int
    used_percent: float


class HeartbeatIn(BaseModel):
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk: DiskInfo | None = None
    mediamtx_running: bool = True
    paths_configured: int = 0
    paths_ready: int = 0
    pending_uploads: int = 0
    extra: dict[str, Any] | None = None


class HeartbeatOut(BaseModel):
    node_id: int
    state: NodeState
    lease_expires_at: datetime
    assignments: int


class StreamAssignment(BaseModel):
    profile: str
    path_name: str
    source_url: str
    record: bool
    rtsp_transport: str


class CameraAssignmentOut(BaseModel):
    camera_id: int
    camera_name: str
    generation: int
    streams: list[StreamAssignment]


class AssignmentsOut(BaseModel):
    node_id: int
    state: NodeState
    cameras: list[CameraAssignmentOut]


class StreamStatusIn(BaseModel):
    camera_id: int
    profile: str
    status: StreamStatus
    detail: str | None = None
    bytes_received: int = 0


class StreamStatusBatchIn(BaseModel):
    items: list[StreamStatusIn]


# ---------------------------------------------------------------- public


class NodeOut(BaseModel):
    id: int
    name: str
    api_url: str
    media_host: str
    rtsp_port: int
    hls_port: int
    webrtc_port: int
    capacity_cameras: int
    version: str | None
    mediamtx_version: str | None
    state: NodeState
    last_heartbeat_at: datetime | None
    metrics: dict[str, Any] | None
    assigned_cameras: int = 0


class NodeUpdate(BaseModel):
    capacity_cameras: int | None = Field(default=None, ge=1)
