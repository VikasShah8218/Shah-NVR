"""AuditStore: the audit log, newest first, one page at a time (port of nvr_client/src/features/audit/AuditPage.tsx).

Sign-ins (also failed ones), live and playback opens, export downloads, every change and every refused request.
Filters: user, action (prefix, e.g. "cameras" or "auth.login"), result and a time range.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Property, Signal, Slot

from app.core.auth.permissions import Perm
from app.core.context import AppContext
from app.core.paged_store import PagedStore

AUDIT_ROLES = ["id", "at", "user_id", "username", "action", "method", "path", "camera_id", "status", "detail",
               "ip", "detailText"]
RANGES = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "all": None}
STATUSES = ("", "ok", "denied", "failed")


def detail_text(detail) -> str:
    if not detail:
        return ""
    if isinstance(detail, dict):
        return ", ".join(f"{k}: {v}" for k, v in detail.items())
    return str(detail)


class AuditStore(PagedStore):
    PERMS = (Perm.AUDIT_VIEW,)
    filtersChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, AUDIT_ROLES, page_size=50, parent=parent)
        self._username = ""
        self._action = ""
        self._status = ""
        self._range = "7d"
        ctx.centralChanged.connect(self._clear)

    def _clear(self) -> None:
        """Another user or server: drop the rows of the previous one (the page reloads when opened)."""
        self._page = 1
        self._apply([], 0)

    def _load(self, limit: int, offset: int):
        span = RANGES.get(self._range)
        start = datetime.now(timezone.utc) - span if span else None
        rows, total = self.api.audit(username=self._username, action=self._action, status=self._status or None,
                                     start=start, limit=limit, offset=offset)
        for row in rows:
            row["detailText"] = detail_text(row.get("detail"))
        return rows, total

    def _set(self, attr: str, value: str) -> None:
        if getattr(self, attr) != value:
            setattr(self, attr, value)
            self.filtersChanged.emit()
            self.reset()

    @Slot(str)
    def setUsername(self, value: str) -> None:
        self._set("_username", value.strip())

    @Slot(str)
    def setAction(self, value: str) -> None:
        self._set("_action", value.strip())

    @Slot(str)
    def setStatus(self, value: str) -> None:
        if value in STATUSES:
            self._set("_status", value)

    @Slot(str)
    def setRange(self, value: str) -> None:
        if value in RANGES:
            self._set("_range", value)

    username = Property(str, lambda self: self._username, notify=filtersChanged)
    action = Property(str, lambda self: self._action, notify=filtersChanged)
    status = Property(str, lambda self: self._status, notify=filtersChanged)
    timeRange = Property(str, lambda self: self._range, notify=filtersChanged)
