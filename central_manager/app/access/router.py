"""Camera access grants for roles and users (docs/AUTH_INTEGRATION_PLAN.md §6). Needs permission 30."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from tortoise.transactions import in_transaction

from app.access.models import AccessGrant
from app.auth.integration import get_runtime
from app.cameras.models import Camera
from app.groups.models import CameraGroup
from app.groups.services import group_labels

router = APIRouter(prefix="/api/v1/access", tags=["Access"])

SubjectType = Literal["role", "user"]
MAX_ITEMS = 500


class SubjectUser(BaseModel):
    id: int
    username: str
    display_name: str
    roles: list[str]
    is_active: bool


class SubjectsOut(BaseModel):
    roles: list[str]  # roles of SNVR users (from the Auth Server) and roles that already have grants
    users: list[SubjectUser]


class GrantRef(BaseModel):
    id: int
    name: str


class GrantSummary(BaseModel):
    subject_type: SubjectType
    subject: str
    all_cameras: bool
    groups: int
    cameras: int


class GrantsOut(BaseModel):
    subject_type: SubjectType
    subject: str
    all_cameras: bool
    groups: list[GrantRef]  # name = full path, e.g. "Anantnag › Bijbehara"
    cameras: list[GrantRef]


class GrantsIn(BaseModel):
    subject_type: SubjectType
    subject: str = Field(min_length=1, max_length=128)
    all_cameras: bool = False
    group_ids: list[int] = Field(default_factory=list, max_length=MAX_ITEMS)
    camera_ids: list[int] = Field(default_factory=list, max_length=MAX_ITEMS)


@router.get("/subjects", response_model=SubjectsOut, summary="Roles and users that grants can be given to")
async def subjects():
    runtime = get_runtime()
    users = await runtime.store.list_users() if runtime else []
    roles = {r for u in users for r in u.roles}
    roles.update(await AccessGrant.filter(subject_type="role").distinct().values_list("subject", flat=True))
    return SubjectsOut(
        roles=sorted(roles, key=str.lower),
        users=[SubjectUser(id=u.id, username=u.username, display_name=u.display_name, roles=list(u.roles),
                           is_active=u.is_active) for u in users],
    )


async def _detail(subject_type: str, subject: str) -> GrantsOut:
    grants = await AccessGrant.filter(subject_type=subject_type, subject=subject).prefetch_related("camera")
    group_ids = [g.group_id for g in grants if g.group_id is not None]
    labels = await group_labels(group_ids)
    return GrantsOut(
        subject_type=subject_type, subject=subject, all_cameras=any(g.all_cameras for g in grants),  # type: ignore[arg-type]
        groups=sorted((GrantRef(id=i, name=labels.get(i, f"#{i}")) for i in group_ids), key=lambda r: r.name.lower()),
        cameras=sorted((GrantRef(id=g.camera_id, name=g.camera.name) for g in grants if g.camera_id is not None),
                       key=lambda r: r.name.lower()),
    )


@router.get("/grants", response_model=GrantsOut | list[GrantSummary],
            summary="Grants of one role / user (with subject_type + subject), or a summary of all")
async def get_grants(subject_type: SubjectType | None = None, subject: str | None = Query(default=None, max_length=128)):
    if subject_type and subject:
        return await _detail(subject_type, subject)
    summary: dict[tuple[str, str], GrantSummary] = {}
    for g in await AccessGrant.all():
        key = (g.subject_type, g.subject)
        row = summary.setdefault(key, GrantSummary(subject_type=g.subject_type, subject=g.subject,  # type: ignore[arg-type]
                                                   all_cameras=False, groups=0, cameras=0))
        row.all_cameras |= g.all_cameras
        row.groups += g.group_id is not None
        row.cameras += g.camera_id is not None
    return sorted(summary.values(), key=lambda r: (r.subject_type, r.subject.lower()))


@router.put("/grants", response_model=GrantsOut, summary="Replace the grants of one role / user")
async def put_grants(body: GrantsIn):
    group_ids, camera_ids = sorted(set(body.group_ids)), sorted(set(body.camera_ids))
    if group_ids and await CameraGroup.filter(id__in=group_ids).count() != len(group_ids):
        raise HTTPException(422, "Some groups do not exist")
    if camera_ids and await Camera.filter(id__in=camera_ids).count() != len(camera_ids):
        raise HTTPException(422, "Some cameras do not exist")
    async with in_transaction():
        await AccessGrant.filter(subject_type=body.subject_type, subject=body.subject).delete()
        rows = [AccessGrant(subject_type=body.subject_type, subject=body.subject, group_id=g) for g in group_ids]
        rows += [AccessGrant(subject_type=body.subject_type, subject=body.subject, camera_id=c) for c in camera_ids]
        if body.all_cameras:
            rows.append(AccessGrant(subject_type=body.subject_type, subject=body.subject, all_cameras=True))
        if rows:
            await AccessGrant.bulk_create(rows)
    return await _detail(body.subject_type, body.subject)
