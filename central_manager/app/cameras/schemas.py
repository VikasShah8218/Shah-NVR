from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.cameras.models import StreamStatus


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


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    username: str | None = None
    password: str | None = None
    enabled: bool = True
    # Days to keep, counted back from the camera's latest recording. Leave out for the default (create) /
    # unchanged (update); send null to keep recordings until storage is full.
    retention_days: int | None = Field(default=None, ge=1, le=3650)
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
    # Days to keep, counted back from the camera's latest recording. Leave out for the default (create) /
    # unchanged (update); send null to keep recordings until storage is full.
    retention_days: int | None = Field(default=None, ge=1, le=3650)


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
    retention_days: int | None  # None = keep until storage is full
    created_at: datetime
    updated_at: datetime
    streams: list[StreamOut]
    assignment: AssignmentInfo | None


class LiveStreamUrls(BaseModel):
    profile: str
    codec_note: str = "Codec is passed through from the camera (no transcoding)."
    rtsp: str
    hls: str
    webrtc: str


class LiveOut(BaseModel):
    camera_id: int
    node_id: int
    node_name: str
    generation: int
    streams: list[LiveStreamUrls]
