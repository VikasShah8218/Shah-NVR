from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schedules.utils import parse_hhmm

BlockMode = Literal["continuous", "off"]  # "event" comes with event-triggered recording
CameraRecordingMode = Literal["always", "schedule", "never"]
MAX_BLOCKS = 50


class ScheduleBlock(BaseModel):
    """One weekly block. `end <= start` runs past midnight; "24:00" = end of the day; start == end = 24 h."""

    days: list[int] = Field(min_length=1, max_length=7, description="0 = Monday ... 6 = Sunday")
    start: str = Field(examples=["08:00"])
    end: str = Field(examples=["18:00"])
    mode: BlockMode = "continuous"

    @field_validator("days")
    @classmethod
    def check_days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v) or len(set(v)) != len(v):
            raise ValueError("days must be distinct numbers 0 (Monday) to 6 (Sunday)")
        return sorted(v)

    @field_validator("start", "end")
    @classmethod
    def check_time(cls, v: str) -> str:
        parse_hhmm(v)
        return v

    @model_validator(mode="after")
    def check_start(self):
        if self.start == "24:00":
            raise ValueError("start cannot be 24:00")
        return self


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    blocks: list[ScheduleBlock] = Field(default_factory=list, max_length=MAX_BLOCKS)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name is empty")
        return v.strip()


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    blocks: list[ScheduleBlock] | None = Field(default=None, max_length=MAX_BLOCKS)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("name is empty")
        return v.strip() if v else v


class ScheduleOut(BaseModel):
    id: int
    name: str
    description: str | None
    blocks: list[ScheduleBlock]
    camera_count: int
    recording_now: bool  # the schedule's mode at this moment is "continuous"
    next_change: datetime | None  # site wall clock, with its offset
    created_at: datetime
    updated_at: datetime


class ApplyIn(BaseModel):
    """Set the recording mode of many cameras: listed ones, a group (optionally with its sub-groups), or both."""

    mode: CameraRecordingMode
    schedule_id: int | None = None  # required when mode = "schedule"
    camera_ids: list[int] = Field(default_factory=list, max_length=10000)
    group_id: int | None = None
    include_subgroups: bool = True

    @model_validator(mode="after")
    def check(self):
        if (self.mode == "schedule") != (self.schedule_id is not None):
            raise ValueError("schedule_id is required with mode 'schedule', and only then")
        if not self.camera_ids and self.group_id is None:
            raise ValueError("give camera_ids or group_id")
        return self


class ApplyOut(BaseModel):
    updated: int


class PreviewSpan(BaseModel):
    start: datetime
    end: datetime
    mode: Literal["continuous", "event", "off"]


class PreviewOut(BaseModel):
    timezone: str
    spans: list[PreviewSpan]


class SiteTimeOut(BaseModel):
    timezone: str  # SITE_TIMEZONE, or this PC's offset such as "+05:30"
    now: datetime  # site wall clock with offset
