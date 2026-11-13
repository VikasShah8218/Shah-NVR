"""Audit log writes and retention (docs/AUTH_INTEGRATION_PLAN.md §7.7)."""

from __future__ import annotations

import logging
from datetime import timedelta

from app.audit.models import AuditEvent
from app.auth.principal import Principal
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("central.audit")


async def record(principal: Principal | None, action: str, *, method: str | None = None, path: str = "",
                 camera_id: int | None = None, status: str = "ok", detail: dict | None = None,
                 ip: str | None = None) -> None:
    """Never let an audit failure break the request it describes."""
    try:
        await AuditEvent.create(
            user_id=(principal.user_id or None) if principal and not principal.local else None,
            auth_source=(principal.source or None) if principal else None,
            username=(principal.username if principal else "anonymous")[:128], action=action[:64], method=method,
            path=path[:512], camera_id=camera_id, status=status, detail=detail, ip=(ip or "")[:64] or None,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Audit write failed for %s", action)


async def prune_audit() -> int:
    cutoff = utcnow() - timedelta(days=settings.AUDIT_RETENTION_DAYS)
    removed = await AuditEvent.filter(at__lt=cutoff).delete()
    if removed:
        logger.info("Audit: removed %d events older than %d days", removed, settings.AUDIT_RETENTION_DAYS)
    return removed
