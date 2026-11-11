"""Desktop sign-in (docs/DESKTOP_AUTH_PLAN.md): permissions, the encrypted token store, the session state machine,
single-flight refresh, the API client's 401 handling, URL signing and log redaction."""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx
from PySide6.QtCore import QCoreApplication, QSettings

from app.core.api.central import CentralApi
from app.core.api.errors import ApiError
from app.core.auth import secure_store
from app.core.auth.permissions import CAMERA_READ, PAGE_PERMS, Perm, allows, start_page, summary_text
from app.core.auth.secure_store import TokenStore
from app.core.auth.session import AuthSession
from app.core.redact import redact
from app.core.store import BaseStore

app = QCoreApplication.instance() or QCoreApplication([])
BASE = "http://central.test"
ROOT = Path(__file__).resolve().parents[2]
ME = {"id": 7, "username": "op", "display_name": "Operator", "roles": ["Operator"], "permissions": [1, 2],
      "is_admin": False, "local": False, "scope": {"all_cameras": False, "groups": 1, "cameras": 0}}


def immediate(fn, ok=None, err=None):
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - mirrors run_task
        if err:
            err(exc)
    else:
        if ok:
            ok(result)


@pytest.fixture(autouse=True)
def sync_tasks(monkeypatch):
    monkeypatch.setattr("app.core.auth.session.run_task", immediate)


@pytest.fixture
def store(tmp_path):
    return TokenStore(QSettings(str(tmp_path / "auth.ini"), QSettings.Format.IniFormat))


def tokens(n: int = 1, expires_in: int = 600) -> dict:
    return {"access_token": f"access-{n}", "refresh_token": f"refresh-{n}", "token_type": "bearer",
            "expires_in": expires_in}


