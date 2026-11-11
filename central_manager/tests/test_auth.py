"""Auth integration (docs/AUTH_INTEGRATION_PLAN.md): every route has a rule, the switch, token checks
(signature, type, app, expiry, revocation, active user), permission numbers, camera scope through groups,
the access and audit APIs, and the Auth Server proxy. A fake Auth Server (httpx MockTransport); no network."""

import json
import time

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import integration
from app.auth.integration import AuthRuntime, AuthServer, parse_events, parse_user
from app.auth.policy import rule_for
from app.auth.state import AuthUser, MemoryAuthStateStore
from settings.settings import settings

KEY = "test-signing-key-0123456789-abcdefghijklmnop"
STREAM = [{"profile": "main", "source_url": "rtsp://1.2.3.4/x", "record": True}]


def token(user_id=1, perms=("*",), roles=("Admin",), ver=1, app="SNVR", typ="access", exp=None, key=KEY):
    claims = {"sub": f"user{user_id}", "user_id": user_id, "app": app, "perms": list(perms), "roles": list(roles),
              "ver": ver, "exp": int(exp if exp is not None else time.time() + 600), "type": typ}
    return jwt.encode(claims, key, algorithm="HS256")


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


class FakeAuthServer:
    """What the Auth Server answers (login / refresh / logout / internal users)."""

    def __init__(self):
        self.users = [
            {"user": {"id": 1, "username": "shah", "is_active": True, "is_superuser": True, "token_version": 1},
             "roles": [{"id": 22, "name": "Admin"}], "permissions": [{"id": 15, "code": "*"}]},
            {"user": {"id": 2, "username": "guard", "is_active": True, "is_superuser": False, "token_version": 1,
                      "first_name": "Night", "last_name": "Guard"},
             "roles": [{"id": 30, "name": "Viewer"}], "permissions": [{"id": 16, "code": "1"}]},
            {"user": {"id": 3, "username": "gone", "is_active": False, "is_superuser": False, "token_version": 1},
             "roles": [], "permissions": []},
        ]
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path, request.content.decode() if request.content else ""))
        if path == "/login/":
            body = json.loads(request.content)
            if body["password"] != "pw":
                return httpx.Response(401, json={"detail": "Invalid credentials"})
            return httpx.Response(200, json={
                "access_token": token(2, perms=("1", "2", "40"), roles=("Viewer",)), "refresh_token": "r1",
                "token_type": "bearer", "expires_in": 600, "app_key": body["app_key"],
                "user": {"id": 2, "username": body["username"], "first_name": "Night", "last_name": "Guard"},
                "roles": ["Viewer"], "permissions": ["1", "2", "40"]})
        if path == "/refresh":
            return httpx.Response(200, json={"access_token": "a2", "refresh_token": "r2", "expires_in": 600,
                                             "app_key": "SNVR"})
        if path == "/logout":
            return httpx.Response(200, json={})
        if path == "/internal/v1/users/SNVR":
            return httpx.Response(200, json=self.users)
        if path == "/internal/v1/service-token":
            return httpx.Response(200, json={"access_token": "svc", "expires_in": 900, "token_type": "bearer",
                                             "scope": "auth.users.read", "app_key": "SNVR"})
        return httpx.Response(404, json={"detail": "not found"})


class FakeRuntime(AuthRuntime):
    def start(self):  # no background loops in tests: the snapshot is loaded by hand
        pass


@pytest.fixture
def auth_on(monkeypatch):
    import main

    fake = FakeAuthServer()
    store = MemoryAuthStateStore()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://auth")
    runtime = FakeRuntime(store, AuthServer(store, http=http))
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_KEY", KEY)
    monkeypatch.setattr(settings, "AUTH_CLIENT_SECRET", "secret")
    monkeypatch.setattr(main, "create_runtime", lambda: runtime)
    server = runtime.server

    async def refresh_now(wait: float = 3.0):  # no background loop in tests: fetch at once
        await server.fetch_users()

    monkeypatch.setattr(server, "refresh_users_now", refresh_now)
    with TestClient(main.app) as client:
        client.portal.call(server.fetch_service_token)
        client.portal.call(server.fetch_users)  # first users snapshot (versions + active flags)
        yield client, runtime, fake


