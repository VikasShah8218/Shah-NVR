"""Desktop sign-in on the new Auth Server (docs/DESKTOP_AUTH_V2_PLAN.md): the AuthSession in oidc mode with a fake
central, a fake Auth Server and a fake browser that follows the redirect to the real loopback listener."""

from __future__ import annotations

import functools
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from PySide6.QtCore import QCoreApplication, QSettings

from app.core.auth import oauth, secure_store
from app.core.auth.secure_store import TokenStore
from app.core.auth.session import AuthSession

app = QCoreApplication.instance() or QCoreApplication([])
BASE = "http://central.test"
ISSUER = "http://auth.test"
ME = {"id": "11111111-1111-1111-1111-111111111111", "username": "op", "display_name": "Operator",
      "roles": ["Operator"], "permissions": [1, 2], "is_admin": False, "local": False,
      "scope": {"all_cameras": False, "groups": 1, "cameras": 0}}
needs_dpapi = pytest.mark.skipif(not secure_store.supported(), reason="DPAPI is Windows-only")


def immediate(fn, ok=None, err=None):
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - mirrors run_task
        if err:
            err(exc)
    else:
        if ok:
            ok(result)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def sync_tasks(monkeypatch):
    monkeypatch.setattr("app.core.auth.session.run_task", immediate)
    # a free port per test (5199 may be busy on a developer PC), short timeout available via `listener_timeout`
    monkeypatch.setattr("app.core.auth.session.LoopbackListener",
                        functools.partial(oauth.LoopbackListener, ports=(free_port(),)))


@pytest.fixture
def store(tmp_path):
    return TokenStore(QSettings(str(tmp_path / "auth.ini"), QSettings.Format.IniFormat))


