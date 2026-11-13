"""Which Auth Server verifies tokens (docs/AUTH_V2_PLAN.md). Chosen by AUTH_PROVIDER, read once at startup.

Everything outside app/auth talks to the provider through this small interface, never to a specific server:
the request guard (verify), the Access page (subjects, labels), /auth/config (client_config) and /auth/status.

* `LegacyProvider`: the old Authentication-Server (integration.py + verify.py + state.py, unchanged).
* `OidcProvider` (oidc.py): the new Auth Server through auth_sdk. Imported only when selected, so a server on
  legacy runs without the SDK installed.

Grants and audit rows remember which provider they came from (`auth_source`), because user ids and role keys
of the two servers never match: "12" / "Viewer" on legacy, a UUID / a role UUID on oidc.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.auth.integration import AuthRuntime, create_runtime
from app.auth.principal import Principal
from settings.settings import settings

LEGACY, OIDC = "legacy", "oidc"
PROVIDERS = (LEGACY, OIDC)
REMOVED_ROLE = "(role removed)"
UNKNOWN_USER = "(unknown user)"


@dataclass(frozen=True)
class RoleItem:
    key: str  # what grants store: the name (legacy) or the role id (oidc)
    name: str
    description: str | None = None


@dataclass(frozen=True)
class UserItem:
    key: str  # what grants store: the user id as text (legacy) or `sub` (oidc)
    username: str
    display_name: str
    roles: tuple[str, ...]  # role names
    is_active: bool


class AuthProvider(Protocol):
    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def verify(self, token: str) -> Principal: ...  # raises verify.AuthError
    def new_session(self, principal: Principal) -> bool: ...  # first request of a sign-in seen here
    async def subjects(self) -> tuple[list[RoleItem], list[UserItem]]: ...
    async def labels(self, subject_type: str, keys: list[str]) -> dict[str, str]: ...
    def client_config(self) -> dict: ...
    def health(self) -> dict: ...


class LegacyProvider:
    """The old Authentication-Server, exactly as before (only wrapped)."""

    name = LEGACY

    def __init__(self, runtime: AuthRuntime):
        self.runtime = runtime

    async def start(self) -> None:
        from app.auth.verify import check_signing_key

        check_signing_key()
        self.runtime.start()

    async def stop(self) -> None:
        await self.runtime.stop()

    async def verify(self, token: str) -> Principal:
        from app.auth.verify import verify_access_token

        return await verify_access_token(token, self.runtime)

    def new_session(self, principal: Principal) -> bool:
        return False  # sign-ins go through central's /login, which writes auth.login itself

    async def subjects(self) -> tuple[list[RoleItem], list[UserItem]]:
        users = await self.runtime.store.list_users()
        roles = sorted({r for u in users for r in u.roles}, key=str.lower)
        return ([RoleItem(key=r, name=r) for r in roles],
                [UserItem(key=str(u.id), username=u.username, display_name=u.display_name, roles=u.roles,
                          is_active=u.is_active) for u in users])

    async def labels(self, subject_type: str, keys: list[str]) -> dict[str, str]:
        if subject_type == "role":
            return {k: k for k in keys}
        users = {str(u.id): u for u in await self.runtime.store.list_users()}
        return {k: users[k].username if k in users else f"user {k}" for k in keys}

    def client_config(self) -> dict:
        return {}

    def health(self) -> dict:
        return {"tasks": len(self.runtime.tasks)}


_provider: AuthProvider | None = None


def get_provider() -> AuthProvider | None:
    return _provider


def set_provider(provider: AuthProvider | None) -> None:
    global _provider
    _provider = provider


def active_source() -> str:
    """The provider name grants and audit rows are written under (also when auth is off)."""
    return settings.AUTH_PROVIDER


def check_provider_setting() -> None:
    if settings.AUTH_PROVIDER not in PROVIDERS:
        raise RuntimeError(f"AUTH_PROVIDER={settings.AUTH_PROVIDER!r}: use one of {', '.join(PROVIDERS)}")


def create_provider() -> AuthProvider:
    check_provider_setting()
    if settings.AUTH_PROVIDER == OIDC:
        from app.auth.oidc import OidcProvider

        return OidcProvider.from_settings()
    return LegacyProvider(create_runtime())
