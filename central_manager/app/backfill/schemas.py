from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.recordings.models import BackfillState


class EdgeRecordingOut(BaseModel):
    token: str
    source_id: str | None = None
    earliest: datetime | None = None
    latest: datetime | None = None
    replay_available: bool = False


class BackfillConfigOut(BaseModel):
    camera_id: int
    mode: Literal["off", "manual", "automatic"]
    profile: str
    capability: Literal["unknown", "supported", "unsupported", "degraded"]
    recording_token: str | None
    earliest: datetime | None
    latest: datetime | None
    checked_at: datetime | None
    error: str | None


class BackfillProbeOut(BackfillConfigOut):
    recordings: list[EdgeRecordingOut]


class BackfillConfigUpdate(BaseModel):
    mode: Literal["off", "manual", "automatic"] | None = None
    profile: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,32}$")
    recording_token: str | None = Field(default=None, max_length=256)


class BackfillJobCreate(BaseModel):
    start_time: datetime
    end_time: datetime
    profile: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,32}$")


class BackfillJobOut(BaseModel):
    id: UUID
    camera_id: int
    node_id: int | None
    profile: str
    recording_token: str
    start_time: datetime
    end_time: datetime
    state: BackfillState
    requested_by: str
    attempt_count: int
    progress_percent: float
    imported_seconds: float
    imported_bytes: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime


class ClaimIn(BaseModel):
    node_id: int


class ClaimedJobOut(BaseModel):
    id: UUID
    camera_id: int
    profile: str
    recording_token: str
    start_time: datetime
    end_time: datetime
    assignment_generation: int
    host: str
    port: int
    username: str
    password: str


class JobProgressIn(BaseModel):
    node_id: int
    state: Literal["DOWNLOADING", "INDEXING"]
    progress_percent: float = Field(ge=0, le=100)


class JobCompleteIn(BaseModel):
    node_id: int
    imported_seconds: float = Field(ge=0)
    imported_bytes: int = Field(ge=0)
    partial: bool = False


class JobFailIn(BaseModel):
    node_id: int
    code: str = Field(max_length=64)
    message: str = Field(max_length=512)
