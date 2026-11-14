"""Browser sign-in pieces (docs/DESKTOP_AUTH_V2_PLAN.md): PKCE, the authorize URL, callback checks, the loopback
listener and the Auth Server token calls (fake server, no network, no Qt)."""

from __future__ import annotations

import base64
import hashlib
import socket
import threading
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.auth import oauth
from app.core.auth.oauth import LoopbackListener, OAuthError, OidcConfig, Pkce

CFG = OidcConfig("http://auth.test", "snvr-desktop", "openid profile email")


def free_ports(n: int) -> tuple[int, ...]:
    socks = [socket.socket() for _ in range(n)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = tuple(s.getsockname()[1] for s in socks)
    for s in socks:
        s.close()
    return ports


def test_pkce_values():
    p = Pkce()
    assert 43 <= len(p.verifier) <= 128 and "=" not in p.verifier and "+" not in p.verifier
    expected = base64.urlsafe_b64encode(hashlib.sha256(p.verifier.encode()).digest()).rstrip(b"=").decode()
    assert p.challenge == expected and p.state != Pkce().state


def test_config_from_central():
    assert OidcConfig.from_config({"issuer": "http://a/", "desktop_client_id": "d", "scopes": "openid"}) == \
        OidcConfig("http://a", "d", "openid")
    assert OidcConfig.from_config({"issuer": None, "desktop_client_id": "d"}) is None


def test_authorize_url():
    p = Pkce()
    q = parse_qs(urlsplit(oauth.authorize_url(CFG, 5199, p)).query)
    assert {k: v[0] for k, v in q.items()} == {
        "response_type": "code", "client_id": "snvr-desktop", "redirect_uri": "http://127.0.0.1:5199/callback",
        "scope": "openid profile email", "state": p.state, "code_challenge": p.challenge,
        "code_challenge_method": "S256"}
    assert "prompt=login" in oauth.authorize_url(CFG, 5199, p, force_login=True)


def test_check_callback():
    p = Pkce()
    assert oauth.check_callback({"code": "c1", "state": p.state, "iss": "http://auth.test"}, p, CFG) == "c1"
    cases = {
        "access_denied": {"error": "access_denied", "state": p.state},
        "invalid_state": {"code": "c", "state": "forged"},
        "invalid_issuer": {"code": "c", "state": p.state, "iss": "http://evil.test"},
        "invalid_request": {"state": p.state},
    }
    for code, params in cases.items():
        with pytest.raises(OAuthError) as e:
            oauth.check_callback(params, p, CFG)
        assert e.value.code == code
    with pytest.raises(OAuthError, match="no role"):
        oauth.check_callback(cases["access_denied"], p, CFG)


class FakeAuthServer:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.token_answer = {"access_token": "a1", "refresh_token": "r1", "expires_in": 600}
        self.token_status = 200

    def post(self, url, data=None, headers=None, timeout=None, json=None):
        self.calls.append((url.removeprefix(CFG.issuer), {"data": data, "headers": headers}))
        request = httpx.Request("POST", url)
        if url.endswith("/oauth/token"):
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant", "error_description": "bad"},
                                      request=request)
            return httpx.Response(200, json=self.token_answer, request=request)
        return httpx.Response(204 if url.endswith("/logout") else 200, request=request)


def test_exchange_refresh_and_end_login():
    fake, p = FakeAuthServer(), Pkce()
    assert oauth.exchange_code(CFG, "code1", p, 5198, post=fake.post)["refresh_token"] == "r1"
    path, sent = fake.calls[-1]
    assert path == "/oauth/token" and sent["data"] == {
        "grant_type": "authorization_code", "code": "code1", "redirect_uri": "http://127.0.0.1:5198/callback",
        "code_verifier": p.verifier, "client_id": "snvr-desktop"}

    fake.token_answer = {"access_token": "a2", "expires_in": 600}  # grace window: no new refresh token
    assert oauth.refresh(CFG, "r1", post=fake.post)["refresh_token"] == "r1"
    fake.token_status = 400
    with pytest.raises(OAuthError) as e:
        oauth.refresh(CFG, "r1", post=fake.post)
    assert (e.value.status, e.value.code) == (400, "invalid_grant")

    fake.calls.clear()
    oauth.end_login(CFG, "a2", "r1", post=fake.post)
    assert [c[0] for c in fake.calls] == ["/oauth/logout", "/oauth/revoke"]
    assert fake.calls[0][1]["headers"] == {"Authorization": "Bearer a2"}
    assert fake.calls[1][1]["data"] == {"token": "r1", "client_id": "snvr-desktop"}


def test_exchange_without_refresh_token_and_unreachable():
    fake = FakeAuthServer()
    fake.token_answer = {"access_token": "a", "expires_in": 600}
    with pytest.raises(OAuthError, match="no refresh token"):
        oauth.exchange_code(CFG, "c", Pkce(), 5199, post=fake.post)

    def down(*a, **k):
        raise httpx.ConnectError("refused")

    with pytest.raises(OAuthError) as e:
        oauth.refresh(CFG, "r", post=down)
    assert e.value.status == 0
    oauth.end_login(CFG, "a", "r", post=down)  # never raises


def test_listener_answers_one_callback_then_closes():
    got: list = []
    done = threading.Event()
    listener = LoopbackListener(lambda r: (got.append(r), done.set()), ports=free_ports(1)).start()
    base = f"http://127.0.0.1:{listener.port}"
    assert httpx.get(f"{base}/other").status_code == 404
    r = httpx.get(f"{base}/callback", params={"code": "c", "state": "s"})
    assert r.status_code == 200 and "Signed in" in r.text
    assert done.wait(2) and got == [{"code": "c", "state": "s"}] and listener.done
    for _ in range(20):  # the socket closes shortly after
        try:
            httpx.get(f"{base}/callback", timeout=0.2)
        except httpx.HTTPError:
            break
        threading.Event().wait(0.05)
    else:
        pytest.fail("listener still answering")


def test_listener_falls_back_to_next_port_and_reports_busy():
    a, b = free_ports(2)
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", a))
    blocker.listen()
    try:
        listener = LoopbackListener(lambda r: None, ports=(a, b))
        assert listener.port == b
        listener.close()
        with pytest.raises(OSError, match="in use"):
            LoopbackListener(lambda r: None, ports=(a,))
    finally:
        blocker.close()


def test_listener_timeout_and_close():
    got: list = []
    done = threading.Event()
    LoopbackListener(lambda r: (got.append(r), done.set()), ports=free_ports(1), timeout_s=0.2).start()
    assert done.wait(2) and got == [None]

    called: list = []
    listener = LoopbackListener(called.append, ports=free_ports(1)).start()
    threading.Thread(target=listener.close).start()
    threading.Event().wait(0.3)
    assert listener.done and called == []  # close() never reports a result
    listener.close()  # idempotent


def test_listener_error_page():
    got: list = []
    done = threading.Event()
    listener = LoopbackListener(lambda r: (got.append(r), done.set()), ports=free_ports(1)).start()
    r = httpx.get(f"http://127.0.0.1:{listener.port}/callback", params={"error": "access_denied", "state": "s"})
    assert "did not finish" in r.text and "no role" in r.text
    assert done.wait(2) and got[0]["error"] == "access_denied"
