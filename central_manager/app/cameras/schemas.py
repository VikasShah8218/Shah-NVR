from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.cameras.models import StreamStatus


# Camera events from ONVIF (docs/ONVIF_EVENTS_PLAN.md). The analytics kinds are opt-in: null = the three basic kinds
# (docs/ONVIF_ANALYTICS_EVENTS_PLAN.md A5).
OnvifEventKind = Literal["motion", "tamper", "digital_input", "line_crossing", "intrusion", "loitering", "object_left",
                         "person", "face", "counting", "audio_alarm"]


class StreamIn(BaseModel):
    profile: str = Field(default="main", pattern=r"^[a-z0-9_-]{1,32}$", examples=["main"])
    source_url: str = Field(examples=["rtsp://192.168.1.64:554/Streaming/Channels/101"])
    record: bool = True
    rtsp_transport: str = Field(default="tcp", pattern=r"^(tcp|udp|automatic)$")

    @field_validator("source_url")
    @classmethod
    def check_scheme(cls, v: str) -> str:
        if not v.lower().startswith(("rtsp://", "rtsps://", "rtmp://", "srt://", "http://", "https://")):
            raise ValueError("source_url must be an rtsp/rtsps/rtmp/srt/http(s) URL")
        return v


class StreamUpdate(BaseModel):
    source_url: str | None = None
    record: bool | None = None
    rtsp_transport: str | None = Field(default=None, pattern=r"^(tcp|udp|automatic)$")


class StreamOut(BaseModel):
    id: int
    profile: str
    source_url: str
    record: bool
    rtsp_transport: str
    status: StreamStatus
    status_detail: str | None
    bytes_received: int
    last_status_at: datetime | None
    last_segment_at: datetime | None
    onvif_profile_token: str | None = None  # ONVIF media profile behind source_url
    audio_state: str = "unknown"
    audio_advertised: bool | None = None
    audio_observed: bool | None = None
    audio_codec: str | None = None
    audio_codec_raw: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    audio_bitrate_kbps: int | None = None
    audio_last_observed_at: datetime | None = None


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    username: str | None = None
    password: str | None = None
    enabled: bool = True
    # Days to keep, counted back from the camera's latest recording. Leave out for the default (create) /
    # unchanged (update); send null to keep recordings until storage is full.
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    has_ptz: bool = False  # PTZ-capable; auto-set from ONVIF detection when added through discovery
    group_id: int | None = None  # camera group (docs/GROUPING_PLAN.md); None = no group
    # When recorded streams record (docs/RECORDING_SCHEDULES_PLAN.md); schedule id needed with "schedule"
    recording_mode: Literal["always", "schedule", "never", "event"] = "always"
    recording_schedule_id: int | None = None
    # Event recording (docs/EVENT_RECORDING_PLAN.md): seconds kept before / after an event, and event marks
    event_pre_seconds: int = Field(default=10, ge=0, le=60)
    event_post_seconds: int = Field(default=30, ge=0, le=600)
    event_marking: bool = True
    # Camera events from ONVIF: off by default (plan D2); kinds null = all the camera offers
    onvif_events_enabled: bool = False
    onvif_event_kinds: list[OnvifEventKind] | None = None
    onvif_events_store_other: bool = False
    streams: list[StreamIn] = Field(min_length=1)

    @field_validator("streams")
    @classmethod
    def unique_profiles(cls, v: list[StreamIn]) -> list[StreamIn]:
        profiles = [s.profile for s in v]
        if len(profiles) != len(set(profiles)):
            raise ValueError("stream profiles must be unique")
        return v


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    username: str | None = None
    password: str | None = None
    enabled: bool | None = None
    expose_via_onvif: bool | None = None
    has_ptz: bool | None = None  # manual override of the PTZ flag; null = leave unchanged
    group_id: int | None = None  # send null to take the camera out of its group; leave out = unchanged
    # Days to keep, counted back from the camera's latest recording. Leave out for the default (create) /
    # unchanged (update); send null to keep recordings until storage is full.
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    # Leave out = unchanged. "schedule" needs recording_schedule_id (in this request or already set).
    recording_mode: Literal["always", "schedule", "never", "event"] | None = None
    recording_schedule_id: int | None = None
    event_pre_seconds: int | None = Field(default=None, ge=0, le=60)  # leave out = unchanged
    event_post_seconds: int | None = Field(default=None, ge=0, le=600)
    event_marking: bool | None = None
    onvif_events_enabled: bool | None = None  # leave out = unchanged
    onvif_event_kinds: list[OnvifEventKind] | None = None  # send null = the basic kinds (motion, tamper, inputs)
    onvif_events_store_other: bool | None = None


class AssignmentInfo(BaseModel):
    node_id: int | None
    node_name: str | None
    generation: int
    lease_expires_at: datetime | None


class CameraOut(BaseModel):
    id: int
    name: str
    description: str | None
    username: str | None
    has_password: bool
    enabled: bool
    expose_via_onvif: bool
    has_ptz: bool
    retention_days: int | None  # None = keep until storage is full
    recording_mode: str = "always"  # always | schedule | never | event
    recording_schedule_id: int | None = None
    recording_schedule_name: str | None = None
    recording_now: bool = True  # what the mode/schedule says right now (not whether a file is being written)
    recording_state: Literal["continuous", "event", "off"] = "continuous"  # the mode/schedule right now
    event_pre_seconds: int = 10
    event_post_seconds: int = 30
    event_marking: bool = True
    onvif_events_enabled: bool = False
    onvif_event_kinds: list[str] | None = None
    onvif_events_store_other: bool = False
    # From the recording node: state ok | auth_failed | no_topics | unsupported | unreachable | error, the topics in
    # use per kind, the kinds the camera offers, detail, last_event_at, since (also filled by "Detect")
    onvif_events_status: dict | None = None
    recording_next_change: datetime | None = None  # site wall clock, with offset
    # ONVIF device (null for cameras never seen over ONVIF)
    onvif_host: str | None = None
    onvif_port: int | None = None
    manufacturer: str | None = None
    model: str | None = None
    firmware: str | None = None
    serial: str | None = None
    mac: str | None = None
    onvif_services: list[str] | None = None
    onvif_reachable: bool | None = None
    clock_offset_seconds: float | None = None  # camera clock minus node clock
    onvif_checked_at: datetime | None = None
    group_id: int | None = None
    group_path: str | None = None  # "Anantnag › Bijbehara"
    created_at: datetime
    updated_at: datetime
    streams: list[StreamOut]
    assignment: AssignmentInfo | None


class CameraOption(BaseModel):
    """One row of a camera picker / live sidebar (GET /api/v1/cameras/options)."""

    id: int
    name: str
    enabled: bool
    has_ptz: bool
    profiles: list[str]  # stream profiles, e.g. ["main", "sub"]
    status: StreamStatus  # the recording stream's state (first stream if none records); DISABLED when disabled
    node_id: int | None  # assigned media node, if any
    group_id: int | None = None
    group_path: str | None = None  # "Anantnag › Bijbehara"


class LiveStreamUrls(BaseModel):
    profile: str
    codec_note: str = "Codec is passed through from the camera (no transcoding)."
    rtsp: str
    hls: str
    webrtc: str
    audio_state: str = "unknown"
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None


class LiveOut(BaseModel):
    camera_id: int
    node_id: int
    node_name: str
    generation: int
    streams: list[LiveStreamUrls]
