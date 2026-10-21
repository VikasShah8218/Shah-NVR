from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.recordings.models import ExportMode, ExportState


class ExportCreate(BaseModel):
    camera_id: int
    profile: str = Field(default="main", pattern=r"^[a-z0-9_-]{1,32}$")
    start_time: datetime
    end_time: datetime
    mode: ExportMode = ExportMode.ORIGINAL
    video_codec: Literal["h264", "h265"] = "h264"
    quality: Literal["high", "balanced", "small"] = "balanced"
    processor: Literal["auto", "cpu", "gpu"] = "auto"
    max_height: Literal[0, 360, 480, 720, 1080, 1440, 2160] = 0
    max_fps: int = Field(default=0, ge=0, le=120)
    include_audio: bool = True
    audio_bitrate_kbps: Literal[64, 96, 128, 160, 192, 256] = 128

    @field_validator("start_time", "end_time")
    @classmethod
    def utc_dates(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def normalize_original(self):
        if self.mode == ExportMode.ORIGINAL:
            self.max_height = self.max_fps = 0
        return self


class ExportOut(BaseModel):
    id: UUID
    camera_id: int
    node_id: int | None
    profile: str
    start_time: datetime
    end_time: datetime
    mode: ExportMode
    state: ExportState
    options: dict
    progress_percent: float
    attempt_count: int
    output_name: str | None
    output_size_bytes: int
    output_sha256: str | None
    encoder: str | None
    recorded_seconds: float
    gap_seconds: float
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    expires_at: datetime | None
    updated_at: datetime


class ClaimIn(BaseModel):
    node_id: int


class ClaimedExportOut(BaseModel):
    id: UUID
    source_url: str
    camera_id: int
    camera_name: str
    profile: str
    start_time: datetime
    end_time: datetime
    mode: ExportMode
    options: dict
    output_name: str
    trim_start_seconds: float
    max_output_seconds: float


class ProgressIn(BaseModel):
    node_id: int
    state: Literal["PROCESSING", "FINALIZING"]
    progress_percent: float = Field(ge=0, le=100)


class CompleteIn(BaseModel):
    node_id: int
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    encoder: str = Field(max_length=64)
    recorded_seconds: float = Field(ge=0)


class FailIn(BaseModel):
    node_id: int
    code: str = Field(max_length=64)
    message: str = Field(max_length=512)


class ProgressOut(BaseModel):
    cancelled: bool
