from datetime import datetime

from pydantic import BaseModel, Field, field_validator

MAX_ASSIGN = 500


def _clean_name(v: str | None) -> str | None:
    if v is None:
        return v
    v = " ".join(v.split())
    if not v:
        raise ValueError("name must not be empty")
    return v


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    parent_id: int | None = None  # None = top level

    _name = field_validator("name")(classmethod(lambda cls, v: _clean_name(v)))


class GroupUpdate(BaseModel):
    """Rename, describe or move. Send `parent_id: null` to move a group to the top level."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    parent_id: int | None = None

    _name = field_validator("name")(classmethod(lambda cls, v: _clean_name(v)))


class GroupRef(BaseModel):
    id: int
    name: str


class GroupOut(BaseModel):
    id: int
    name: str
    description: str | None
    parent_id: int | None
    depth: int
    path: str  # "/3/17/" ids from the top, ending with this group
    path_label: str  # "Anantnag › Bijbehara" names from the top, ending with this group
    sort_order: int
    child_groups: int  # direct sub-groups (the tree shows a chevron without loading them)
    cameras_direct: int  # cameras directly in this group
    cameras_total: int  # cameras in this group and every sub-group
    online_total: int  # of those: enabled and streaming / recording
    created_at: datetime
    updated_at: datetime


class GroupDetail(GroupOut):
    breadcrumb: list[GroupRef]  # ancestors from the top down (not the group itself)


class AssignIn(BaseModel):
    camera_ids: list[int] = Field(min_length=1, max_length=MAX_ASSIGN)
    group_id: int | None  # None = take the cameras out of every group


class AssignOut(BaseModel):
    updated: int
