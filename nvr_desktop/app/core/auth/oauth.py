"""Sign-in on the new Auth Server through the system browser (docs/DESKTOP_AUTH_V2_PLAN.md, RFC 8252).

OAuth 2.1 Authorization Code + PKCE (S256) with a loopback redirect:
1. `Pkce()` makes the verifier, its challenge and a state value.
2. `LoopbackListener` listens on 127.0.0.1 (ports 5199, 5198, 5197: all registered on the snvr-desktop client,
   because the Auth Server matches redirect URIs exactly). It answers one `GET /callback`, then closes.
3. The browser opens `authorize_url(...)`: the Auth Server's own login page (password, 2FA, passkeys).
4. The Auth Server redirects to the listener with `code`, `state`, `iss`; `check_callback` validates them.
5. `exchange_code` swaps the code for tokens; `refresh` / `end_login` handle the rest of the session.

No Qt here (unit-tested on its own). HTTP calls take an injectable `post` with the httpx.post signature.
"""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

logger = logging.getLogger(__name__)

PORTS = (5199, 5198, 5197)
CALLBACK_PATH = "/callback"
TIMEOUT_S = 300  # a sign-in left open in the browser this long is abandoned
HTTP_TIMEOUT_S = 15

Post = Callable[..., httpx.Response]


@dataclass(frozen=True)
class OidcConfig:
    """From central's GET /api/v1/auth/config (mode "oidc")."""

    issuer: str
    client_id: str
    scopes: str = "openid profile email"

    @classmethod
    def from_config(cls, config: dict) -> "OidcConfig | None":
        issuer, client_id = config.get("issuer"), config.get("desktop_client_id")
        if not issuer or not client_id:
            return None
        return cls(str(issuer).rstrip("/"), str(client_id), str(config.get("scopes") or "openid profile email"))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class Pkce:
    verifier: str = field(default_factory=lambda: _b64url(secrets.token_bytes(48)))
    state: str = field(default_factory=lambda: _b64url(secrets.token_bytes(32)))

    @property
    def challenge(self) -> str:
        return _b64url(hashlib.sha256(self.verifier.encode("ascii")).digest())


def redirect_uri(port: int) -> str:
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"


def authorize_url(cfg: OidcConfig, port: int, pkce: Pkce, force_login: bool = False) -> str:
    params = {
        "response_type": "code", "client_id": cfg.client_id, "redirect_uri": redirect_uri(port), "scope": cfg.scopes,
        "state": pkce.state, "code_challenge": pkce.challenge, "code_challenge_method": "S256",
    }
    if force_login:  # after a sign-out: the browser's SSO cookie must not sign the next person in silently
        params["prompt"] = "login"
    return f"{cfg.issuer}/oauth/authorize?{urlencode(params)}"


class OAuthError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


CALLBACK_ERRORS = {
    "access_denied": "Your account has no role in Shah-NVR. Ask an administrator for access.",
    "login_required": "Please sign in.",
    "invalid_scope": "The Auth Server refused the requested scopes (check the snvr-desktop client).",
}


def check_callback(params: dict[str, str], pkce: Pkce, cfg: OidcConfig) -> str:
    """The authorization code from a callback, or OAuthError with a message for the user."""
    error = params.get("error")
    if error:
        raise OAuthError(400, error, CALLBACK_ERRORS.get(error) or params.get("error_description")
                         or f"Sign-in failed ({error})")
    if not secrets.compare_digest(params.get("state", ""), pkce.state):
        raise OAuthError(400, "invalid_state", "This sign-in answer does not match. Please sign in again.")
    iss = params.get("iss")
    if iss and iss.rstrip("/") != cfg.issuer:
        raise OAuthError(400, "invalid_issuer", "The answer came from another Auth Server.")
    code = params.get("code")
    if not code:
        raise OAuthError(400, "invalid_request", "The Auth Server sent no authorization code.")
    return code


# ---------------------------------------------------------------------- token endpoint
def _token_call(cfg: OidcConfig, form: dict, post: Post | None) -> dict:
    post = post or httpx.post
    try:
        response = post(f"{cfg.issuer}/oauth/token", data=form,
                        headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=HTTP_TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise OAuthError(0, "unreachable", f"Cannot reach the Auth Server at {cfg.issuer}") from exc
    if response.status_code >= 400:
        code, message = "error", f"Auth Server error (HTTP {response.status_code})"
        try:
            body = response.json()
            detail = body.get("detail") if isinstance(body, dict) else None
            code = str(body.get("error") or (detail or {}).get("code") or code)
            message = str(body.get("error_description") or (detail or {}).get("message") or code)
        except (ValueError, AttributeError):
            pass
        raise OAuthError(response.status_code, code, message)
    data = response.json()
    if not isinstance(data, dict) or not data.get("access_token"):
        raise OAuthError(502, "invalid_response", "Unexpected answer from the Auth Server")
    return data


def exchange_code(cfg: OidcConfig, code: str, pkce: Pkce, port: int, post: Post | None = None) -> dict:
    data = _token_call(cfg, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(port),
                             "code_verifier": pkce.verifier, "client_id": cfg.client_id}, post)
    if not data.get("refresh_token"):
        raise OAuthError(502, "invalid_response", "The Auth Server sent no refresh token")
    return data