def test_every_route_has_an_access_rule():
    import main

    missing = [(m.upper(), path) for path, ops in main.app.openapi()["paths"].items() for m in ops
               if rule_for(m, path) is None]
    assert missing == [], f"routes without a rule in app/auth/policy.py: {missing}"


def test_auth_off_is_open_as_before():
    import main

    with TestClient(main.app) as c:
        assert c.get("/api/v1/auth/config").json() == {"enabled": False, "app_key": "SNVR"}
        me = c.get("/api/v1/auth/me").json()
        assert me["local"] and me["is_admin"] and me["scope"]["all_cameras"]
        assert c.post("/api/v1/cameras", json={"name": "Gate", "streams": STREAM}).status_code == 201
        assert c.post("/api/v1/auth/login", json={"username": "a", "password": "b"}).status_code == 409


def test_token_checks(auth_on):
    c, runtime, _ = auth_on
    ok = c.get("/api/v1/auth/me", headers=auth(token()))
    assert ok.status_code == 200 and ok.json()["username"] == "user1" and ok.json()["is_admin"]
    r = c.get("/api/v1/cameras/options")
    assert r.status_code == 401 and r.headers["x-auth-error"] == "missing"
    cases = {
        "invalid_token": token(key="another-key-0123456789-0123456789-xyz"),
        "wrong_app": token(app="AUTH"),
        "token_expired": token(exp=time.time() - 120),
    }
    for code, tok in cases.items():
        r = c.get("/api/v1/cameras/options", headers=auth(tok))
        assert r.status_code == 401 and r.headers["x-auth-error"] == code, (code, r.text)
    r = c.get("/api/v1/cameras/options", headers=auth(token(typ="refresh")))
    assert r.status_code == 401
    r = c.get("/api/v1/cameras/options", headers=auth(token(user_id=3)))
    assert r.status_code == 401 and r.headers["x-auth-error"] == "inactive"
    r = c.get("/api/v1/cameras/options", headers=auth(token(user_id=99)))
    assert r.status_code == 401 and r.headers["x-auth-error"] == "no_access"
    # unsigned / alg=none tokens never pass
    none_tok = jwt.encode({"user_id": 1, "app": "SNVR", "type": "access", "ver": 1, "exp": time.time() + 60},
                          None, algorithm="none")
    assert c.get("/api/v1/cameras/options", headers=auth(none_tok)).status_code == 401


def test_revocation_by_token_version(auth_on):
    c, runtime, _ = auth_on
    old = token(ver=1)
    assert c.get("/api/v1/auth/me", headers=auth(old)).status_code == 200
    c.portal.call(runtime.store.set_token_versions, {1: 2})  # logout / password / role change arrives over SSE
    r = c.get("/api/v1/auth/me", headers=auth(old))
    assert r.status_code == 401 and r.headers["x-auth-error"] == "token_revoked"
    assert c.get("/api/v1/auth/me", headers=auth(token(ver=2))).status_code == 200
    # an older snapshot cannot bring the old version back
    c.portal.call(runtime.server.fetch_users)
    assert c.get("/api/v1/auth/me", headers=auth(old)).status_code == 401


def test_syncing_answers_503(auth_on, monkeypatch):
    c, runtime, _ = auth_on
    monkeypatch.setattr(runtime.store, "_ready", False)
    r = c.get("/api/v1/auth/me", headers=auth(token()))
    assert r.status_code == 503 and r.headers["x-auth-error"] == "auth_syncing"


