"""API contract: pydantic models for every response the desktop app reads.

Mirrors the central manager / media node schemas (see nvr_client/openapi/*.json and
docs/memory/06_api_reference.md). When a backend API changes, update this one file.
Stores convert these to plain dicts (`to_qml`) before handing them to QML.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    def to_qml(self) -> dict:
        return self.model_dump(mode="json")


# ---------------------------------------------------------------- cameras
class Stream(ApiModel):
    id: int
    profile: str
    source_url: str
    record: bool
    rtsp_transport: str
    status: str
    status_detail: str | None = None
    bytes_received: int = 0
    last_status_at: datetime | None = None
    last_segment_at: datetime | None = None
    onvif_profile_token: str | None = None
    audio_state: str = "unknown"
    audio_advertised: bool | None = None
    audio_observed: bool | None = None
    audio_codec: str | None = None
    audio_codec_raw: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    audio_bitrate_kbps: int | None = None
    audio_last_observed_at: datetime | None = None


class AssignmentInfo(ApiModel):
    node_id: int | None = None
    node_name: str | None = None
    generation: int = 0
    lease_expires_at: datetime | None = None


class Camera(ApiModel):
    id: int
    name: str
    description: str | None = None
    username: str | None = None
    has_password: bool = False
    enabled: bool = True
    expose_via_onvif: bool = True
    retention_days: int | None = 7  # None = keep until storage is full
    created_at: datetime
    updated_at: datetime
    streams: list[Stream] = []
    assignment: AssignmentInfo | None = None
    onvif_host: str | None = None
    onvif_port: int | None = None
    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    serial: str | None = None
    mac: str | None = None
    onvif_services: list[str] | None = None
    onvif_reachable: bool | None = None
    clock_offset_seconds: float | None = None
    onvif_checked_at: datetime | None = None


class LiveUrls(ApiModel):
    profile: str
    codec_note: str = ""
    rtsp: str
    hls: str
    webrtc: str
    audio_state: str = "unknown"
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None


class LiveInfo(ApiModel):
    camera_id: int
    node_id: int
    node_name: str
    generation: int
    streams: list[LiveUrls]


# ---------------------------------------------------------------- ONVIF H1
class OnvifDiscovered(ApiModel):
    endpoint: str
    host: str
    port: int
    xaddr: str
    name: str | None = None
    hardware: str | None = None
    location: str | None = None
    mac: str | None = None
    profiles: list[str] = []
    node_id: int
    node_name: str
    camera_id: int | None = None
    camera_name: str | None = None


class OnvifClock(ApiModel):
    offset_seconds: float | None = None
    source: str | None = None
    timezone: str | None = None
    camera_utc: str | None = None


class OnvifProfile(ApiModel):
    token: str
    name: str | None = None
    api: str
    encoding: str | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    bitrate_kbps: int | None = None
    has_audio: bool = False
    has_ptz: bool = False
    rtsp: str | None = None
    snapshot: str | None = None


class OnvifSuggestion(ApiModel):
    main: str | None = None
    sub: str | None = None


class OnvifDeviceInfo(ApiModel):
    manufacturer: str | None = None
    model: str | None = None
    firmwareversion: str | None = None
    serialnumber: str | None = None
    hardwareid: str | None = None


class OnvifProbe(ApiModel):
    node_id: int
    host: str
    port: int
    device_url: str
    clock: OnvifClock
    info: OnvifDeviceInfo
    services: list[str] = []
    profiles: list[OnvifProfile] = []
    suggested: OnvifSuggestion
    camera_id: int | None = None


class OnvifNtp(ApiModel):
    from_dhcp: bool = False
    servers: list[str] = []


class OnvifNetwork(ApiModel):
    mac: str | None = None
    dhcp: bool = False
    ip: str | None = None
    prefix_length: int | None = None


class OnvifDeviceState(ApiModel):
    camera_id: int
    node_id: int
    host: str
    port: int
    clock: OnvifClock
    info: OnvifDeviceInfo
    services: list[str] = []
    ntp: OnvifNtp | None = None
    hostname: str | None = None
    network: OnvifNetwork | None = None
    checked_at: datetime


# ---------------------------------------------------------------- recordings
class Segment(ApiModel):
    id: UUID
    profile: str
    node_id: int
    generation: int
    start_time: datetime
    end_time: datetime
    duration_ms: int
    size_bytes: int
    codec: str | None = None
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    origin: str = "NVR"
    backfill_job_id: UUID | None = None
    status: str


class Gap(ApiModel):
    start_time: datetime
    end_time: datetime
    seconds: float


class Timeline(ApiModel):
    camera_id: int
    profile: str
    start: datetime
    end: datetime
    recorded_seconds: float
    coverage_percent: float
    total_size_bytes: int
    segments: list[Segment]
    gaps: list[Gap]


# ---------------------------------------------------------------- nodes
class StorageVolume(ApiModel):
    """A place where a node records: its own folder, another drive or a network share (fill in order)."""

    id: int
    path: str
    kind: str  # local | network
    position: int
    quota_bytes: int | None = None  # None = whole disk
    accepting: bool = True
    is_default: bool = False
    state: str  # PENDING | OK | FULL | UNAVAILABLE | ERROR
    state_detail: str | None = None
    total_bytes: int | None = None
    free_bytes: int | None = None
    recordings_bytes: int | None = None
    writing: bool = False
    last_report_at: datetime | None = None


class MediaNode(ApiModel):
    id: int
    name: str
    api_url: str
    media_host: str
    rtsp_port: int
    hls_port: int
    webrtc_port: int
    public_enabled: bool = False
    public_api_url: str | None = None
    public_media_host: str | None = None
    public_rtsp_port: int | None = None
    public_hls_port: int | None = None
    public_webrtc_port: int | None = None
    public_media_tls: bool = False
    capacity_cameras: int
    storage_quota_bytes: int | None = None  # total of the volume caps (None if any volume is uncapped)
    volumes: list[StorageVolume] = []
    version: str | None = None
    mediamtx_version: str | None = None
    state: str
    last_heartbeat_at: datetime | None = None
    metrics: dict[str, Any] | None = None
    assigned_cameras: int = 0


class ClusterHealth(ApiModel):
    cameras_total: int
    cameras_enabled: int
    streams_by_status: dict[str, int]
    nodes_by_state: dict[str, int]
    segments_last_hour: int
    segments_total: int


# ---------------------------------------------------------------- assignments
class Assignment(ApiModel):
    camera_id: int
    camera_name: str
    node_id: int | None = None
    node_name: str | None = None
    generation: int
    lease_expires_at: datetime | None = None
    reason: str | None = None
    updated_at: datetime


class AssignmentHistory(ApiModel):
    camera_id: int
    node_id: int | None = None
    generation: int
    reason: str
    started_at: datetime
    ended_at: datetime | None = None


# ---------------------------------------------------------------- media node (direct API)
class NodeStatus(ApiModel):
    node_name: str
    node_id: int | None = None
    api_url: str
    central_url: str
    central_online: bool
    last_central_contact: datetime | None = None
    mediamtx_running: bool
    mediamtx_version: str | None = None
    recordings_dir: str
    disk: dict[str, Any]
    assigned_cameras: int
    ready_paths: list[str]
    pending_uploads: int
    local_segments: int


class LocalSegment(ApiModel):
    id: UUID
    camera_id: int
    profile: str
    generation: int
    rel_path: str
    start_time: datetime
    end_time: datetime
    duration_ms: int
    size_bytes: int
    codec: str | None = None
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    origin: str = "NVR"
    backfill_job_id: UUID | None = None
    part_count: int
    uploaded: bool


# ---------------------------------------------------------------- H3 PTZ
class PtzCapabilities(ApiModel):
    pan_tilt: bool = False
    zoom: bool = False
    presets: bool = False
    home: bool = False
    home_set: bool = False
    camera_timeout_seconds: float | None = None


class PtzStatus(ApiModel):
    pan: float | None = None
    tilt: float | None = None
    zoom: float | None = None
    pan_tilt_state: str | None = None
    zoom_state: str | None = None
    position_valid: bool = False


class PtzPreset(ApiModel):
    token: str
    name: str


class PtzState(ApiModel):
    session_id: str
    expires_in_seconds: int
    capabilities: PtzCapabilities
    status: PtzStatus
    presets: list[PtzPreset] = []
    warnings: list[str] = []


class PtzResult(ApiModel):
    message: str
    status: PtzStatus | None = None
    presets: list[PtzPreset] | None = None


# ---------------------------------------------------------------- H5 virtual ONVIF server
class OnvifServer(ApiModel):
    node_id: int
    enabled: bool
    discovery_name: str
    location: str | None = None
    status: str
    credentials_configured: bool
    xaddr: str | None = None
    rtsp_address: str | None = None
    exposed_cameras: int = 0
    exposed_profiles: int = 0
    last_error: str | None = None


# ---------------------------------------------------------------- L3 edge storage backfill
class EdgeRecording(ApiModel):
    token: str
    source_id: str | None = None
    earliest: datetime | None = None
    latest: datetime | None = None
    replay_available: bool = False


class BackfillConfig(ApiModel):
    camera_id: int
    mode: str
    profile: str
    capability: str
    recording_token: str | None = None
    earliest: datetime | None = None
    latest: datetime | None = None
    checked_at: datetime | None = None
    error: str | None = None


class BackfillProbe(BackfillConfig):
    recordings: list[EdgeRecording] = []


class BackfillJob(ApiModel):
    id: UUID
    camera_id: int
    node_id: int | None = None
    profile: str
    recording_token: str
    start_time: datetime
    end_time: datetime
    state: str
    requested_by: str
    attempt_count: int
    progress_percent: float
    imported_seconds: float
    imported_bytes: int
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime
