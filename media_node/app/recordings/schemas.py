from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
    part_count: int
    uploaded: bool