def test_permission_numbers(auth_on):
    c, _, _ = auth_on
    admin, viewer = auth(token()), auth(token(user_id=2, perms=("1", "2", "40"), roles=("Viewer",)))
    cam = c.post("/api/v1/cameras", json={"name": "Gate", "streams": STREAM}, headers=admin).json()
    r = c.post("/api/v1/cameras", json={"name": "X", "streams": STREAM}, headers=viewer)
    assert r.status_code == 403 and r.headers["x-auth-error"] == "forbidden"
    assert c.get("/api/v1/nodes/1/volumes", headers=viewer).status_code == 403
    assert c.get("/api/v1/audit", headers=viewer).status_code == 403
    me = c.get("/api/v1/auth/me", headers=viewer).json()
    assert me["permissions"] == [1, 2, 40] and not me["is_admin"]
    # viewer has no grants yet: no cameras at all
    assert c.get("/api/v1/cameras/options", headers=viewer).json()["total"] == 0
    assert c.get(f"/api/v1/cameras/{cam['id']}", headers=viewer).status_code == 404


def test_camera_scope_through_groups(auth_on):
    c, _, _ = auth_on
    admin, viewer = auth(token()), auth(token(user_id=2, perms=("1", "2", "3", "40"), roles=("Viewer",)))
    a = c.post("/api/v1/groups", json={"name": "Anantnag"}, headers=admin).json()
    b = c.post("/api/v1/groups", json={"name": "Bijbehara", "parent_id": a["id"]}, headers=admin).json()
    j = c.post("/api/v1/groups", json={"name": "Jammu"}, headers=admin).json()
    in_b = c.post("/api/v1/cameras", json={"name": "Gate", "streams": STREAM, "group_id": b["id"]}, headers=admin).json()
    in_j = c.post("/api/v1/cameras", json={"name": "Tawi", "streams": STREAM, "group_id": j["id"]}, headers=admin).json()
    loose = c.post("/api/v1/cameras", json={"name": "Loose", "streams": STREAM}, headers=admin).json()
    # role Viewer may see Anantnag (and its sub-groups); user guard also gets the loose camera
    r = c.put("/api/v1/access/grants", json={"subject_type": "role", "subject": "Viewer", "group_ids": [a["id"]]},
              headers=admin)
    assert r.status_code == 200 and r.json()["groups"] == [{"id": a["id"], "name": "Anantnag"}]
    c.put("/api/v1/access/grants", json={"subject_type": "user", "subject": "2", "camera_ids": [loose["id"]]},
          headers=admin)
    names = [x["name"] for x in c.get("/api/v1/cameras/options", headers=viewer).json()["items"]]
    assert names == ["Gate", "Loose"]
    assert c.get(f"/api/v1/cameras/{in_j['id']}", headers=viewer).status_code == 404
    assert c.get(f"/api/v1/cameras/{in_j['id']}/recordings", headers=viewer,
                 params={"profile": "main", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"}).status_code == 404
    assert c.get(f"/api/v1/cameras/{in_b['id']}", headers=viewer).status_code == 200
    top = c.get("/api/v1/groups", headers=viewer).json()
    assert [g["name"] for g in top["items"]] == ["Anantnag"] and top["items"][0]["cameras_total"] == 1
    assert c.get(f"/api/v1/groups/{j['id']}", headers=viewer).status_code == 404
    assert [g["name"] for g in c.get("/api/v1/groups/search", params={"q": "a"}, headers=viewer).json()["items"]] == \
        ["Anantnag", "Bijbehara"]
    alerts = c.get("/api/v1/cluster/alerts", headers=viewer).json()  # every camera is unassigned (no nodes)
    assert {x["camera_name"] for x in alerts["items"]} == {"Gate", "Loose"}
    summary = c.get("/api/v1/access/grants", headers=admin).json()
    assert {(s["subject_type"], s["subject"], s["groups"], s["cameras"]) for s in summary} == \
        {("role", "Viewer", 1, 0), ("user", "2", 0, 1)}
    subjects = c.get("/api/v1/access/subjects", headers=admin).json()
    assert "Viewer" in subjects["roles"] and {u["username"] for u in subjects["users"]} == {"shah", "guard", "gone"}
    # all cameras grant
    c.put("/api/v1/access/grants", json={"subject_type": "role", "subject": "Viewer", "all_cameras": True}, headers=admin)
    assert c.get("/api/v1/cameras/options", headers=viewer).json()["total"] == 3


def test_query_token_only_where_allowed(auth_on):
    c, _, _ = auth_on
    tok = token()
    cam = c.post("/api/v1/cameras", json={"name": "Gate", "streams": STREAM}, headers=auth(tok)).json()
    assert c.get("/api/v1/cameras/options", params={"access_token": tok}).status_code == 401
    r = c.get(f"/api/v1/playback/{cam['id']}/index.m3u8",
              params={"access_token": tok, "profile": "main", "start": "2026-01-01T00:00:00Z",
                      "end": "2026-01-01T00:10:00Z"})
    assert r.status_code != 401  # authenticated (404/200 depends on recordings)


def test_audit_log(auth_on):
    c, _, _ = auth_on
    admin, viewer = auth(token()), auth(token(user_id=2, perms=("1",), roles=("Viewer",)))
    c.post("/api/v1/cameras", json={"name": "Gate", "streams": STREAM}, headers=admin)
    c.post("/api/v1/cameras", json={"name": "Nope", "streams": STREAM}, headers=viewer)  # denied
    events = c.get("/api/v1/audit", headers=admin).json()["items"]
    assert [(e["action"], e["status"], e["username"]) for e in events][:2] == [
        ("cameras.create", "denied", "user2"), ("cameras.create", "ok", "user1")]
    only_denied = c.get("/api/v1/audit", params={"status": "denied"}, headers=admin).json()
    assert only_denied["total"] == 1


def test_login_refresh_logout_proxy(auth_on):
    c, _, fake = auth_on
    r = c.post("/api/v1/auth/login", json={"username": "guard", "password": "pw"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["display_name"] == "Night Guard" and body["user"]["permissions"] == [1, 2, 40]
    assert json.loads(fake.calls[-1][2])["app_key"] == "SNVR"  # forced, whatever the client sends
    assert c.post("/api/v1/auth/login", json={"username": "guard", "password": "x"}).status_code == 401
    assert c.post("/api/v1/auth/refresh", json={"refresh_token": "r1"}).json()["refresh_token"] == "r2"
    assert c.post("/api/v1/auth/logout", headers=auth(body["access_token"])).status_code == 204
    actions = [e["action"] for e in c.get("/api/v1/audit", headers=auth(token())).json()["items"]]
    assert actions[:3] == ["auth.logout", "auth.login", "auth.login"]


def test_auth_server_parsing_and_store():
    assert parse_events('[{"user_id": 4, "token_version": 7}]') == {4: 7}
    assert parse_events('{"user_id": "5", "token_version": "2"}') == {5: 2}
    assert parse_events("[]") == {} and parse_events("not json") == {}
    u = parse_user({"user": {"id": 9, "username": "x", "is_active": True, "token_version": 3},
                    "roles": [{"name": "Viewer"}], "permissions": [{"code": "1"}]})
    assert (u.id, u.roles, u.permissions, u.token_version) == (9, ("Viewer",), ("1",), 3)


@pytest.mark.anyio
async def test_memory_store_versions_only_grow_and_removed_users_go():
    s = MemoryAuthStateStore()
    assert not await s.ready()
    await s.replace_users([AuthUser(id=1, username="a", token_version=5), AuthUser(id=2, username="b", token_version=1)])
    await s.set_token_versions({1: 7})
    await s.replace_users([AuthUser(id=1, username="a", token_version=6)])  # older snapshot
    assert await s.get_token_version(1) == 7 and await s.get_user(2) is None and await s.get_token_version(2) is None
    await s.set_service_token("t", 0)
    assert await s.get_service_token() is None  # expired at once


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_runtime_is_not_left_behind():
    assert integration.get_runtime() is None
