from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.recordings.models import SegmentStatus

# ---------------------------------------------------------------- internal (node -> central)


class SegmentIn(BaseModel):
    id: UUID
    camera_id: int
    profile: str
    generation: int = 0
    start_time: datetime
    end_time: datetime
    duration_ms: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    codec: str | None = None
    config_signature: str | None = Field(None, max_length=64)
    file_path: str  # relative to the volume's folder
    volume_id: int | None = None  # None = the node's default folder (nodes older than storage volumes)
    parts: list[int] = Field(min_length=1)


class SegmentBatchIn(BaseModel):
    node_id: int
    items: list[SegmentIn] = Field(max_length=1000)


class SegmentBatchOut(BaseModel):
    accepted: int
    duplicates: int
    ignored: int


class DeletionItem(BaseModel):
    id: UUID
    file_path: str
    volume_id: int | None = None


class DeletedIn(BaseModel):
    ids: list[UUID]


# ---------------------------------------------------------------- public


class SegmentOut(BaseModel):
    id: UUID
    profile: str
    node_id: int
    generation: int
    start_time: datetime
    end_time: datetime
    duration_ms: int
    size_bytes: int
    codec: str | None
    status: SegmentStatus


class GapOut(BaseModel):
    start_time: datetime
    end_time: datetime
    seconds: float


class TimelineOut(BaseModel):
    camera_id: int
    profile: str
    start: datetime
    end: datetime
    recorded_seconds: float
    coverage_percent: float
    total_size_bytes: int
    segments: list[SegmentOut]
    gaps: list[GapOut]
