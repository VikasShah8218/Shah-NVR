"""The caller of a request: an Auth Server user (auth on) or the built-in local admin (auth off)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

from app.auth.permissions import Perm

ADMIN_ROLE = "Admin"


@dataclass
class Principal:
    # Text, because the two Auth Servers differ: the old one numbers users ("12"), the new one uses UUIDs.
    user_id: str
    username: str
    roles: tuple[str, ...] = ()  # role names (display, Admin check)
    perms: frozenset[int] = frozenset()
    is_admin: bool = False  # "*" in the token (or the Admin role): every permission, every camera
    display_name: str = ""
    local: bool = False  # auth is off: built-in local admin
    source: str = ""  # which Auth Server verified it: "legacy" | "oidc" ("" = local / anonymous)
    sid: str = ""  # sign-in session (oidc only)
    # what role grants are stored under: role names (legacy) or role ids that survive renames (oidc)
    role_keys: tuple[str, ...] = ()
    # per-request cache of the camera scope (app/auth/scope.py)
    scope_cache: dict = field(default_factory=dict, repr=False, compare=False)

    def has(self, perm: int) -> bool:
        return self.is_admin or int(perm) in self.perms

    def permission_list(self) -> list[int]:
        return sorted(p.value for p in Perm) if self.is_admin else sorted(self.perms)


def local_admin() -> Principal:
    return Principal(user_id="0", username="local", roles=(ADMIN_ROLE,), is_admin=True, display_name="Local admin",
                     local=True)


_current: ContextVar[Principal | None] = ContextVar("nvr_principal", default=None)


def set_current(principal: Principal) -> None:
    _current.set(principal)


def current() -> Principal:
    """The caller of the running request. Outside a request (background loops, tests) = local admin."""
    return _current.get() or local_admin()
