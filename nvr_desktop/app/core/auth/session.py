"""AuthSession: sign-in state, tokens and permissions (QML singleton `Auth`; docs/DESKTOP_AUTH_PLAN.md §4-§5).

States
  checking     asking central `/auth/config` (startup, server change)
  disabled     auth is off on central: the built-in local admin, the app works as before
  unreachable  central did not answer (Retry / Change server)
  signed_out   the login screen (`endedReason` says why a session ended)
  signed_in    user, roles, permission numbers and camera scope from `/auth/me`

Tokens
* The access token (10 min) lives only in memory. Its expiry is measured with the monotonic clock from
  `expires_in`, so a wrong PC clock does not matter.
* The refresh token rotates on every refresh, and the Auth Server logs the user out when an old one is reused.
  So refreshing is single-flight: one lock for the timer and every worker thread; a thread that waited and finds a
  newer token uses it instead of refreshing again.
* "Keep me signed in": the refresh token is kept encrypted with DPAPI (secure_store.py), else memory only.

Two Auth Servers (docs/DESKTOP_AUTH_V2_PLAN.md), chosen by central (`/auth/config` "mode"):
* legacy: the password form; login / refresh / logout go through central (as above).
* oidc:   `signInWithBrowser` opens the system browser on the Auth Server's login page and catches the answer on a
          loopback listener (oauth.py, PKCE). Refresh and logout go straight to the Auth Server; central only checks
          the access token. The stored entry remembers its mode + issuer, so a token never goes to the wrong server.
          State "waiting_browser" while the browser is open.

Threads: CentralApi calls run on worker threads (app/core/tasks.py). They call `token()`, `refresh_after_expired()`
and `report()`, which only touch lock-protected fields and emit queued signals. Everything else runs on the GUI thread.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from app.core.api.errors import ApiError, raise_for_response
from app.core.auth import oauth
from app.core.auth.oauth import LoopbackListener, OAuthError, OidcConfig, Pkce
from app.core.auth.permissions import ALL_PERMS, PAGE_PERMS, PERM_LABELS, allows, start_page, summary_text
from app.core.auth.secure_store import TokenStore
from app.core.auth.secure_store import supported as secure_store_supported
from app.core.tasks import run_task
from settings.settings import settings

logger = logging.getLogger(__name__)

# X-Auth-Error codes after which the session cannot be used any more (same list as the web client)
SESSION_ENDED = {"token_revoked", "inactive", "no_access", "invalid_token", "wrong_app", "refresh_failed"}
REFRESH_BEFORE_S = 60  # refresh this long before the access token expires
RETRY_BACKOFF_S = (5, 10, 20, 40, 60)

LOCAL_ADMIN = {"id": "0", "username": "local", "display_name": "Local administrator", "roles": [], "is_admin": True,
               "permissions": list(ALL_PERMS), "local": True, "scope": {"all_cameras": True, "groups": 0, "cameras": 0}}


def _reason(code: str | None) -> str:
    if code == "no_access":
        return "Your account no longer has access to Shah-NVR."
    if code == "inactive":
        return "Your account has been deactivated."
    if code == "missing":
        return "Sign-in is now required on this server."
    return "Your session ended. Please sign in again."


def browser_error(exc: Exception) -> str:
    """The message on the sign-in screen after a failed browser sign-in."""
    if isinstance(exc, OAuthError):
        if exc.code == "invalid_grant":
            return "Sign-in expired, please try again"
        return exc.message
    if isinstance(exc, ApiError):
        if exc.status == 0:
            return exc.message
        if exc.code == "no_access" or exc.status == 403:
            return "Your account has no access to Shah-NVR"
        if exc.status == 401:
            return f"Central refused the sign-in ({exc.message})"
        if exc.status == 503:
            return "The server is starting, try again in a moment"
        return exc.message
    return str(exc)


def _open_in_browser(url: str) -> bool:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    return bool(QDesktopServices.openUrl(QUrl(url)))


def login_error(exc: Exception) -> str:
    """The message under the login form."""
    if not isinstance(exc, ApiError):
        return str(exc)
    if exc.status == 0:
        return exc.message
    if exc.status == 401:
        return "Invalid username or password"
    if exc.code == "no_access" or exc.status == 403:
        return "Your account has no access to Shah-NVR"
    if exc.code == "inactive":
        return "Your account is deactivated"
    if exc.status == 503:
        return "The server is starting, try again in a moment"
    if exc.status in (502, 504):
        return "The sign-in service is not available"
    return exc.message


class AuthSession(QObject):
    changed = Signal()  # state, user, permissions, errors
    sessionStarted = Signal()  # became usable (signed_in or disabled): stores refresh
    sessionEnded = Signal()  # left the usable state: pages and players are torn down
    _failure = Signal(str)  # from worker threads -> GUI thread (queued)
    _refreshed = Signal()  # from worker threads -> GUI thread (queued)
    _callback = Signal(object)  # (generation, params | None) from the loopback listener thread (queued)
    bringToFront = Signal()  # browser sign-in finished: raise the main window

    def __init__(self, base_url: str, store: TokenStore | None = None,
                 post: Callable[..., httpx.Response] | None = None, get: Callable[..., httpx.Response] | None = None,
                 oauth_post: Callable[..., httpx.Response] | None = None,
                 open_url: Callable[[str], bool] | None = None, parent=None):
        super().__init__(parent)
        self._base = base_url.rstrip("/")
        self._store = store or TokenStore()
        self._post = post or httpx.post  # injectable for tests
        self._get = get or httpx.get
        self._oauth_post = oauth_post or httpx.post  # Auth Server calls (form-encoded)
        self._open_url = open_url or _open_in_browser
        self._mode = "legacy"  # from /auth/config
        self._oidc: OidcConfig | None = None
        self._flow: dict | None = None  # the pending browser sign-in
        self._sign_in_link = ""
        self._state = "checking"
        self._enabled = False
        self._user: dict | None = None
        self._ended_reason = ""
        self._login_error = ""
        self._busy = False
        self._reconnecting = False
        self._last_user_id: str | None = None
        # token state, shared with worker threads
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._access: str | None = None
        self._refresh: str | None = None
        self._expires_at = 0.0  # time.monotonic()
        self._remember = False
        self._generation = 0  # bumped when a session ends: late results of the old one are dropped
        self._retry_step = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh_now)
        self._failure.connect(self._on_failure)
        self._refreshed.connect(self._on_refreshed)
        self._callback.connect(self._on_callback)

    # ------------------------------------------------------------------ HTTP (worker threads)
    def _call(self, method: str, path: str, token: str | None = None, json: dict | None = None) -> dict | None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        url, timeout = f"{self._base}{path}", settings.HTTP_TIMEOUT_SECONDS
        try:
            if method == "POST":
                response = self._post(url, json=json, headers=headers, timeout=timeout)
            else:
                response = self._get(url, headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            raise ApiError(0, f"Cannot reach central at {self._base}") from exc
        raise_for_response(response)
        return response.json() if response.content else None

    # ------------------------------------------------------------------ used by CentralApi (any thread)
    def token(self) -> str | None:
        with self._lock:
            return self._access

    def valid_token(self) -> str | None:
        """A token that is good for at least 30 s more (downloads, URLs given to other programs). Worker threads."""
        with self._lock:
            token, left = self._access, self._expires_at - time.monotonic()
        if token and left < 30:
            try:
                return self.refresh_after_expired(token)
            except ApiError:
                return None
        return token

    def refresh_after_expired(self, stale: str | None) -> str:
        """Single-flight refresh. Returns the new access token; raises ApiError when it is not possible."""
        with self._refresh_lock:
            with self._lock:
                if self._access and self._access != stale:
                    return self._access  # another thread refreshed while this one waited
                refresh, generation = self._refresh, self._generation
            if not refresh:
                raise ApiError(401, "Not signed in", "missing")
            try:
                data = self._refresh_tokens(refresh)
            except ApiError as exc:
                if exc.status in (400, 401, 403, 404):  # expired, revoked or reused refresh token
                    self._failure.emit("refresh_failed")
                    raise ApiError(401, _reason("refresh_failed"), "refresh_failed") from exc
                raise  # network / server trouble: the session stays, the caller sees the error
            with self._lock:
                if generation != self._generation:  # signed out meanwhile: do not bring the session back
                    raise ApiError(401, "Signed out", "missing")
                self._set_tokens_locked(data)
                access = self._access
        self._refreshed.emit()
        return access

    def _refresh_tokens(self, refresh: str, mode: str | None = None, oidc: OidcConfig | None = None) -> dict:
        """One refresh at the right server (worker thread). OAuth errors become ApiError with the same status."""
        mode, oidc = mode or self._mode, oidc or self._oidc
        if mode != "oidc":
            return self._call("POST", "/api/v1/auth/refresh", json={"refresh_token": refresh}) or {}
        if oidc is None:
            raise ApiError(401, "Not signed in", "missing")
        try:
            return oauth.refresh(oidc, refresh, post=self._oauth_post)
        except OAuthError as exc:
            raise ApiError(exc.status, exc.message, exc.code) from exc

    def report(self, code: str | None) -> None:
        """A 401 that was not an expired token (CentralApi, any thread)."""
        self._failure.emit(code or "")

    def sign_url(self, url: str) -> str:
        """Add `access_token` to a central playback / export URL (players and downloads that cannot send headers)."""
        token = self.token()
        if not token or not url.startswith(self._base + "/"):
            return url
        path = urlsplit(url).path
        if not (path.startswith("/api/v1/playback/") or (path.startswith("/api/v1/exports/")
                                                          and path.endswith("/download"))):
            return url
        return f"{url}{'&' if '?' in url else '?'}access_token={token}"

    def _set_tokens_locked(self, data: dict) -> None:
        self._access = data["access_token"]
        self._refresh = data["refresh_token"]
        self._expires_at = time.monotonic() + max(30, int(data.get("expires_in") or 600))

    # ------------------------------------------------------------------ state
    def _set_state(self, state: str) -> None:
        was_ready = self.ready
        self._state = state
        self.changed.emit()
        if self.ready and not was_ready:
            self.sessionStarted.emit()
        elif was_ready and not self.ready:
            self.sessionEnded.emit()

    def _set_busy(self, value: bool) -> None:
        self._busy = value
        self.changed.emit()

    @property
    def ready(self) -> bool:
        return self._state in ("signed_in", "disabled")

    @property
    def base_url(self) -> str:
        return self._base

    def user_switched(self) -> bool:
        """True when the user that just signed in is not the previous one (stores drop their data then)."""
        return self._user is not None and self._user.get("id") != self._last_user_id

    # ------------------------------------------------------------------ startup / server change
    @Slot()
    def start(self) -> None:
        """Ask central whether sign-in is needed, then try the stored session."""
        self._generation += 1
        generation = self._generation
        self._set_state("checking")

        def check():
            config = self._call("GET", "/api/v1/auth/config") or {}
            mode = "oidc" if config.get("mode") == "oidc" else "legacy"
            oidc = OidcConfig.from_config(config) if mode == "oidc" else None
            base = {"enabled": True, "mode": mode, "oidc": oidc}
            if not config.get("enabled"):
                return {**base, "enabled": False}
            entry = self._store.load_entry(self._base)
            if not entry:
                return base
            same_server = entry.get("mode") == mode and (
                mode == "legacy" or (oidc is not None and entry.get("issuer") == oidc.issuer
                                     and entry.get("client_id") == oidc.client_id))
            if not same_server:  # saved under the other Auth Server (central was switched): sign in again
                return {**base, "stale": True}
            try:
                data = self._refresh_tokens(entry["refresh"], mode, oidc)
                me = self._call("GET", "/api/v1/auth/me", token=data["access_token"])
            except ApiError as exc:
                if exc.status == 0:
                    raise
                return {**base, "stale": True}
            return {**base, "tokens": data, "me": me}

        def ok(result: dict) -> None:
            if generation != self._generation:
                return
            self._mode, self._oidc = result.get("mode", "legacy"), result.get("oidc")
            self._enabled = bool(result.get("enabled"))
            if not self._enabled:
                self._user = dict(LOCAL_ADMIN)
                self._set_state("disabled")
            elif "tokens" in result:
                self._begin(result["tokens"], result["me"], remember=True)
            else:
                if result.get("stale"):
                    self._store.clear(self._base)
                self._set_state("signed_out")

        def err(exc: Exception) -> None:
            if generation != self._generation:
                return
            self._login_error = str(exc)
            self._set_state("unreachable")

        run_task(check, ok, err)

    def set_server(self, base_url: str) -> None:
        """The central URL changed: the old session belongs to the old server."""
        base_url = base_url.rstrip("/")
        if base_url == self._base:
            return
        self._clear_session(clear_stored=False)
        self._base = base_url
        self._ended_reason = ""
        self.start()

    # ------------------------------------------------------------------ sign in / out
    @Slot(str, str, bool)
    def signIn(self, username: str, password: str, remember: bool) -> None:
        username = username.strip()
        if not username or not password or self._busy:
            return
        self._login_error = ""
        self._set_busy(True)
        generation = self._generation

        def login():
            body = {"username": username, "password": password}
            try:
                data = self._call("POST", "/api/v1/auth/login", json=body)
            except ApiError as exc:
                if exc.code != "auth_syncing" and exc.status != 503:
                    raise
                time.sleep(2)  # central just started and is loading the users: one more try
                data = self._call("POST", "/api/v1/auth/login", json=body)
            me = self._call("GET", "/api/v1/auth/me", token=data["access_token"])
            return data, me

        def ok(result) -> None:
            self._busy = False
            if generation != self._generation:
                return
            data, me = result
            self._store.save_username(self._base, username)
            self._begin(data, me, remember)

        def err(exc: Exception) -> None:
            self._busy = False
            self._login_error = login_error(exc)
            self.changed.emit()

        run_task(login, ok, err)

    def _begin(self, tokens: dict, me: dict, remember: bool) -> None:
        with self._lock:
            self._set_tokens_locked(tokens)
            self._remember = remember
        if remember:
            self._save_refresh(tokens["refresh_token"])
        else:
            self._store.clear(self._base)
        self._user = me
        self._ended_reason = ""
        self._login_error = ""
        self._retry_step = 0
        self._schedule()
        self._set_state("signed_in")
        self._last_user_id = me.get("id")

    def _save_refresh(self, refresh: str) -> None:
        oidc = self._oidc if self._mode == "oidc" else None
        self._store.save_entry(self._base, self._mode, refresh, oidc.issuer if oidc else None,
                               oidc.client_id if oidc else None)

    # ------------------------------------------------------------------ browser sign-in (oidc)
    @Slot(bool)
    def signInWithBrowser(self, remember: bool) -> None:
        if self._busy or self._mode != "oidc" or self._state not in ("signed_out", "waiting_browser"):
            return
        if self._oidc is None:
            self._login_error = "Central did not send the Auth Server address (AUTH_ISSUER / AUTH_DESKTOP_CLIENT_ID)."
            self.changed.emit()
            return
        self._cancel_flow()
        generation, pkce = self._generation, Pkce()
        try:
            listener = LoopbackListener(lambda params: self._callback.emit((generation, params)))
        except OSError as exc:
            self._login_error = str(exc)
            self.changed.emit()
            return
        url = oauth.authorize_url(self._oidc, listener.port, pkce, force_login=self._store.signed_out(self._base))
        self._flow = {"listener": listener, "pkce": pkce, "port": listener.port, "remember": remember,
                      "generation": generation, "oidc": self._oidc}
        self._sign_in_link = url
        self._login_error = ""
        listener.start()
        self._set_state("waiting_browser")
        if not self._open_url(url):
            self._login_error = "Could not open the browser. Copy the link and open it yourself."
            self.changed.emit()

    def _on_callback(self, payload) -> None:
        generation, params = payload
        flow = self._flow
        if not flow or flow["generation"] != generation or generation != self._generation:
            return  # cancelled, or the server changed meanwhile
        self._flow = None
        if params is None:
            self._login_error = "Sign-in was not completed in time. Please try again."
            self._set_state("signed_out")
            return
        self._set_state("signed_out")
        self._set_busy(True)
        base = self._base

        def finish():
            code = oauth.check_callback(params, flow["pkce"], flow["oidc"])
            tokens = oauth.exchange_code(flow["oidc"], code, flow["pkce"], flow["port"], post=self._oauth_post)
            try:
                me = self._call("GET", "/api/v1/auth/me", token=tokens["access_token"])
            except ApiError as exc:
                if exc.code != "auth_syncing" and exc.status != 503:
                    raise
                time.sleep(2)  # central just started: one more try
                me = self._call("GET", "/api/v1/auth/me", token=tokens["access_token"])
            return tokens, me

        def ok(result) -> None:
            self._busy = False
            if generation != self._generation or base != self._base:
                return
            tokens, me = result
            self._store.set_signed_out(self._base, False)
            self._begin(tokens, me, flow["remember"])
            self.bringToFront.emit()

        def err(exc: Exception) -> None:
            self._busy = False
            self._login_error = browser_error(exc)
            self.changed.emit()

        run_task(finish, ok, err)

    def _cancel_flow(self) -> None:
        flow, self._flow = self._flow, None
        if flow:
            flow["listener"].close()
        self._sign_in_link = ""

    @Slot()
    def cancelBrowserSignIn(self) -> None:
        if self._state != "waiting_browser":
            return
        self._cancel_flow()
        self._set_state("signed_out")

    @Slot()
    def openSignInLinkAgain(self) -> None:
        if self._sign_in_link and not self._open_url(self._sign_in_link):
            self._login_error = "Could not open the browser. Copy the link and open it yourself."
            self.changed.emit()

    @Slot()
    def copySignInLink(self) -> None:
        if not self._sign_in_link:
            return
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard() if QGuiApplication.instance() else None
        if clipboard is not None:
            clipboard.setText(self._sign_in_link)

    @Slot()
    def signOut(self) -> None:
        """legacy: sign out everywhere (the old server ends every session of the user, decision D4).
        oidc: end this device's login only, and ask for the password on the next sign-in here (DV8)."""
        with self._lock:
            token, refresh = self._access, self._refresh
        mode, oidc, base = self._mode, self._oidc, self._base
        if token:
            def logout():
                try:  # central first (audit), while the access token is still valid
                    self._post(f"{base}/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"},
                               timeout=settings.HTTP_TIMEOUT_SECONDS)
                except httpx.HTTPError as exc:
                    logger.info("Logout request failed (signed out locally): %s", exc)
                if mode == "oidc" and oidc is not None:
                    oauth.end_login(oidc, token, refresh, post=self._oauth_post)

            run_task(logout, None, lambda exc: logger.info("Sign-out calls failed (signed out locally): %s", exc))
        if mode == "oidc":
            self._store.set_signed_out(base, True)
        self._end("")

    def _end(self, reason: str) -> None:
        self._clear_session(clear_stored=True)
        self._ended_reason = reason
        self._set_state("signed_out")

    def _clear_session(self, clear_stored: bool) -> None:
        self._cancel_flow()
        self._timer.stop()
        with self._lock:
            self._generation += 1
            self._access = self._refresh = None
            self._expires_at = 0.0
        if clear_stored:
            self._store.clear(self._base)
        self._reconnecting = False

    # ------------------------------------------------------------------ refresh timer (GUI thread)
    def _schedule(self, seconds: float | None = None) -> None:
        if seconds is None:
            with self._lock:
                seconds = self._expires_at - time.monotonic() - REFRESH_BEFORE_S
        self._timer.start(int(max(5.0, seconds) * 1000))

    def _refresh_now(self) -> None:
        stale = self.token()
        if not stale:
            return

        def err(exc: Exception) -> None:
            if isinstance(exc, ApiError) and exc.code in ("refresh_failed", "missing"):
                return  # _on_failure ends the session
            # network or server trouble: keep the session and try again soon
            delay = RETRY_BACKOFF_S[min(self._retry_step, len(RETRY_BACKOFF_S) - 1)]
            self._retry_step += 1
            self._reconnecting = True
            self.changed.emit()
            logger.info("Token refresh failed (%s); retrying in %ss", exc, delay)
            self._schedule(delay)

        run_task(lambda: self.refresh_after_expired(stale), None, err)

    def _on_refreshed(self) -> None:
        if self._state != "signed_in":
            return
        with self._lock:
            refresh, remember = self._refresh, self._remember
        if remember and refresh:
            self._save_refresh(refresh)  # the old one is no longer valid (rotation)
        self._retry_step = 0
        self._reconnecting = False
        self._schedule()
        self.reloadMe()  # roles may have changed: the new token carries the new permissions

    @Slot()
    def reloadMe(self) -> None:
        token, generation = self.token(), self._generation
        if not token:
            return

        def ok(me: dict) -> None:
            if generation == self._generation and self._state == "signed_in" and me != self._user:
                self._user = me
                self.changed.emit()

        run_task(lambda: self._call("GET", "/api/v1/auth/me", token=token), ok,
                 lambda exc: logger.debug("Reloading /auth/me failed: %s", exc))

    # ------------------------------------------------------------------ 401s from the API (GUI thread)
    def _on_failure(self, code: str) -> None:
        if self._state == "signed_in" and (code in SESSION_ENDED or code == "missing"):
            logger.info("Session ended by the server (%s)", code)
            self._end(_reason(code))
        elif self._state == "disabled" and code == "missing":  # auth was switched on while the app ran
            self._enabled = True
            self._user = None
            self._end(_reason("missing"))

    # ------------------------------------------------------------------ QML API
    def can(self, *perms: int) -> bool:
        user = self._user
        if not self.ready or not user:
            return False
        return allows(bool(user.get("is_admin")), user.get("permissions") or [], perms)

    @Slot("QVariantList", result=bool)
    def allowsAny(self, perms) -> bool:
        return self.can(*(int(p) for p in perms or []))

    def _allowed(self) -> dict:
        """{"1": True, ...} for QML bindings (`Auth.allowed["5"]`); re-evaluated on `changed`."""
        return {str(p): self.can(p) for p in ALL_PERMS}

    def _pages(self) -> dict:
        return {page: self.can(*perms) for page, perms in PAGE_PERMS.items()}

    def start_page(self) -> str:
        user = self._user or {}
        return start_page(bool(user.get("is_admin")), user.get("permissions") or [])

    def _scope_text(self) -> str:
        user = self._user or {}
        return summary_text(user.get("scope"), bool(user.get("is_admin")))

    def _permission_labels(self) -> list:
        user = self._user or {}
        return [PERM_LABELS[p] for p in sorted(user.get("permissions") or []) if p in PERM_LABELS]

    @Slot()
    def retry(self) -> None:
        self.start()

    state = Property(str, lambda self: self._state, notify=changed)
    enabled = Property(bool, lambda self: self._enabled, notify=changed)
    isReady = Property(bool, lambda self: self.ready, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    reconnecting = Property(bool, lambda self: self._reconnecting, notify=changed)
    user = Property("QVariant", lambda self: self._user or {}, notify=changed)
    isAdmin = Property(bool, lambda self: bool((self._user or {}).get("is_admin")), notify=changed)
    allowed = Property("QVariantMap", _allowed, notify=changed)
    pages = Property("QVariantMap", _pages, notify=changed)
    permissionLabels = Property("QVariantList", _permission_labels, notify=changed)
    scopeText = Property(str, _scope_text, notify=changed)
    endedReason = Property(str, lambda self: self._ended_reason, notify=changed)
    loginError = Property(str, lambda self: self._login_error, notify=changed)
    serverUrl = Property(str, lambda self: self._base, notify=changed)
    lastUsername = Property(str, lambda self: self._store.last_username(self._base), notify=changed)
    secureStoreSupported = Property(bool, lambda self: secure_store_supported(), constant=True)
    mode = Property(str, lambda self: self._mode, notify=changed)  # legacy | oidc
    waitingBrowser = Property(bool, lambda self: self._state == "waiting_browser", notify=changed)
    signInLink = Property(str, lambda self: self._sign_in_link, notify=changed)
    issuerHost = Property(str, lambda self: urlsplit(self._oidc.issuer).netloc if self._oidc else "", notify=changed)