class FakeServer:
    """The central auth endpoints, as plain functions with the httpx.post / httpx.get signature."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.calls: list[tuple[str, dict | None]] = []
        self.refresh_count = 0
        self.refresh_status = 200
        self.login_status = 200
        self.lock = threading.Lock()

    def _response(self, status, body=None, headers=None):
        return httpx.Response(status, json=body, headers=headers or {}, request=httpx.Request("GET", BASE))

    def get(self, url, headers=None, timeout=None):
        path = url.removeprefix(BASE)
        self.calls.append((path, None))
        if path == "/api/v1/auth/config":
            return self._response(200, {"enabled": self.enabled, "app_key": "SNVR"})
        if path == "/api/v1/auth/me":
            return self._response(200, ME)
        return self._response(404, {"detail": "Not found"})

    def post(self, url, json=None, headers=None, timeout=None):
        path = url.removeprefix(BASE)
        self.calls.append((path, json))
        if path == "/api/v1/auth/login":
            if self.login_status != 200:
                return self._response(self.login_status, {"detail": "Invalid username or password"})
            return self._response(200, {**tokens(1), "user": ME})
        if path == "/api/v1/auth/refresh":
            time.sleep(0.05)  # long enough for concurrent callers to pile up on the lock
            with self.lock:
                self.refresh_count += 1
                n = self.refresh_count + 1
            if self.refresh_status != 200:
                return self._response(self.refresh_status, {"detail": "Refresh token reused"},
                                      {"X-Auth-Error": "refresh_failed"})
            return self._response(200, tokens(n))
        if path == "/api/v1/auth/logout":
            return self._response(204)
        return self._response(404, {"detail": "Not found"})


def session(server: FakeServer, store: TokenStore) -> AuthSession:
    return AuthSession(BASE, store=store, post=server.post, get=server.get)


# ---------------------------------------------------------------------- permissions
def test_permission_numbers_match_the_server_and_the_web_client():
    central = (ROOT / "central_manager/app/auth/permissions.py").read_text(encoding="utf-8")
    server = {name: int(value) for name, value in re.findall(r"^\s+([A-Z_]+) = (\d+)", central, re.M)}
    assert server == {p.name: p.value for p in Perm}
    web = (ROOT / "nvr_client/src/lib/auth/permissions.ts").read_text(encoding="utf-8")
    assert {n: int(v) for n, v in re.findall(r"^\s+([A-Z_]+): (\d+),", web, re.M)} == server
    policy = (ROOT / "central_manager/app/auth/policy.py").read_text(encoding="utf-8")
    server_camera_read = re.search(r"^CAMERA_READ = any_of\((.*)\)", policy, re.M).group(1)
    assert {server[n.strip().removeprefix("P.")] for n in server_camera_read.split(",")} == set(CAMERA_READ)


def test_pages_and_start_page():
    assert allows(False, [1], PAGE_PERMS["live"]) and not allows(False, [1], PAGE_PERMS["nodes"])
    assert allows(True, [], PAGE_PERMS["access"])  # admins pass everything
    assert start_page(False, [1, 2]) == "live"  # no dashboard permission: first allowed page
    assert start_page(False, [40, 1]) == "dashboard"
    assert start_page(False, []) == "settings"  # everyone may open Settings
    assert summary_text({"groups": 1, "cameras": 0}) == "1 group" and summary_text(None, True) == "Everything (admin)"


# ---------------------------------------------------------------------- encrypted token store
@pytest.mark.skipif(not secure_store.supported(), reason="DPAPI is Windows-only")
def test_token_store_encrypts_per_server(store, tmp_path):
    assert store.save(BASE, "secret-refresh")
    raw = (tmp_path / "auth.ini").read_text(encoding="utf-8")
    assert "secret-refresh" not in raw  # never in plain text
    assert store.load(BASE) == "secret-refresh"
    assert store.load("http://other.test") is None
    store.clear(BASE)
    assert store.load(BASE) is None


def test_damaged_stored_token_is_dropped(store):
    store._settings.setValue(f"auth/{secure_store.server_key(BASE)}/refresh", "bm90LWEtYmxvYg==")
    assert store.load(BASE) is None
    assert store._settings.value(f"auth/{secure_store.server_key(BASE)}/refresh") is None


# ---------------------------------------------------------------------- state machine
def test_auth_off_is_the_local_admin(store):
    auth = session(FakeServer(enabled=False), store)
    started = []
    auth.sessionStarted.connect(lambda: started.append(True))
    auth.start()
    assert auth.state == "disabled" and auth.ready and started == [True]
    assert auth.can(Perm.NODES_MANAGE) and auth.pages["access"] and not auth.token()


def test_auth_on_without_a_stored_session_shows_the_login(store):
    auth = session(FakeServer(), store)
    auth.start()
    assert auth.state == "signed_out" and not auth.ready and not auth.can(Perm.LIVE)


def test_unreachable_server(store):
    def down(*_a, **_kw):
        raise httpx.ConnectError("refused")

    auth = AuthSession(BASE, store=store, post=down, get=down)
    auth.start()
    assert auth.state == "unreachable" and "Cannot reach central" in auth.loginError


@pytest.mark.skipif(not secure_store.supported(), reason="DPAPI is Windows-only")
def test_stored_session_signs_in_silently_and_rotates_the_stored_token(store):
    store.save(BASE, "refresh-old")
    server = FakeServer()
    auth = session(server, store)
    auth.start()
    assert auth.state == "signed_in" and auth.user["username"] == "op"
    assert ("/api/v1/auth/refresh", {"refresh_token": "refresh-old"}) in server.calls
    assert store.load(BASE) == "refresh-2"  # the rotated token replaced the used one


def test_sign_in_and_permissions(store):
    server = FakeServer()
    auth = session(server, store)
    auth.start()
    auth.signIn("op", "pw", False)
    assert auth.state == "signed_in" and auth.token() == "access-1"
    assert auth.can(Perm.LIVE) and not auth.can(Perm.NODES_MANAGE)
    assert auth.pages["live"] and not auth.pages["nodes"] and auth.pages["settings"]
    assert auth.start_page() == "live" and auth.scopeText == "1 group"
    assert store.load(BASE) is None  # "Keep me signed in" off: nothing stored
    assert store.last_username(BASE) == "op"


def test_wrong_password(store):
    server = FakeServer()
    server.login_status = 401
    auth = session(server, store)
    auth.start()
    auth.signIn("op", "nope", False)
    assert auth.state == "signed_out" and auth.loginError == "Invalid username or password"


def test_single_flight_refresh(store):
    """Ten threads see an expired token at once: one network refresh, everyone gets the new token."""
    server = FakeServer()
    auth = session(server, store)
    auth.start()
    auth.signIn("op", "pw", False)
    results, errors = [], []

    def worker():
        try:
            results.append(auth.refresh_after_expired("access-1"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and server.refresh_count == 1 and set(results) == {"access-2"}


def test_failed_refresh_ends_the_session(store):
    server = FakeServer()
    auth = session(server, store)
    auth.start()
    auth.signIn("op", "pw", False)
    server.refresh_status = 401
    ended = []
    auth.sessionEnded.connect(lambda: ended.append(True))
    with pytest.raises(ApiError) as err:
        auth.refresh_after_expired("access-1")
    assert err.value.code == "refresh_failed"
    assert auth.state == "signed_out" and ended == [True] and "session ended" in auth.endedReason.lower()
    assert auth.token() is None


def test_server_ends_the_session(store):
    auth = session(FakeServer(), store)
    auth.start()
    auth.signIn("op", "pw", False)
    auth.report("token_revoked")
    assert auth.state == "signed_out" and auth.token() is None
    auth.signIn("op", "pw", False)
    auth.report("no_access")
    assert auth.endedReason == "Your account no longer has access to Shah-NVR."


def test_auth_switched_on_while_running(store):
    auth = session(FakeServer(enabled=False), store)
    auth.start()
    auth.report("missing")
    assert auth.state == "signed_out" and auth.enabled and "required" in auth.endedReason


def test_sign_out_calls_logout_and_clears(store):
    server = FakeServer()
    auth = session(server, store)
    auth.start()
    auth.signIn("op", "pw", True)
    auth.signOut()
    assert "/api/v1/auth/logout" in [path for path, _ in server.calls]
    assert auth.state == "signed_out" and auth.token() is None and store.load(BASE) is None


def test_sign_url_only_for_playback_and_exports(store):
    auth = session(FakeServer(), store)
    auth.start()
    auth.signIn("op", "pw", False)
    assert auth.sign_url(f"{BASE}/api/v1/playback/1/index.m3u8?profile=main") \
        == f"{BASE}/api/v1/playback/1/index.m3u8?profile=main&access_token=access-1"
    assert auth.sign_url(f"{BASE}/api/v1/exports/x/download").endswith("?access_token=access-1")
    assert auth.sign_url(f"{BASE}/api/v1/cameras") == f"{BASE}/api/v1/cameras"
    assert auth.sign_url("rtsp://node:8554/cam-1/main") == "rtsp://node:8554/cam-1/main"  # never to other hosts
    assert redact("x?a=1&access_token=abc.def&b=2") == "x?a=1&access_token=***&b=2"


# ---------------------------------------------------------------------- API client
class Tokens:
    def __init__(self):
        self.current, self.reported, self.refreshes = "old", [], 0

    def token(self):
        return self.current

    def valid_token(self):
        return self.current

    def refresh_after_expired(self, stale):
        self.refreshes += 1
        self.current = "new"
        return self.current

    def report(self, code):
        self.reported.append(code)


@respx.mock
def test_api_sends_the_token_and_retries_once_after_a_refresh():
    tokens_ = Tokens()
    route = respx.get(f"{BASE}/api/v1/auth/me").mock(side_effect=[
        httpx.Response(401, json={"detail": "Session expired"}, headers={"X-Auth-Error": "token_expired"}),
        httpx.Response(200, json=ME)])
    assert CentralApi(BASE, tokens_).me()["username"] == "op"
    assert [c.request.headers["Authorization"] for c in route.calls] == ["Bearer old", "Bearer new"]
    assert tokens_.refreshes == 1 and tokens_.reported == []


@respx.mock
def test_api_reports_a_session_ending_401_without_retry():
    tokens_ = Tokens()
    route = respx.get(f"{BASE}/api/v1/auth/me").mock(return_value=httpx.Response(
        401, json={"detail": "Session ended"}, headers={"X-Auth-Error": "token_revoked"}))
    with pytest.raises(ApiError) as err:
        CentralApi(BASE, tokens_).me()
    assert err.value.status == 401 and err.value.code == "token_revoked"
    assert route.call_count == 1 and tokens_.reported == ["token_revoked"] and tokens_.refreshes == 0


@respx.mock
def test_api_retries_while_central_loads_the_users(monkeypatch):
    monkeypatch.setattr("app.core.api.central.time.sleep", lambda s: None)
    route = respx.get(f"{BASE}/api/v1/auth/me").mock(side_effect=[
        httpx.Response(503, json={"detail": "syncing"}, headers={"X-Auth-Error": "auth_syncing"}),
        httpx.Response(200, json=ME)])
    assert CentralApi(BASE, Tokens()).me()["id"] == 7 and route.call_count == 2


@respx.mock
def test_api_without_a_session_sends_no_header():
    route = respx.get(f"{BASE}/api/v1/auth/me").mock(return_value=httpx.Response(200, json=ME))
    CentralApi(BASE).me()
    assert "Authorization" not in route.calls.last.request.headers


# ---------------------------------------------------------------------- stores
def test_stores_fetch_nothing_while_nobody_is_signed_in(monkeypatch):
    called = []
    monkeypatch.setattr("app.core.store.run_task", lambda *a, **kw: called.append(True))
    ctx = SimpleNamespace(ready=False, can=lambda *p: False)
    store = BaseStore(ctx)
    store.fetch("x", lambda: 1, lambda r: None)
    assert called == [] and not store.allowed(1)
    ctx.ready = True
    store.fetch("x", lambda: 1, lambda r: None)
    assert called == [True]


def test_live_grid_is_kept_per_user(tmp_path, monkeypatch):
    from app.core.preferences import Preferences

    prefs = Preferences()
    prefs._store = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    prefs.save_live_layout(9, [1, 2] + [None] * 14)
    prefs.set_profile("server-7")
    assert prefs.live_layout() == (4, [None] * 16)  # a new user starts empty
    prefs.save_live_layout(1, [5] + [None] * 15)
    prefs.set_profile("")
    assert prefs.live_layout()[0] == 9  # auth off: the shared grid as before


def test_a_second_launch_activates_the_first(monkeypatch):
    import uuid

    from app.core import single_instance

    monkeypatch.setattr(single_instance, "_name", lambda: f"ShahNVR-test-{uuid.uuid4().hex}")
    name = single_instance._name()
    monkeypatch.setattr(single_instance, "_name", lambda: name)
    assert not single_instance.SingleInstance.notify_running()  # nobody listens yet
    first = single_instance.SingleInstance()
    activated = []
    first.activated.connect(lambda: activated.append(True))
    first.listen()
    assert single_instance.SingleInstance.notify_running()
    end = time.monotonic() + 2
    while not activated and time.monotonic() < end:
        app.processEvents()
    assert activated
