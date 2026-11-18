from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.bookmarks.schemas import _utc

# Types made by people / other systems through the API. Node-made types (video_loss, motion...) come in on the
# internal API.
UserEventType = Literal["manual", "api"]


class EventCreate(BaseModel):
    """Mark an event on a camera. Default: a moment, now. `ongoing` starts an event that is ended later
    (POST /events/{id}/end, or automatically after EVENT_MAX_SECONDS)."""

    type: UserEventType = "manual"
    label: str | None = Field(default=None, max_length=128)
    data: dict[str, Any] | None = None
    start_time: datetime | None = Field(default=None, description="Default: now")
    duration_seconds: float = Field(default=0, ge=0, le=3600, description="0 = a moment")
    ongoing: bool = False

    @field_validator("start_time")
    @classmethod
    def _utc_time(cls, v: datetime | None) -> datetime | None:
        return _utc(v)

    @field_validator("label")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v else None

    @model_validator(mode="after")
    def _check(self):
        if self.ongoing and self.duration_seconds:
            raise ValueError("give duration_seconds or ongoing, not both")
        return self


class EventOut(BaseModel):
    id: int
    camera_id: int
    camera_name: str
    type: str
    source: str
    start_time: datetime
    end_time: datetime | None  # None = still going on; == start_time = a moment
    label: str | None
    data: dict[str, Any] | None
    pre_seconds: int  # the camera's pre / post event seconds (playback starts at start - pre)
    post_seconds: int
    merged: bool = False  # create only: the mark extended a recent event of the same type
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- node <-> central (internal API)


class NodeEventIn(BaseModel):
    key: str = Field(min_length=1, max_length=96)  # the node's own id for the event (idempotent upload)
    camera_id: int
    type: str = Field(pattern=r"^[a-z0-9_.:-]{1,32}$")
    start_time: datetime
    end_time: datetime | None = None
    label: str | None = Field(default=None, max_length=128)
    data: dict[str, Any] | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def _utc_times(cls, v: datetime | None) -> datetime | None:
        return _utc(v)


class NodeEventsIn(BaseModel):
    items: list[NodeEventIn] = Field(max_length=500)


class NodeEventsOut(BaseModel):
    ids: dict[str, int]  # node key -> central event id (events of cameras the node no longer owns are left out)


class EventWindow(BaseModel):
    """What a node needs to keep video for an event: central -> node push and the node's catch-up."""

    id: int
    camera_id: int
    type: str
    start_time: datetime
    end_time: datetime | None
    updated_at: datetime


class EventWindowsOut(BaseModel):
    items: list[EventWindow]
    now: datetime  # central's clock: pass back as `since` next time
