from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.cameras.models import StreamStatus
from app.nodes.models import NodeState, VolumeState
from app.nodes.utils import normalize_volume_path

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


class GpuInfo(BaseModel):
    name: str
    utilization_percent: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None


class DriveInfo(BaseModel):
    """A local fixed drive of the node (offered in "Add storage")."""

    root: str  # e.g. "D:\\"
    label: str | None = None
    fstype: str | None = None
    total_bytes: int
    free_bytes: int


class VolumeReport(BaseModel):
    """The node's view of one storage volume."""

    id: int
    state: VolumeState
    state_detail: str | None = None
    total_bytes: int | None = None
    free_bytes: int | None = None
    recordings_bytes: int | None = None
    writing: bool = False


class HeartbeatIn(BaseModel):
    cpu_percent: float | None = None
    cpu_count: int | None = None
    memory_percent: float | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    gpus: list[GpuInfo] = []
    disk: DiskInfo | None = None
    recordings_bytes: int | None = None
    net_rx_mbps: float | None = None
    net_tx_mbps: float | None = None
    mediamtx_running: bool = True
    paths_configured: int = 0
    paths_ready: int = 0
    pending_uploads: int = 0
    # the node's IPv4 addresses [{interface, ip, usable}] (it advertises one of them as media_host)
    addresses: list[dict[str, Any]] = []
    # storage volumes (nodes older than 2026-10-15 send none of these)
    default_recordings_dir: str | None = None
    drives: list[DriveInfo] = []
    volumes: list[VolumeReport] = []
    extra: dict[str, Any] | None = None


class VolumeConfig(BaseModel):
    """What a node needs to know about one of its volumes (sent in every heartbeat response)."""

    id: int
    path: str
    position: int
    quota_bytes: int | None
    accepting: bool
    is_default: bool


class HeartbeatOut(BaseModel):
    node_id: int
    state: NodeState
    lease_expires_at: datetime
    assignments: int
    storage_quota_bytes: int | None = None  # deprecated: for nodes older than storage volumes
    volumes: list[VolumeConfig] = []


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


class VolumeOut(BaseModel):
    id: int
    path: str
    kind: str  # local | network
    position: int
    quota_bytes: int | None
    accepting: bool
    is_default: bool
    state: VolumeState
    state_detail: str | None
    total_bytes: int | None
    free_bytes: int | None
    recordings_bytes: int | None
    writing: bool
    last_report_at: datetime | None


class VolumeCreate(BaseModel):
    path: str = Field(
        min_length=3,
        max_length=400,
        description=r"A folder on the node: D:\ShahNVR\recordings, \\192.168.1.9\nvr (network share) or /data/nvr",
    )
    quota_gb: float | None = Field(default=None, gt=0, description="Max GB of recordings here; null = whole disk")
    accepting: bool = True

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return normalize_volume_path(value)


class VolumeUpdate(BaseModel):
    quota_gb: float | None = Field(default=None, gt=0, description="null = whole disk")
    accepting: bool | None = None


class VolumeOrder(BaseModel):
    volume_ids: list[int] = Field(min_length=1, description="All of the node's volume ids, in fill order")


class NodeOut(BaseModel):
    id: int
    name: str
    api_url: str
    media_host: str
    rtsp_port: int
    hls_port: int
    webrtc_port: int
    capacity_cameras: int
    storage_quota_bytes: int | None  # total cap of all volumes (None if any volume is uncapped)
    volumes: list[VolumeOut] = []
    version: str | None
    mediamtx_version: str | None
    state: NodeState
    last_heartbeat_at: datetime | None
    metrics: dict[str, Any] | None
    assigned_cameras: int = 0


class NodeUpdate(BaseModel):
    capacity_cameras: int | None = Field(default=None, ge=1)
    # Deprecated (use the volumes API): sets the cap of the node's default volume. null = whole disk.
    storage_quota_gb: float | None = Field(default=None, gt=0)