def wait_for(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


class Central:
    def __init__(self, mode="oidc"):
        self.mode = mode
        self.calls: list[str] = []

    def _r(self, status, body=None):
        return httpx.Response(status, json=body, request=httpx.Request("GET", BASE))

    def get(self, url, headers=None, timeout=None):
        path = url.removeprefix(BASE)
        self.calls.append(f"GET {path}")
        if path == "/api/v1/auth/config":
            cfg = {"enabled": True, "app_key": "SNVR", "mode": self.mode}
            if self.mode == "oidc":
                cfg |= {"issuer": ISSUER, "web_client_id": "snvr-web", "desktop_client_id": "snvr-desktop",
                        "scopes": "openid profile email"}
            return self._r(200, cfg)
        if path == "/api/v1/auth/me":
            return self._r(200, ME)
        return self._r(404, {"detail": "Not found"})

    def post(self, url, json=None, headers=None, timeout=None):
        path = url.removeprefix(BASE)
        self.calls.append(f"POST {path}")
        if path == "/api/v1/auth/logout":
            return self._r(204)
        if path == "/api/v1/auth/refresh":
            return self._r(200, {"access_token": "legacy-a", "refresh_token": "legacy-r", "expires_in": 600})
        return self._r(404, {"detail": "Not found"})


class AuthServer:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []
        self.n = 0
        self.refresh_status = 200
        self.omit_refresh = False

    def post(self, url, data=None, headers=None, timeout=None):
        path = url.removeprefix(ISSUER)
        self.calls.append((path, data))
        req = httpx.Request("POST", url)
        if path == "/oauth/token":
            if data["grant_type"] == "refresh_token" and self.refresh_status != 200:
                return httpx.Response(self.refresh_status, json={"error": "invalid_grant"}, request=req)
            self.n += 1
            body = {"access_token": f"a{self.n}", "refresh_token": f"r{self.n}", "expires_in": 600}
            if self.omit_refresh and data["grant_type"] == "refresh_token":
                body.pop("refresh_token")
            return httpx.Response(200, json=body, request=req)
        return httpx.Response(204 if path.endswith("logout") else 200, request=req)


class Browser:
    """Opens URLs like the system browser would: the Auth Server "signs in" and redirects to the loopback."""

    def __init__(self, answer="ok"):
        self.answer = answer
        self.opened: list[str] = []

    def __call__(self, url: str) -> bool:
        self.opened.append(url)
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        params = {"ok": {"code": "code-1", "state": q["state"], "iss": ISSUER},
                  "forged": {"code": "code-1", "state": "forged"},
                  "denied": {"error": "access_denied", "state": q["state"]}}.get(self.answer)
        if params is not None:
            threading.Thread(target=lambda: httpx.get(q["redirect_uri"], params=params, timeout=3), daemon=True).start()
        return True


def make(store, central=None, server=None, browser=None):
    central, server, browser = central or Central(), server or AuthServer(), browser or Browser()
    auth = AuthSession(BASE, store=store, post=central.post, get=central.get, oauth_post=server.post,
                       open_url=browser)
    return auth, central, server, browser


def test_oidc_config_shows_the_browser_sign_in(store):
    auth, *_ = make(store)
    auth.start()
    assert (auth.state, auth.mode, auth.issuerHost) == ("signed_out", "oidc", "auth.test")


@needs_dpapi
def test_browser_sign_in_end_to_end(store):
    auth, central, server, browser = make(store)
    raised = []
    auth.bringToFront.connect(lambda: raised.append(True))
    auth.start()
    auth.signInWithBrowser(True)
    assert browser.opened and auth.signInLink == browser.opened[0]
    assert "prompt=login" not in browser.opened[0]
    assert wait_for(lambda: auth.state == "signed_in"), auth.loginError
    assert auth.user["username"] == "op" and auth.token() == "a1" and raised == [True]
    path, form = server.calls[0]
    assert path == "/oauth/token" and form["grant_type"] == "authorization_code" and form["code"] == "code-1"
    assert form["client_id"] == "snvr-desktop" and form["code_verifier"]
    entry = store.load_entry(BASE)
    assert (entry["mode"], entry["issuer"], entry["client_id"], entry["refresh"]) == \
        ("oidc", ISSUER, "snvr-desktop", "r1")


def test_forged_or_denied_callback_is_refused(store):
    for answer, text in (("forged", "does not match"), ("denied", "no role")):
        auth, _, server, _ = make(store, browser=Browser(answer))
        auth.start()
        auth.signInWithBrowser(False)
        assert wait_for(lambda: auth.state == "signed_out" and auth.loginError), answer
        assert text in auth.loginError and server.calls == [] and auth.token() is None


@needs_dpapi
def test_stored_oidc_session_refreshes_at_the_auth_server(store):
    store.save_entry(BASE, "oidc", "r-old", ISSUER, "snvr-desktop")
    auth, central, server, _ = make(store)
    auth.start()
    assert auth.state == "signed_in" and server.calls[0][1]["refresh_token"] == "r-old"
    assert "POST /api/v1/auth/refresh" not in central.calls  # never through central on oidc
    assert store.load_entry(BASE)["refresh"] == "r1"
    server.omit_refresh = True  # grace window: the answer has no new refresh token, keep ours
    assert auth.refresh_after_expired(auth.token()) == "a2"
    app.processEvents()
    assert store.load_entry(BASE)["refresh"] == "r1"


@needs_dpapi
def test_entry_of_the_other_server_is_dropped(store):
    store.save_entry(BASE, "legacy", "legacy-token")
    auth, central, server, _ = make(store)
    auth.start()
    assert auth.state == "signed_out" and store.load_entry(BASE) is None and server.calls == []
    store.save_entry(BASE, "oidc", "r", "http://other-auth.test", "snvr-desktop")
    auth.start()
    assert auth.state == "signed_out" and store.load_entry(BASE) is None
    # and an oidc entry is never sent to central's legacy refresh
    store.save_entry(BASE, "oidc", "r", ISSUER, "snvr-desktop")
    legacy, lc, ls, _ = make(store, central=Central("legacy"))
    legacy.start()
    assert legacy.state == "signed_out" and "POST /api/v1/auth/refresh" not in lc.calls


@needs_dpapi
def test_revoked_refresh_ends_the_session(store):
    store.save_entry(BASE, "oidc", "r-old", ISSUER, "snvr-desktop")
    auth, _, server, _ = make(store)
    auth.start()
    server.refresh_status = 400
    with pytest.raises(Exception):
        auth.refresh_after_expired(auth.token())
    assert wait_for(lambda: auth.state == "signed_out") and "session ended" in auth.endedReason.lower()


@needs_dpapi
def test_sign_out_ends_this_login_and_forces_the_password_next_time(store):
    auth, central, server, browser = make(store)
    auth.start()
    auth.signInWithBrowser(True)
    assert wait_for(lambda: auth.state == "signed_in")
    server.calls.clear()
    auth.signOut()
    assert auth.state == "signed_out" and store.load_entry(BASE) is None and store.signed_out(BASE)
    assert "POST /api/v1/auth/logout" in central.calls
    assert [c[0] for c in server.calls] == ["/oauth/logout", "/oauth/revoke"]
    browser.answer = None  # just look at the next URL
    auth.signInWithBrowser(True)
    assert "prompt=login" in browser.opened[-1]
    auth.cancelBrowserSignIn()


def test_cancel_timeout_and_server_change(store, monkeypatch):
    auth, _, server, browser = make(store, browser=Browser(answer=None))
    auth.start()
    auth.signInWithBrowser(False)
    assert auth.state == "waiting_browser" and auth.waitingBrowser
    port = int(urlsplit(parse_qs(urlsplit(browser.opened[-1]).query)["redirect_uri"][0]).port)
    auth.cancelBrowserSignIn()
    assert auth.state == "signed_out" and auth.signInLink == ""
    assert wait_for(lambda: _closed(port))

    monkeypatch.setattr("app.core.auth.session.LoopbackListener",
                        functools.partial(oauth.LoopbackListener, ports=(free_port(),), timeout_s=0.2))
    auth.signInWithBrowser(False)
    assert wait_for(lambda: auth.state == "signed_out") and "not completed" in auth.loginError

    auth.signInWithBrowser(False)
    assert auth.state == "waiting_browser"
    auth.set_server("http://central-2.test")  # the flow belongs to the old server
    assert auth._flow is None and server.calls == []


def _closed(port: int) -> bool:
    try:
        httpx.get(f"http://127.0.0.1:{port}/callback", timeout=0.2)
        return False
    except httpx.HTTPError:
        return True


def test_busy_ports_show_a_message(store, monkeypatch):
    def busy(*a, **k):
        raise OSError("Could not start the sign-in listener (ports 5199/5198/5197 are in use)")

    monkeypatch.setattr("app.core.auth.session.LoopbackListener", busy)
    auth, _, _, browser = make(store)
    auth.start()
    auth.signInWithBrowser(False)
    assert auth.state == "signed_out" and "in use" in auth.loginError and browser.opened == []


def test_legacy_mode_is_unchanged(store):
    auth, central, _, browser = make(store, central=Central("legacy"))
    auth.start()
    assert (auth.state, auth.mode) == ("signed_out", "legacy")
    auth.signInWithBrowser(False)  # not available on legacy
    assert browser.opened == [] and auth.state == "signed_out"
