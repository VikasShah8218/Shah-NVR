"""Auth state store: token versions, the users snapshot and the service token (docs/AUTH_INTEGRATION_PLAN.md §4.1).

Everything that reads or writes auth state goes through `AuthStateStore`. `MemoryAuthStateStore` is the
implementation used now (one central process). A Redis implementation can be added later with the same methods
(keys `token_version:{id}`, `Users:{id}`, `auth:service-token:{app}`) and selected with AUTH_STATE_BACKEND=redis;
callers do not change.

Token versions only grow (logout, password and role changes bump them). Both writers - the SSE stream and the
users snapshot - keep the higher value, so a snapshot fetched just before an SSE bump cannot bring an older
version (and a revoked token) back.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class AuthUser:
    id: int
    username: str
    is_active: bool = True
    is_superuser: bool = False
    token_version: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        full = " ".join(p for p in (self.first_name, self.last_name) if p)
        return full or self.username


class AuthStateStore(Protocol):
    async def get_token_version(self, user_id: int) -> int | None: ...
    async def set_token_versions(self, versions: dict[int, int]) -> None: ...
    async def get_user(self, user_id: int) -> AuthUser | None: ...
    async def list_users(self) -> list[AuthUser]: ...
    async def replace_users(self, users: list[AuthUser]) -> None: ...
    async def get_service_token(self) -> str | None: ...
    async def set_service_token(self, token: str, expires_in: int) -> None: ...
    async def ready(self) -> bool: ...


@dataclass
class MemoryAuthStateStore:
    """In-process store. Correct for a single central process (each process would keep its own copy)."""

    _versions: dict[int, int] = field(default_factory=dict)
    _users: dict[int, AuthUser] = field(default_factory=dict)
    _service_token: tuple[str, float] | None = None  # (token, monotonic expiry)
    _ready: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_token_version(self, user_id: int) -> int | None:
        return self._versions.get(user_id)

    async def set_token_versions(self, versions: dict[int, int]) -> None:
        async with self._lock:
            for user_id, version in versions.items():
                self._versions[user_id] = max(version, self._versions.get(user_id, version))

    async def get_user(self, user_id: int) -> AuthUser | None:
        return self._users.get(user_id)

    async def list_users(self) -> list[AuthUser]:
        return sorted(self._users.values(), key=lambda u: u.username.lower())

    async def replace_users(self, users: list[AuthUser]) -> None:
        async with self._lock:
            self._users = {u.id: u for u in users}
            # users no longer in the application are forgotten (their tokens stop working)
            self._versions = {uid: v for uid, v in self._versions.items() if uid in self._users}
            for u in users:
                if u.token_version is not None:
                    self._versions[u.id] = max(u.token_version, self._versions.get(u.id, u.token_version))
            self._ready = True

    async def get_service_token(self) -> str | None:
        if self._service_token is None:
            return None
        token, expires = self._service_token
        return token if time.monotonic() < expires else None

    async def set_service_token(self, token: str, expires_in: int) -> None:
        self._service_token = (token, time.monotonic() + expires_in)

    async def ready(self) -> bool:
        return self._ready


def create_store(backend: str) -> AuthStateStore:
    if backend == "memory":
        return MemoryAuthStateStore()
    raise ValueError(f"AUTH_STATE_BACKEND={backend!r} is not available (supported: memory)")
