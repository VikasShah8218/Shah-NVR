"""The new Auth Server (AUTH_PROVIDER=oidc) through auth_sdk (docs/AUTH_V2_PLAN.md).

The SDK does the hard part: ES256 signature with cached JWKS, issuer / audience / expiry, revocations from the
signed event stream (user disabled, session ended, access changed, client or key revoked) and the permission map.
This module only turns its Principal into ours and keeps a small directory for names and the Access page:

* members (sub -> username, name, roles, active) and roles (id, name): from GET /v1/apps/SNVR/members and /roles
  (scope users.read), reloaded when the SDK reports a change (debounced). Kept in memory only (personal data).
* roles name -> id: also saved next to the SDK state file (no personal data), so role-based camera grants keep
  working when central restarts while the Auth Server is down.

Clients sign in on the Auth Server's own page (Authorization Code + PKCE) and send its access token here; central
never sees a password and has no /login or /refresh of its own in this mode.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from collections import OrderedDict
from pathlib import Path

from auth_sdk import AuthError as SdkAuthError
from auth_sdk import AuthSDK, MissingScope, StaleAuthState

from app.auth.permissions import perms_from_codes
from app.auth.principal import ADMIN_ROLE, Principal
from app.auth.provider import OIDC, REMOVED_ROLE, UNKNOWN_USER, RoleItem, UserItem
from app.auth.verify import AuthError
from settings.settings import settings

logger = logging.getLogger("central.auth")

DEBOUNCE_SECONDS = 1.0
RETRY_MIN, RETRY_MAX = 2.0, 300.0
SEEN_SESSIONS = 5000  # sign-in sessions remembered for the "auth.session" audit event


def _unverified_claims(token: str) -> dict:
    """Only to choose an error code after the SDK refused the token. Never trusted for access."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError, UnicodeDecodeError):
        return {}


def _display_name(member: dict) -> str:
    full = " ".join(p for p in (member.get("given_name"), member.get("family_name")) if p)
    return full or str(member.get("username") or "")


