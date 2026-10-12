from datetime import datetime

from pydantic import BaseModel


class AssignmentOut(BaseModel):
    camera_id: int
    camera_name: str
    node_id: int | None
    node_name: str | None
    generation: int
    lease_expires_at: datetime | None
    reason: str | None
    updated_at: datetime


class AssignmentHistoryOut(BaseModel):
    camera_id: int
    node_id: int | None
    generation: int
    reason: str
    started_at: datetime
    ended_at: datetime | None


class ManualAssignIn(BaseModel):
    node_id: int
