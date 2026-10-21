from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.recordings.models import SegmentOrigin


class LocalSegmentOut(BaseModel):
    id: UUID
    camera_id: int
    profile: str
    generation: int
    rel_path: str
    start_time: datetime
    end_time: datetime
    duration_ms: int
    size_bytes: int
    codec: str | None
    audio_codec: str | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    origin: SegmentOrigin = SegmentOrigin.NVR
    backfill_job_id: UUID | None = None
    part_count: int
    uploaded: bool
