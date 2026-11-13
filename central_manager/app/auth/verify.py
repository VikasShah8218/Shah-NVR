"""Verify an Auth Server access token and build the Principal (docs/AUTH_INTEGRATION_PLAN.md §4).

1. HS256 signature with AUTH_KEY (no other algorithm accepted), `exp` with a small leeway.
2. `type == "access"` and `app == AUTH_APP_KEY` (an AUTH or ANPR token must not open Shah-NVR).
3. Revocation: the token's `ver` must equal the user's current token version (SSE + users snapshot).
4. The user must be in the SNVR users snapshot and active.
Fail closed: while the auth state has not loaded yet -> 503; unknown version -> 401.
"""

from __future__ import annotations

import hashlib
import logging

import jwt

from app.auth.integration import AuthRuntime
from app.auth.permissions import parse_perms
from app.auth.principal import ADMIN_ROLE, Principal
from settings.settings import settings

logger = logging.getLogger("central.auth")

# SHA-256 of known development signing keys (the keys themselves never go into the code)
KNOWN_DEV_KEY_HASHES = {"fc9325d4b8a998519f7a3d7badea7059c849887d5432564ea7d0f46b59ce3d71"}


class AuthError(Exception):
    def __init__(self, status: int, detail: str, code: str = "unauthorized"):
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


def decode(token: str) -> dict:
    try:
        return jwt.decode(token, settings.AUTH_KEY, algorithms=["HS256"], leeway=settings.AUTH_LEEWAY_SECONDS,
                          options={"require": ["exp"]})
    except jwt.ExpiredSignatureError as exc:
        raise AuthError(401, "Session expired", "token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(401, "Invalid token", "invalid_token") from exc


async def verify_access_token(token: str, runtime: AuthRuntime) -> Principal:
    claims = decode(token)
    if claims.get("type") != "access":
        raise AuthError(401, "Not an access token", "invalid_token")
    if str(claims.get("app", "")).upper() != settings.AUTH_APP_KEY.upper():
        raise AuthError(401, "Token is not for this application", "wrong_app")
    try:
        user_id = int(claims["user_id"])
        version = int(claims["ver"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError(401, "Invalid token", "invalid_token") from exc

    store = runtime.store
    if not await store.ready():
        if settings.AUTH_FAIL_MODE == "open":
            logger.warning("Auth state not loaded yet: allowing user %s (AUTH_FAIL_MODE=open)", user_id)
        else:
            raise AuthError(503, "Authentication is syncing, try again in a moment", "auth_syncing")

    user = await store.get_user(user_id)
    if user is None:  # just given access to SNVR? fetch the users snapshot once and look again
        await runtime.server.refresh_users_now()
        user = await store.get_user(user_id)
    if user is None:
        raise AuthError(401, "User has no access to this application", "no_access")
    if not user.is_active:
        raise AuthError(401, "User is deactivated", "inactive")

    current = await store.get_token_version(user_id)
    if current is None:
        if settings.AUTH_FAIL_MODE != "open":
            raise AuthError(401, "Session state unknown, please sign in again", "token_revoked")
    elif current != version:
        raise AuthError(401, "Session ended, please sign in again", "token_revoked")

    is_all, perms = parse_perms(claims.get("perms"))
    roles = tuple(str(r) for r in claims.get("roles") or [])
    return Principal(user_id=str(user_id), username=str(claims.get("sub") or user.username), roles=roles, perms=perms,
                     is_admin=is_all or ADMIN_ROLE in roles, display_name=user.display_name, source="legacy",
                     role_keys=roles)


def check_signing_key() -> None:
    """Startup check when AUTH_ENABLED (plan D1): no key = refuse to start; the known dev key = loud warning."""
    if not settings.AUTH_KEY:
        raise RuntimeError("AUTH_ENABLED=true but AUTH_KEY is empty: set the Auth Server signing secret in .env")
    if not settings.AUTH_CLIENT_SECRET:
        raise RuntimeError("AUTH_ENABLED=true but AUTH_CLIENT_SECRET is empty: set the downstream service secret")
    if hashlib.sha256(settings.AUTH_KEY.encode()).hexdigest() in KNOWN_DEV_KEY_HASHES or len(settings.AUTH_KEY) < 32:
        logger.warning("*" * 78)
        logger.warning("AUTH_KEY is a known development key (or shorter than 32 characters). Anyone who knows it")
        logger.warning("can mint valid tokens. Rotate it on the Auth Server before production.")
        logger.warning("*" * 78)