class OidcProvider:
    name = OIDC

    def __init__(self, sdk: AuthSDK, roles_path: str | None = None):
        self.sdk = sdk
        self.roles_path = roles_path
        self.members: dict[str, dict] = {}
        self.roles: list[RoleItem] = []
        self.role_ids: dict[str, str] = {}  # name -> id
        self.directory_loaded = False
        self.directory_error: str | None = None
        self._wanted = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._sessions: OrderedDict[str, None] = OrderedDict()
        self._load_roles()
        sdk.on_change(self._on_change)

    @classmethod
    def from_settings(cls) -> "OidcProvider":
        if not settings.AUTH_OIDC_CLIENT_SECRET:
            raise RuntimeError("AUTH_PROVIDER=oidc but AUTH_OIDC_CLIENT_SECRET is empty: set the snvr-a secret in .env")
        state_path = settings.AUTH_STATE_PATH or None
        if state_path:
            Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        sdk = AuthSDK(
            issuer=settings.AUTH_ISSUER, app_key=settings.AUTH_APP_KEY, client_id=settings.AUTH_OIDC_CLIENT_ID,
            client_secret=settings.AUTH_OIDC_CLIENT_SECRET, instance_id=settings.AUTH_INSTANCE_ID or None,
            state_path=state_path, max_staleness_seconds=settings.AUTH_MAX_STALENESS_SECONDS or None,
            api_url=settings.AUTH_API_URL or None, leeway_seconds=settings.AUTH_LEEWAY_SECONDS,
        )
        roles_path = str(Path(state_path).with_name("auth-roles.json")) if state_path else None
        return cls(sdk, roles_path)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        await self.sdk.start()
        self._wanted.set()  # first directory load
        self._task = asyncio.create_task(self._run_directory(), name="auth-directory")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        await self.sdk.stop()

    def health(self) -> dict:
        return {**self.sdk.health(), "members": len(self.members), "roles": len(self.roles),
                "directory_loaded": self.directory_loaded, "directory_error": self.directory_error}

    def client_config(self) -> dict:
        return {"issuer": settings.AUTH_ISSUER.rstrip("/"), "web_client_id": settings.AUTH_WEB_CLIENT_ID,
                "desktop_client_id": settings.AUTH_DESKTOP_CLIENT_ID, "scopes": settings.AUTH_CLIENT_SCOPES}

    # ------------------------------------------------------------------ verification
    async def verify(self, token: str) -> Principal:
        try:
            p = await self.sdk.verify(token)
        except StaleAuthState as exc:
            raise AuthError(503, "Authentication is syncing, try again in a moment", "auth_syncing") from exc
        except SdkAuthError as exc:
            raise self._refusal(token, str(exc)) from exc
        member = self.members.get(p.sub)
        if member is None and self.directory_loaded:
            self._wanted.set()  # probably just given access: reload the names in the background
        roles = tuple(p.roles)
        is_admin = bool(p.mask & 1) or ADMIN_ROLE in roles  # bit 0 = "*"
        return Principal(
            user_id=p.sub, username=str(member["username"]) if member else p.sub, roles=roles,
            perms=perms_from_codes(p.has_perm), is_admin=is_admin,
            display_name=_display_name(member) if member else "", source=OIDC, sid=p.sid,
            role_keys=tuple(self.role_ids[r] for r in roles if r in self.role_ids),
        )

    def _refusal(self, token: str, message: str) -> AuthError:
        claims = _unverified_claims(token)
        exp = claims.get("exp")
        if isinstance(exp, int) and exp + settings.AUTH_LEEWAY_SECONDS <= time.time():
            return AuthError(401, "Session expired", "token_expired")
        if "revoked" in message.lower():
            return AuthError(401, "Session ended, please sign in again", "token_revoked")
        if claims and claims.get("aud") not in (None, self.sdk.app_key):
            return AuthError(401, "Token is not for this application", "wrong_app")
        return AuthError(401, "Invalid token", "invalid_token")

    def new_session(self, principal: Principal) -> bool:
        if not principal.sid or principal.sid in self._sessions:
            return False
        self._sessions[principal.sid] = None
        while len(self._sessions) > SEEN_SESSIONS:
            self._sessions.popitem(last=False)
        return True

    # ------------------------------------------------------------------ directory (members + roles)
    def _on_change(self, event_type: str, payload: dict) -> None:
        self._wanted.set()

    async def _run_directory(self) -> None:
        delay = RETRY_MIN
        while True:
            await self._wanted.wait()
            await asyncio.sleep(DEBOUNCE_SECONDS)  # changes arrive in bursts: one reload for all of them
            self._wanted.clear()
            try:
                await self.reload_directory()
                delay = RETRY_MIN
            except asyncio.CancelledError:
                raise
            except MissingScope as exc:
                self.directory_error = str(exc)
                logger.error("Auth directory: %s", exc)
                await asyncio.sleep(RETRY_MAX)
                self._wanted.set()
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                self.directory_error = str(exc) or type(exc).__name__
                logger.warning("Auth directory reload failed (%s); retrying in %.0f s", self.directory_error, delay)
                await asyncio.sleep(delay)
                delay = min(RETRY_MAX, delay * 2)
                self._wanted.set()

    async def reload_directory(self) -> None:
        roles = await self.sdk.roles()
        members = await self.sdk.list_all_members()
        self.set_directory(roles, members)

    def set_directory(self, roles: list[dict], members: list[dict]) -> None:
        self.roles = [RoleItem(key=str(r["id"]), name=str(r["name"]), description=r.get("description"))
                      for r in sorted(roles, key=lambda r: str(r["name"]).lower())]
        self.role_ids = {r.name: r.key for r in self.roles}
        self.members = {str(m["sub"]): m for m in members}
        self.directory_loaded, self.directory_error = True, None
        self._save_roles()
        logger.info("Auth directory: %d members, %d roles", len(self.members), len(self.roles))

    def _load_roles(self) -> None:
        if not self.roles_path or not os.path.exists(self.roles_path):
            return
        try:
            with open(self.roles_path, encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("issuer") != self.sdk.issuer or saved.get("app_key") != self.sdk.app_key:
                return
            self.roles = [RoleItem(key=r["key"], name=r["name"], description=r.get("description"))
                          for r in saved.get("roles", [])]
            self.role_ids = {r.name: r.key for r in self.roles}
        except (OSError, ValueError, TypeError, KeyError) as exc:
            logger.warning("Ignoring unreadable %s: %s", self.roles_path, exc)

    def _save_roles(self) -> None:
        if not self.roles_path:
            return
        data = {"issuer": self.sdk.issuer, "app_key": self.sdk.app_key,
                "roles": [{"key": r.key, "name": r.name, "description": r.description} for r in self.roles]}
        tmp = f"{self.roles_path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.roles_path)
        except OSError as exc:
            logger.warning("Could not save %s: %s", self.roles_path, exc)

    async def subjects(self) -> tuple[list[RoleItem], list[UserItem]]:
        users = [UserItem(key=sub, username=str(m.get("username") or sub), display_name=_display_name(m),
                          roles=tuple(str(r["name"]) for r in m.get("roles") or []),
                          is_active=bool(m.get("is_active", True)))
                 for sub, m in self.members.items()]
        return list(self.roles), sorted(users, key=lambda u: u.username.lower())

    async def labels(self, subject_type: str, keys: list[str]) -> dict[str, str]:
        if subject_type == "role":
            names = {r.key: r.name for r in self.roles}
            return {k: names.get(k, REMOVED_ROLE) for k in keys}
        return {k: str(self.members[k].get("username")) if k in self.members else UNKNOWN_USER for k in keys}
