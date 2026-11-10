from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator, model_validator

_COLOR = r"^#[0-9a-fA-F]{6}$"
_PROFILE = r"^[a-z0-9_-]{1,32}$"


def _utc(value: datetime | None) -> datetime | None:
    """Naive datetimes are UTC (same rule as the recordings API)."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class BookmarkCreate(BaseModel):
    camera_id: int
    profile: str | None = Field(default=None, pattern=_PROFILE)
    start_time: datetime
    end_time: datetime | None = None
    note: str = Field(min_length=1, max_length=4000)
    label: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, pattern=_COLOR)
    author: str | None = Field(default=None, max_length=128)

    @field_validator("start_time", "end_time")
    @classmethod
    def _utc_times(cls, v: datetime | None) -> datetime | None:
        return _utc(v)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("note must not be blank")
        return v

    @model_validator(mode="after")
    def _range(self):
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class BookmarkUpdate(BaseModel):
    """Only the fields sent are changed. Send end_time=null to turn a range into a point."""

    profile: str | None = Field(default=None, pattern=_PROFILE)
    start_time: datetime | None = None
    end_time: datetime | None = None
    note: str | None = Field(default=None, min_length=1, max_length=4000)
    label: str | None = Field(default=None, max_length=64)
    color: str | None = Field(default=None, pattern=_COLOR)
    author: str | None = Field(default=None, max_length=128)

    @field_validator("start_time", "end_time")
    @classmethod
    def _utc_times(cls, v: datetime | None) -> datetime | None:
        return _utc(v)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("note must not be blank")
        return v


class BookmarkOut(BaseModel):
    id: int
    camera_id: int
    camera_name: str
    profile: str | None
    start_time: datetime
    end_time: datetime | None
    note: str
    label: str | None
    color: str | None
    author: str | None
    created_at: datetime
    updated_at: datetime
