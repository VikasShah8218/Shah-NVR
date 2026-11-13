"""Auth endpoints for the clients (docs/AUTH_INTEGRATION_PLAN.md §7.1, docs/AUTH_V2_PLAN.md).

GET  /api/v1/auth/config   -> {enabled, app_key, mode, ...}: does the client need a login, and which kind?
                              mode "legacy": central's /login form; mode "oidc": the Auth Server's login page
                              (issuer + public client ids for Authorization Code + PKCE)
POST /api/v1/auth/login    -> legacy only: proxied to the Auth Server with app_key forced to SNVR
POST /api/v1/auth/refresh  -> legacy only: proxied (refresh tokens rotate; reusing an old one logs the user out)
POST /api/v1/auth/logout   -> legacy: proxied (signed out everywhere, decision D6). oidc: audit only; the client
                              ends its own session at the Auth Server (/oauth/revoke, /oauth/logout)
GET  /api/v1/auth/me       -> the caller, permission numbers and camera scope summary
GET  /api/v1/auth/status   -> which Auth Server, and its sync health
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.audit.services import record
from app.auth import scope
from app.auth.deps import bearer_token, client_ip
from app.auth.integration import AuthServerError
from app.auth.permissions import Perm, parse_perms
from app.auth.principal import ADMIN_ROLE, Principal, current
from app.auth.provider import LEGACY, LegacyProvider, get_provider
from settings.settings import settings

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


class AuthConfigOut(BaseModel):
    enabled: bool
    app_key: str
    mode: str = LEGACY  # legacy | oidc
    issuer: str | None = None  # oidc: the Auth Server (login page, /oauth/token, /oauth/revoke, /oauth/logout)
    web_client_id: str | None = None
    desktop_client_id: str | None = None
    scopes: str | None = None


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    totp: str | None = Field(default=None, max_length=16)  # 2FA: passed through, not used by the UI yet (D7)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserOut(BaseModel):
    id: str  # "12" (legacy) or the user's UUID (oidc)
    username: str
    display_name: str
    roles: list[str]
    permissions: list[int]  # resolved Shah-NVR permission numbers (all of them for admins)
    is_admin: bool
    local: bool = False  # auth is off: built-in local admin


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginOut(TokensOut):
    user: UserOut


class MeOut(UserOut):
    scope: dict  # {all_cameras, groups, cameras}


def _user_from_login(data: dict) -> UserOut:
    raw_user = data.get("user") or {}
    roles = [str(r) for r in data.get("roles") or []]
    is_all, perms = parse_perms(data.get("permissions"))
    is_admin = is_all or ADMIN_ROLE in roles
    name = " ".join(p for p in (raw_user.get("first_name"), raw_user.get("last_name")) if p)
    return UserOut(id=str(raw_user.get("id", 0)), username=str(raw_user.get("username", "")),
                   display_name=name or str(raw_user.get("username", "")), roles=roles,
                   permissions=sorted(p.value for p in Perm) if is_admin else sorted(perms), is_admin=is_admin)


def _tokens(data: dict) -> dict:
    try:
        return {"access_token": data["access_token"], "refresh_token": data["refresh_token"],
                "expires_in": int(data["expires_in"])}
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(502, "Unexpected answer from the authentication server") from exc


def _server():
    if not settings.AUTH_ENABLED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Authentication is disabled on this server")
    provider = get_provider()
    if provider is None:
        raise HTTPException(503, "Authentication is not running")
    if not isinstance(provider, LegacyProvider):
        raise HTTPException(status.HTTP_409_CONFLICT, "This server signs in on the Auth Server's login page")
    return provider.runtime.server


@router.get("/config", response_model=AuthConfigOut, summary="Is sign-in required, and how? (no token needed)")
async def auth_config():
    provider = get_provider()
    extra = provider.client_config() if settings.AUTH_ENABLED and provider else {}
    return AuthConfigOut(enabled=settings.AUTH_ENABLED, app_key=settings.AUTH_APP_KEY, mode=settings.AUTH_PROVIDER,
                         **extra)


@router.post("/login", response_model=LoginOut, summary="Sign in (proxied to the Auth Server, app SNVR)")
async def login(body: LoginIn, request: Request):
    server = _server()
    try:
        data = await server.login(body.username, body.password, body.totp)
    except AuthServerError as exc:
        await record(Principal(user_id="", username=body.username, source=LEGACY), "auth.login", method="POST",
                     path=request.url.path, status="denied", detail={"reason": exc.detail}, ip=client_ip(request))
        if exc.status == 404:  # the Auth Server answers a wrong password with 404
            raise HTTPException(401, "Invalid username or password") from exc
        raise HTTPException(exc.status, exc.detail) from exc
    user = _user_from_login(data)
    await record(Principal(user_id=user.id, username=user.username, source=LEGACY), "auth.login", method="POST",
                 path=request.url.path, ip=client_ip(request))
    return LoginOut(**_tokens(data), user=user)


@router.post("/refresh", response_model=TokensOut, summary="New access + refresh tokens (refresh tokens rotate)")
async def refresh(body: RefreshIn):
    server = _server()
    try:
        data = await server.refresh(body.refresh_token)
    except AuthServerError as exc:
        raise HTTPException(exc.status, exc.detail, headers={"X-Auth-Error": "refresh_failed"}) from exc
    return TokensOut(**_tokens(data))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT,
             summary="Sign out (everywhere: the user's token version is bumped)")
async def logout(request: Request):
    principal = current()
    if principal.local:
        return
    if principal.source == LEGACY:
        token = bearer_token(request, allow_query=False)
        try:
            await _server().logout(token or "")
        except AuthServerError as exc:
            if exc.status != 401:  # an already-ended session is fine
                raise HTTPException(exc.status, exc.detail) from exc
    await record(principal, "auth.logout", method="POST", path=request.url.path, ip=client_ip(request))


@router.get("/me", response_model=MeOut, summary="The signed-in user, permissions and camera scope")
async def me():
    p = current()
    return MeOut(id=p.user_id, username=p.username, display_name=p.display_name or p.username, roles=list(p.roles),
                 permissions=p.permission_list(), is_admin=p.is_admin, local=p.local, scope=await scope.summary(p))


class AuthStatusOut(BaseModel):
    enabled: bool
    mode: str
    health: dict


@router.get("/status", response_model=AuthStatusOut, summary="Which Auth Server, and its sync health")
async def auth_status():
    provider = get_provider()
    return AuthStatusOut(enabled=settings.AUTH_ENABLED, mode=settings.AUTH_PROVIDER,
                         health=provider.health() if provider else {})
