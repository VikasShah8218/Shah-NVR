"""Connection to the Auth Server (docs/AUTH_INTEGRATION_PLAN.md §4, §7.1).

A rewrite of the handover bundle (docs/auth-server-doc/handover/) on top of the AuthStateStore, with its
defects fixed:
* initial token versions come from the users snapshot (SSE only sends *changes*; the bundle left every user
  "unknown" after a restart, which with fail-closed locks everyone out);
* a user that fails validation is skipped (the bundle saved an unbound / previous user);
* users removed from the application are dropped (the bundle kept them forever);
* the SSE loop reconnects with backoff instead of every 2 s forever;
* an unknown user (just assigned to SNVR) triggers an immediate snapshot instead of waiting 10 minutes.

Three background loops, all started from main.py when AUTH_ENABLED:
* service token: POST /internal/v1/service-token (HTTP Basic client id/secret), renewed before expiry;
* users snapshot: GET /internal/v1/users/{app} every AUTH_USERS_REFRESH_SECONDS (or when asked);
* revocations: GET /internal/v1/events/{app} (SSE): {user_id, token_version} on logout / password / role change.
Login, refresh and logout for the clients are proxied here too (clients never call the Auth Server).
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from app.auth.state import AuthStateStore, AuthUser, create_store
from settings.settings import settings

logger = logging.getLogger("central.auth")

RETRY_MIN, RETRY_MAX = 1.0, 30.0
SERVICE_TOKEN_MARGIN = 30  # renew this long before expiry (half the lifetime for very short tokens)


class AuthServerError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, str) else f"HTTP {response.status_code}"


def parse_user(raw: dict) -> AuthUser:
    """One item of GET /internal/v1/users/{app}: {"user": {...}, "roles": [{name}], "permissions": [{code}]}."""
    user = raw["user"]
    return AuthUser(
        id=int(user["id"]), username=str(user["username"]), is_active=bool(user.get("is_active", True)),
        is_superuser=bool(user.get("is_superuser", False)), token_version=user.get("token_version"),
        first_name=user.get("first_name"), last_name=user.get("last_name"), email=user.get("email"),
        roles=tuple(str(r["name"]) for r in raw.get("roles") or []),
        permissions=tuple(str(p["code"]) for p in raw.get("permissions") or []),
    )


def parse_events(data: str) -> dict[int, int]:
    """SSE data -> {user_id: token_version}. The payload is one object or a list of them."""
    try:
        payload = json.loads(data)
    except ValueError:
        logger.warning("Auth events: unreadable payload ignored")
        return {}
    items = payload if isinstance(payload, list) else [payload]
    versions: dict[int, int] = {}
    for item in items:
        try:
            versions[int(item["user_id"])] = int(item["token_version"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Auth events: invalid item ignored")
    return versions


class AuthServer:
    def __init__(self, store: AuthStateStore, http: httpx.AsyncClient | None = None):
        self.store = store
        self.http = http or httpx.AsyncClient(base_url=settings.AUTH_SERVER.rstrip("/"),
                                              timeout=settings.AUTH_HTTP_TIMEOUT_SECONDS)
        self.app_key = settings.AUTH_APP_KEY
        self._users_wanted = asyncio.Event()
        self._users_done = asyncio.Event()
        self._users_lock = asyncio.Lock()

    async def close(self) -> None:
        await self.http.aclose()

    # ------------------------------------------------------------------ client proxy (login / refresh / logout)
    async def login(self, username: str, password: str, totp: str | None = None) -> dict:
        body = {"username": username, "password": password, "app_key": self.app_key, "TOTP": totp}
        return await self._client_call("POST", "/login/", json=body)

    async def refresh(self, refresh_token: str) -> dict:
        return await self._client_call("POST", "/refresh", json={"refresh_token": refresh_token})

    async def logout(self, access_token: str) -> None:
        await self._client_call("POST", "/logout", headers={"Authorization": f"Bearer {access_token}"})

    async def _client_call(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise AuthServerError(503, "Authentication server unreachable") from exc
        if response.status_code >= 400:
            raise AuthServerError(response.status_code if response.status_code < 500 else 502, _detail(response))
        data = response.json() if response.content else {}
        app = str(data.get("app_key") or self.app_key) if isinstance(data, dict) else self.app_key
        if app.upper() != self.app_key.upper():
            raise AuthServerError(403, "Token was issued for another application")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ service token
    async def fetch_service_token(self) -> int:
        """Get a service token, store it, and return its lifetime (seconds)."""
        response = await self.http.post("/internal/v1/service-token",
                                        auth=httpx.BasicAuth(settings.AUTH_CLIENT_ID, settings.AUTH_CLIENT_SECRET),
                                        headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        token, expires_in = payload.get("access_token"), payload.get("expires_in")
        if not isinstance(token, str) or not token or not isinstance(expires_in, int) or expires_in <= 0:
            raise ValueError("Auth Server returned an invalid service token")
        if str(payload.get("app_key", "")).upper() != self.app_key.upper():
            raise ValueError(f"Service token is for app {payload.get('app_key')!r}, expected {self.app_key!r}")
        await self.store.set_service_token(token, expires_in)
        return expires_in

    async def run_service_token(self) -> None:
        delay = RETRY_MIN
        while True:
            try:
                expires_in = await self.fetch_service_token()
                delay = RETRY_MIN
                await asyncio.sleep(max(1, expires_in - min(SERVICE_TOKEN_MARGIN, expires_in // 2)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep the loop alive, log and back off
                status = getattr(getattr(exc, "response", None), "status_code", None)
                logger.error("Service token request failed (%s): %s; retrying in %.0f s", status or "-",
                             exc if status is None else _detail(exc.response), delay)
                await asyncio.sleep(delay)
                delay = min(RETRY_MAX, delay * 2)

    async def _service_headers(self) -> dict:
        for _ in range(30):  # the token loop may still be starting
            token = await self.store.get_service_token()
            if token:
                return {"Authorization": f"Bearer {token}"}
            await asyncio.sleep(1)
        raise RuntimeError("No service token (is AUTH_CLIENT_SECRET right?)")

    # ------------------------------------------------------------------ users snapshot
    async def fetch_users(self) -> int:
        response = await self.http.get(f"/internal/v1/users/{self.app_key}", headers=await self._service_headers())
        response.raise_for_status()
        users = []
        for raw in response.json():
            try:
                users.append(parse_user(raw))
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning("Auth users: invalid entry skipped (%s)", exc)
        await self.store.replace_users(users)
        return len(users)

    async def run_users(self) -> None:
        delay = RETRY_MIN
        while True:
            try:
                async with self._users_lock:
                    count = await self.fetch_users()
                self._users_done.set()
                logger.debug("Auth users snapshot: %d users", count)
                delay = RETRY_MIN
                try:  # next round: on schedule, or earlier when asked (unknown user, SSE event)
                    await asyncio.wait_for(self._users_wanted.wait(), settings.AUTH_USERS_REFRESH_SECONDS)
                except asyncio.TimeoutError:
                    pass
                self._users_wanted.clear()
                self._users_done.clear()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("Auth users snapshot failed: %s; retrying in %.0f s", exc, delay)
                await asyncio.sleep(delay)
                delay = min(RETRY_MAX, delay * 2)

    async def refresh_users_now(self, wait: float = 3.0) -> None:
        """Ask for a fresh snapshot (a user unknown here may just have been given access) and wait a little."""
        self._users_done.clear()
        self._users_wanted.set()
        try:
            await asyncio.wait_for(self._users_done.wait(), wait)
        except asyncio.TimeoutError:
            pass

    # ------------------------------------------------------------------ revocation events (SSE)
    async def run_events(self) -> None:
        delay = RETRY_MIN
        url = f"/internal/v1/events/{self.app_key}"
        while True:
            try:
                headers = {**await self._service_headers(), "Accept": "text/event-stream"}
                timeout = httpx.Timeout(settings.AUTH_HTTP_TIMEOUT_SECONDS, read=None)
                async with self.http.stream("GET", url, headers=headers, timeout=timeout) as response:
                    response.raise_for_status()
                    logger.info("Auth events stream connected")
                    delay = RETRY_MIN
                    data: list[str] = []
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data.append(line[5:].strip())
                        elif line == "" and data:
                            versions = parse_events("\n".join(data))
                            data.clear()
                            if versions:
                                await self._apply_events(versions)
                logger.warning("Auth events stream ended; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("Auth events stream failed: %s; reconnecting in %.0f s", exc, delay)
                await asyncio.sleep(delay)
                delay = min(RETRY_MAX, delay * 2)

    async def _apply_events(self, versions: dict[int, int]) -> None:
        await self.store.set_token_versions(versions)
        logger.info("Auth events: token version changed for %d user(s)", len(versions))
        unknown = [uid for uid in versions if await self.store.get_user(uid) is None]
        if unknown:  # e.g. a user just given access to SNVR, or roles changed: refresh the snapshot
            self._users_wanted.set()


# ---------------------------------------------------------------------- runtime (one per process)
class AuthRuntime:
    def __init__(self, store: AuthStateStore, server: AuthServer):
        self.store, self.server = store, server
        self.tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self.tasks = [
            asyncio.create_task(self.server.run_service_token(), name="auth-service-token"),
            asyncio.create_task(self.server.run_users(), name="auth-users"),
            asyncio.create_task(self.server.run_events(), name="auth-events"),
        ]

    async def stop(self) -> None:
        for task in reversed(self.tasks):  # events + users before the token loop
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.server.close()


_runtime: AuthRuntime | None = None


def get_runtime() -> AuthRuntime | None:
    return _runtime


def set_runtime(runtime: AuthRuntime | None) -> None:
    global _runtime
    _runtime = runtime


def create_runtime() -> AuthRuntime:
    store = create_store(settings.AUTH_STATE_BACKEND)
    return AuthRuntime(store, AuthServer(store))
