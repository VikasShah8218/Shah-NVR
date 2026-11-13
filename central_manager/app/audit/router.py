"""Audit log, newest first (docs/AUTH_INTEGRATION_PLAN.md §7.7). Needs permission 31."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.audit.models import AuditEvent
from utilities.pagination import Page, PageParams, paginate

router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


class AuditOut(BaseModel):
    id: int
    at: datetime
    user_id: str | None
    auth_source: str | None
    username: str
    action: str
    method: str | None
    path: str
    camera_id: int | None
    status: str
    detail: dict | None
    ip: str | None


@router.get("", response_model=Page[AuditOut], summary="Audit events, newest first (paged)")
async def list_audit(
    page: PageParams = Depends(),
    username: str | None = Query(default=None, max_length=128),
    action: str | None = Query(default=None, max_length=64, description="Prefix, e.g. 'auth' or 'live.open'"),
    camera_id: int | None = None,
    status: str | None = Query(default=None, pattern="^(ok|denied|failed)$"),
    start: datetime | None = None,
    end: datetime | None = None,
):
    qs = AuditEvent.all()
    if username:
        qs = qs.filter(username__icontains=username.strip())
    if action:
        qs = qs.filter(action__startswith=action.strip())
    if camera_id is not None:
        qs = qs.filter(camera_id=camera_id)
    if status:
        qs = qs.filter(status=status)
    if start:
        qs = qs.filter(at__gte=start)
    if end:
        qs = qs.filter(at__lt=end)
    qs = qs.order_by("-at", "-id")
    return await paginate(qs, page, lambda rows: [AuditOut.model_validate(r, from_attributes=True) for r in rows])
