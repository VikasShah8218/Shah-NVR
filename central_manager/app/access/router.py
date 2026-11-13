"""Camera access grants for roles and users (docs/AUTH_INTEGRATION_PLAN.md §6). Needs permission 30.

Subjects come from the active Auth Server (app/auth/provider.py). A grant's `subject` is the key that server
uses: a role name / user id on legacy, a role id / user sub (UUIDs) on oidc; `label` is what to show.
Grants of the other server are kept but ignored (they belong to `auth_source`).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from tortoise.transactions import in_transaction

from app.access.models import AccessGrant
from app.auth.provider import REMOVED_ROLE, active_source, get_provider
from app.cameras.models import Camera
from app.groups.models import CameraGroup
from app.groups.services import group_labels

router = APIRouter(prefix="/api/v1/access", tags=["Access"])

SubjectType = Literal["role", "user"]
MAX_ITEMS = 500


class SubjectRole(BaseModel):
    key: str  # what grants store for this role
    name: str
    description: str | None = None
    removed: bool = False  # has grants here but no longer exists on the Auth Server


class SubjectUser(BaseModel):
    key: str  # what grants store for this user
    username: str
    display_name: str
    roles: list[str]
    is_active: bool


class SubjectsOut(BaseModel):
    roles: list[SubjectRole]  # roles of the app on the Auth Server, plus roles that already have grants
    users: list[SubjectUser]


class GrantRef(BaseModel):
    id: int
    name: str


class GrantSummary(BaseModel):
    subject_type: SubjectType
    subject: str
    label: str
    all_cameras: bool
    groups: int
    cameras: int


class GrantsOut(BaseModel):
    subject_type: SubjectType
    subject: str
    label: str
    all_cameras: bool
    groups: list[GrantRef]  # name = full path, e.g. "Anantnag › Bijbehara"
    cameras: list[GrantRef]


class GrantsIn(BaseModel):
    subject_type: SubjectType
    subject: str = Field(min_length=1, max_length=128)
    all_cameras: bool = False
    group_ids: list[int] = Field(default_factory=list, max_length=MAX_ITEMS)
    camera_ids: list[int] = Field(default_factory=list, max_length=MAX_ITEMS)


def _grants():
    return AccessGrant.filter(auth_source=active_source())


async def _labels(subject_type: str, keys: list[str]) -> dict[str, str]:
    provider = get_provider()
    if provider is None:  # auth off: nothing to resolve against
        return {k: k for k in keys}
    return await provider.labels(subject_type, keys)


@router.get("/subjects", response_model=SubjectsOut, summary="Roles and users that grants can be given to")
async def subjects():
    provider = get_provider()
    roles, users = await provider.subjects() if provider else ([], [])
    out = [SubjectRole(key=r.key, name=r.name, description=r.description) for r in roles]
    known = {r.key for r in roles}
    # order by the selected column: with Meta.ordering (id) PostgreSQL refuses DISTINCT ("ORDER BY expressions must
    # appear in select list"); SQLite allows it, so the tests did not catch it
    granted = await _grants().filter(subject_type="role").order_by("subject").distinct().values_list("subject", flat=True)
    extra = [k for k in granted if k not in known]
    labels = await _labels("role", extra)
    out += [SubjectRole(key=k, name=labels.get(k, k), removed=labels.get(k) == REMOVED_ROLE)
            for k in extra]
    return SubjectsOut(
        roles=sorted(out, key=lambda r: r.name.lower()),
        users=[SubjectUser(key=u.key, username=u.username, display_name=u.display_name, roles=list(u.roles),
                           is_active=u.is_active) for u in users],
    )


async def _detail(subject_type: str, subject: str) -> GrantsOut:
    grants = await _grants().filter(subject_type=subject_type, subject=subject).prefetch_related("camera")
    group_ids = [g.group_id for g in grants if g.group_id is not None]
    labels = await group_labels(group_ids)
    label = (await _labels(subject_type, [subject])).get(subject, subject)
    return GrantsOut(
        subject_type=subject_type, subject=subject, label=label, all_cameras=any(g.all_cameras for g in grants),  # type: ignore[arg-type]
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
    for g in await _grants():
        key = (g.subject_type, g.subject)
        row = summary.setdefault(key, GrantSummary(subject_type=g.subject_type, subject=g.subject,  # type: ignore[arg-type]
                                                   label=g.subject, all_cameras=False, groups=0, cameras=0))
        row.all_cameras |= g.all_cameras
        row.groups += g.group_id is not None
        row.cameras += g.camera_id is not None
    for subject_type in ("role", "user"):
        keys = [k for t, k in summary if t == subject_type]
        for k, label in (await _labels(subject_type, keys)).items():
            summary[(subject_type, k)].label = label
    return sorted(summary.values(), key=lambda r: (r.subject_type, r.label.lower()))


@router.put("/grants", response_model=GrantsOut, summary="Replace the grants of one role / user")
async def put_grants(body: GrantsIn):
    group_ids, camera_ids = sorted(set(body.group_ids)), sorted(set(body.camera_ids))
    if group_ids and await CameraGroup.filter(id__in=group_ids).count() != len(group_ids):
        raise HTTPException(422, "Some groups do not exist")
    if camera_ids and await Camera.filter(id__in=camera_ids).count() != len(camera_ids):
        raise HTTPException(422, "Some cameras do not exist")
    source = active_source()
    common = {"subject_type": body.subject_type, "subject": body.subject, "auth_source": source}
    async with in_transaction():
        await AccessGrant.filter(**common).delete()
        rows = [AccessGrant(**common, group_id=g) for g in group_ids]
        rows += [AccessGrant(**common, camera_id=c) for c in camera_ids]
        if body.all_cameras:
            rows.append(AccessGrant(**common, all_cameras=True))
        if rows:
            await AccessGrant.bulk_create(rows)
    return await _detail(body.subject_type, body.subject)
