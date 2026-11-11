"""AccessStore: which cameras each role and user may see (port of nvr_client/src/features/access/AccessPage.tsx).

What a user may *do* comes from their role's permission numbers on the Auth Server; this page only decides *which
cameras*: all cameras, camera groups (with every sub-group) and single cameras. A user sees the union of their own
grants and their roles' grants; the Admin role sees everything without grants.
"""

from __future__ import annotations

from PySide6.QtCore import Property, Signal, Slot

from app.core.auth.permissions import Perm, summary_text
from app.core.context import AppContext
from app.core.store import BaseStore

ADMIN_ROLE = "Admin"


class AccessStore(BaseStore):
    subjectsChanged = Signal()
    grantsChanged = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self._roles: list[dict] = []
        self._users: list[dict] = []
        self._summary: dict[str, dict] = {}
        self._selected: dict = {}
        self._grants: dict | None = None
        self._grants_loading = False
        self._grants_error = ""
        self._saving = False
        self._revision = 0  # bumped on every grants load: the editor starts again from what the server has
        ctx.centralChanged.connect(self._reset)

    def _reset(self) -> None:
        self._roles, self._users, self._summary = [], [], {}
        self._selected, self._grants = {}, None
        self._set_loading(True)
        self.subjectsChanged.emit()
        self.grantsChanged.emit()

    # ------------------------------------------------------------------ subjects + summary
    @Slot()
    def refresh(self) -> None:
        if not self.allowed(Perm.ACCESS_MANAGE):
            return
        self.fetch("subjects", self.api.access_subjects, self._apply_subjects)
        self.fetch("summary", self.api.access_summary, self._apply_summary, track_error=False)

    def _apply_subjects(self, data: dict) -> None:
        self._roles = [{"name": r, "summary": ""} for r in data.get("roles") or []]
        self._users = list(data.get("users") or [])
        self._decorate()

    def _apply_summary(self, rows: list[dict]) -> None:
        self._summary = {f"{r['subject_type']}:{r['subject']}": r for r in rows or []}
        self._decorate()

    def _decorate(self) -> None:
        for role in self._roles:
            role["summary"] = summary_text(self._summary.get(f"role:{role['name']}"), role["name"] == ADMIN_ROLE)
        for user in self._users:
            user["summary"] = summary_text(self._summary.get(f"user:{user['id']}"))
            roles = ", ".join(user.get("roles") or []) or "no role"
            user["sub"] = f"{user.get('username', '')} · {roles}" + ("" if user.get("is_active", True) else " · inactive")
        self.subjectsChanged.emit()

    # ------------------------------------------------------------------ one subject
    @Slot(str, str, str)
    def select(self, subject_type: str, subject: str, label: str) -> None:
        roles = []
        if subject_type == "user":
            roles = next((u.get("roles") or [] for u in self._users if str(u.get("id")) == subject), [])
        self._selected = {"type": subject_type, "name": subject, "label": label, "roles": roles,
                          "isAdminRole": subject_type == "role" and subject == ADMIN_ROLE}
        self._grants, self._grants_error, self._grants_loading = None, "", True
        self.grantsChanged.emit()

        def ok(grants: dict) -> None:
            if self._selected.get("type") == subject_type and self._selected.get("name") == subject:
                self._set_grants(grants)

        def err(exc: Exception) -> None:
            if self._selected.get("name") == subject:
                self._grants_loading, self._grants_error = False, str(exc)
                self.grantsChanged.emit()

        self.fetch(f"grants-{subject_type}-{subject}", lambda: self.api.access_grants(subject_type, subject), ok,
                   track_error=False, on_err=err)

    def _set_grants(self, grants: dict) -> None:
        self._grants, self._grants_loading, self._grants_error = grants, False, ""
        self._revision += 1
        self.grantsChanged.emit()

    @Slot(bool, "QVariantList", "QVariantList")
    def save(self, all_cameras: bool, group_ids, camera_ids) -> None:
        if not self._selected or self._saving:
            return
        subject_type, subject = self._selected["type"], self._selected["name"]
        body = {"subject_type": subject_type, "subject": subject, "all_cameras": bool(all_cameras),
                "group_ids": [int(g) for g in group_ids or []], "camera_ids": [int(c) for c in camera_ids or []]}
        self._saving = True
        self.grantsChanged.emit()

        def done(grants: dict) -> None:
            self._saving = False
            if self._selected.get("name") == subject:
                self._set_grants(grants)
            self.fetch("summary", self.api.access_summary, self._apply_summary, track_error=False)

        def failed(_exc: Exception) -> None:
            self._saving = False
            self.grantsChanged.emit()

        self.act(lambda: self.api.put_access_grants(body), "Access saved", done, failed)

    roles = Property("QVariantList", lambda self: self._roles, notify=subjectsChanged)
    users = Property("QVariantList", lambda self: self._users, notify=subjectsChanged)
    selected = Property("QVariantMap", lambda self: self._selected, notify=grantsChanged)
    grants = Property("QVariant", lambda self: self._grants, notify=grantsChanged)
    grantsLoading = Property(bool, lambda self: self._grants_loading, notify=grantsChanged)
    grantsError = Property(str, lambda self: self._grants_error, notify=grantsChanged)
    saving = Property(bool, lambda self: self._saving, notify=grantsChanged)
    revision = Property(int, lambda self: self._revision, notify=grantsChanged)