def refresh(cfg: OidcConfig, refresh_token: str, post: Post | None = None) -> dict:
    """New tokens. Within the Auth Server's grace window the answer has no refresh_token: keep the old one."""
    data = _token_call(cfg, {"grant_type": "refresh_token", "refresh_token": refresh_token,
                             "client_id": cfg.client_id}, post)
    return {**data, "refresh_token": data.get("refresh_token") or refresh_token}


def end_login(cfg: OidcConfig, access_token: str | None, refresh_token: str | None, post: Post | None = None) -> None:
    """End this device's login: the login itself, then the refresh token family. Errors are only logged."""
    post = post or httpx.post
    calls = []
    if access_token:
        calls.append((f"{cfg.issuer}/oauth/logout", {"headers": {"Authorization": f"Bearer {access_token}"}}))
    if refresh_token:
        calls.append((f"{cfg.issuer}/oauth/revoke", {"data": {"token": refresh_token, "client_id": cfg.client_id}}))
    for url, kwargs in calls:
        try:
            post(url, timeout=HTTP_TIMEOUT_S, **kwargs)
        except httpx.HTTPError as exc:
            logger.info("Auth Server sign-out call failed (%s): %s", url.rsplit("/", 1)[-1], exc)


# ---------------------------------------------------------------------- loopback listener
_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Shah-NVR sign-in</title>
<style>body{{font-family:system-ui,sans-serif;background:#2b303b;color:#e6e9ef;display:grid;place-items:center;
height:100vh;margin:0}}div{{background:#353b48;padding:32px 40px;border-radius:12px;max-width:420px;text-align:center}}
h1{{font-size:20px;margin:0 0 8px}}p{{color:#b8c0cc;margin:0}}</style></head>
<body><div><h1>{title}</h1><p>{text}</p></div></body></html>"""


class LoopbackListener:
    """One-shot HTTP listener on 127.0.0.1 for the OAuth redirect. `on_result(params)` gets the query of the first
    /callback request, or `None` on timeout. `close()` stops it without calling `on_result`. The callback runs on
    a listener thread: hand it to the GUI thread."""

    def __init__(self, on_result: Callable[[dict[str, str] | None], None], ports: tuple[int, ...] = PORTS,
                 timeout_s: float = TIMEOUT_S):
        self._on_result = on_result
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._server = self._bind(ports)
        self.port = self._server.server_address[1]
        self._timer = threading.Timer(timeout_s, lambda: self._finish(None))
        self._timer.daemon = True
        self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.2},
                                        name="oauth-loopback", daemon=True)

    def _bind(self, ports: tuple[int, ...]) -> HTTPServer:
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                parts = urlsplit(self.path)
                if parts.path != CALLBACK_PATH or listener._done.is_set():
                    self.send_error(404)
                    return
                params = {k: v[0] for k, v in parse_qs(parts.query).items()}
                if params.get("error"):
                    title, text = "Sign-in did not finish", CALLBACK_ERRORS.get(params["error"], params["error"])
                else:
                    title, text = "Signed in", "You can close this tab and return to Shah-NVR."
                body = _PAGE.format(title=html.escape(title), text=html.escape(text)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                listener._finish(params)

            def log_message(self, *args):  # the query holds a one-time code: keep it out of the logs
                pass

        last: OSError | None = None
        for port in ports:
            try:
                return HTTPServer(("127.0.0.1", port), Handler)  # loopback only: never reachable from the LAN
            except OSError as exc:
                last = exc
        raise OSError(f"Could not start the sign-in listener (ports {'/'.join(map(str, ports))} are in use)") from last

    def start(self) -> "LoopbackListener":
        self._thread.start()
        self._timer.start()
        return self

    def _finish(self, params: dict[str, str] | None) -> None:
        with self._lock:
            if self._done.is_set():
                return
            self._done.set()
        self._stop()
        try:
            self._on_result(params)
        except Exception:  # noqa: BLE001
            logger.exception("Sign-in callback handler failed")

    def close(self) -> None:
        """Stop without a result (Cancel, server change). Safe from any thread, idempotent."""
        with self._lock:
            if self._done.is_set():
                return
            self._done.set()
        self._stop()

    def _stop(self) -> None:
        self._timer.cancel()
        started = self._thread.is_alive()

        def run():  # shutdown() waits for serve_forever: never call it from the serving thread itself
            if started:
                self._server.shutdown()
            self._server.server_close()

        threading.Thread(target=run, name="oauth-loopback-stop", daemon=True).start()

    @property
    def done(self) -> bool:
        return self._done.is_set()
