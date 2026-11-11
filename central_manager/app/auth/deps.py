"""The request guard: runs before every API endpoint (registered on the FastAPI app in main.py).

1. Finds the route's rule (app/auth/policy.py); a route without a rule is refused.
2. Works out the caller: the built-in local admin when AUTH_ENABLED is off, otherwise the verified Auth Server
   user (Bearer header, or `?access_token=` where the rule allows it).
3. Checks the permission numbers, then the camera scope for routes with a `{camera_id}` (404 when hidden).
4. Marks the request for the audit log; `audit_middleware` writes the event with the real response status.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.audit.services import record
from app.auth.integration import get_runtime
from app.auth.policy import allows, change_action, rule_for
from app.auth.principal import Principal, local_admin, set_current
from app.auth.scope import camera_visible
from app.auth.verify import AuthError, verify_access_token
from settings.settings import settings

logger = logging.getLogger("central.auth")

ANONYMOUS = Principal(user_id=-1, username="anonymous")


def bearer_token(request: Request, allow_query: bool) -> str | None:
    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer ":
        return header[7:].strip() or None
    if allow_query:
        return request.query_params.get("access_token") or None
    return None


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def authenticate(request: Request, allow_query: bool = False) -> Principal:
    """The verified caller of this request (raises 401 / 503)."""
    if not settings.AUTH_ENABLED:
        return local_admin()
    token = bearer_token(request, allow_query)
    if not token:
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer", "X-Auth-Error": "missing"})
    runtime = get_runtime()
    if runtime is None:
        raise HTTPException(503, "Authentication is not running")
    try:
        return await verify_access_token(token, runtime)
    except AuthError as exc:
        headers = {"X-Auth-Error": exc.code}
        if exc.status == 401:
            headers["WWW-Authenticate"] = "Bearer"
        raise HTTPException(exc.status, exc.detail, headers=headers) from exc


async def guard(request: Request) -> None:
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    method = request.method.upper()
    rule = rule_for(method, path)
    if rule is None:
        logger.error("No access rule for %s %s: refused", method, path)
        raise HTTPException(403, "No access rule for this endpoint")
    if rule.internal:  # node -> central (its own key: plan §7.6)
        set_current(local_admin())
        return
    if rule.public:
        principal = local_admin() if not settings.AUTH_ENABLED else ANONYMOUS
        set_current(principal)
        request.state.principal = principal
        return

    principal = await authenticate(request, rule.query_token)
    set_current(principal)
    request.state.principal = principal
    camera_id = _camera_id(request)
    audit = rule.audit if method == "GET" else (change_action(method, path) if rule.audit_changes else None)

    if not allows(rule, principal.perms, principal.is_admin):
        _mark(request, principal, audit or f"denied.{method.lower()}", camera_id, "denied")
        raise HTTPException(403, "You do not have permission for this action", headers={"X-Auth-Error": "forbidden"})
    if camera_id is not None and not await camera_visible(camera_id, principal):
        raise HTTPException(404, "Camera not found")
    if audit:
        _mark(request, principal, audit, camera_id, None)


def _camera_id(request: Request) -> int | None:
    raw = request.path_params.get("camera_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _mark(request: Request, principal: Principal, action: str, camera_id: int | None, status: str | None) -> None:
    request.state.audit = {"principal": principal, "action": action, "camera_id": camera_id, "status": status}


class AuditMiddleware:
    """Writes the audit event marked by the guard, with the outcome (ok / denied / failed + HTTP status)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status_holder = {"code": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            mark = (scope.get("state") or {}).get("audit")
            if mark:
                code = status_holder["code"]
                status = mark["status"] or ("ok" if code < 400 else "failed")
                client = scope.get("client")
                await record(mark["principal"], mark["action"], method=scope["method"], path=scope["path"],
                             camera_id=mark["camera_id"], status=status,
                             detail={"http_status": code} if code >= 400 else None,
                             ip=client[0] if client else None)
