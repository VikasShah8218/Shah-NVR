"""AUTH_PROVIDER=oidc (docs/AUTH_V2_PLAN.md): the new Auth Server through auth_sdk.

A fake Auth Server (httpx MockTransport) signs real ES256 tokens and events, so the real SDK verifies them:
permission codes -> numbers, names from the members directory, error codes, revocation by event, role grants
stored by role id (survive a rename), grants of the other provider ignored, audit rows with the UUID."""

import base64
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

auth_sdk = pytest.importorskip("auth_sdk")
from joserfc import jwt  # noqa: E402
from joserfc.jwk import ECKey  # noqa: E402

from app.auth.oidc import OidcProvider  # noqa: E402
from settings.settings import settings  # noqa: E402

ISSUER = "http://auth.test"
APP = "SNVR"
STREAM = [{"profile": "main", "source_url": "rtsp://1.2.3.4/x", "record": True}]
ADMIN_SUB, GUARD_SUB = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
ROLE_ADMIN, ROLE_VIEWER = "aaaaaaaa-0000-0000-0000-000000000001", "aaaaaaaa-0000-0000-0000-000000000002"
BITS = {"*": 0, "live.view": 1, "playback.view": 2, "camera.manage": 3, "access.manage": 4, "audit.view": 5}


def mask(*codes: str) -> str:
    value = sum(1 << BITS[c] for c in codes)
    return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "little")).rstrip(b"=").decode()


class FakeAuthServer:
    def __init__(self):
        self.key = ECKey.generate_key("P-256", parameters={"kid": "k1"}, private=True)
        self.seq = 0
        self.queued: list[str] = []
        self.roles = [
            {"id": ROLE_ADMIN, "name": "Admin", "description": "Full access", "permissions": ["*"]},
            {"id": ROLE_VIEWER, "name": "Viewer", "description": None, "permissions": ["live.view", "playback.view"]},
        ]
        self.members = [
            {"sub": ADMIN_SUB, "username": "shah", "given_name": "Vikas", "family_name": "Shah", "email": None,
             "is_active": True, "roles": [{"id": ROLE_ADMIN, "name": "Admin"}]},
            {"sub": GUARD_SUB, "username": "guard", "given_name": "Night", "family_name": "Guard", "email": None,
             "is_active": True, "roles": [{"id": ROLE_VIEWER, "name": "Viewer"}]},
        ]

    def sign(self, claims: dict, typ: str = "at+jwt", lifetime: int = 600, now: int | None = None) -> str:
        now = int(now if now is not None else time.time())
        payload = {"iss": ISSUER, "iat": now, "exp": now + lifetime, **claims}
        return jwt.encode({"alg": "ES256", "typ": typ, "kid": "k1"}, payload, self.key, algorithms=["ES256"])

    def token(self, sub=ADMIN_SUB, codes=("*",), roles=("Admin",), sid="sid-1", aud=APP, **kw) -> str:
        claims = {"aud": aud, "sub": sub, "sid": sid, "ver": 1, "token_use": "user", "pm": mask(*codes), "pv": 1,
                  "roles": list(roles), "client_id": "snvr-web"}
        return self.sign(claims, **kw)

    def publish(self, type: str, payload: dict) -> None:
        self.seq += 1
        signed = self.sign({"aud": APP, "seq": self.seq, "type": type, "payload": payload}, typ="event+jwt")
        self.queued.append(f"id: {self.seq}\nevent: {type}\ndata: {signed}\n\n")

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/jwks.json":
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "svc", "token_type": "Bearer", "expires_in": 900})
        if path == f"/v1/apps/{APP}/permission-map":
            return httpx.Response(200, json={"version": 1, "permissions": [
                {"code": c, "bit": b, "retired": False} for c, b in BITS.items()]})
        if path == f"/v1/apps/{APP}/roles":
            return httpx.Response(200, json=self.roles)
        if path == f"/v1/apps/{APP}/members":
            return httpx.Response(200, json={"items": self.members, "next_cursor": None})
        if path == f"/v1/events/{APP}/snapshot":
            return httpx.Response(200, json={"seq": self.seq, "perm_map_version": 1, "users": [],
                                             "revoked_sessions": [], "revoked_clients": []})
        if path == f"/v1/events/{APP}/ack":
            return httpx.Response(204)
        if path == f"/v1/events/{APP}":
            after = int(request.url.params["after"])
            frames = [f for f in self.queued if int(f.split("\n")[0][4:]) > after]
            return httpx.Response(200, content=("".join(frames) + ": keep-alive\n\n").encode(),
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(404)


class SyncedProvider(OidcProvider):
    """No background loops: the test syncs by hand (one pass of the event stream, one directory load)."""

    async def start(self):
        await self.sync()
        await self.reload_directory()

    async def sync(self):
        await self.sdk._follow_events()

    async def stop(self):
        await self.sdk._http.aclose()


@pytest.fixture
def oidc(monkeypatch, tmp_path):
    import main

    fake = FakeAuthServer()
    sdk = auth_sdk.AuthSDK(ISSUER, APP, "snvr-a", "secret", transport=httpx.MockTransport(fake.handle))
    provider = SyncedProvider(sdk, str(tmp_path / "auth-roles.json"))
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "oidc")
    monkeypatch.setattr(settings, "AUTH_ISSUER", ISSUER)
    monkeypatch.setattr(main, "create_provider", lambda: provider)
    with TestClient(main.app) as client:
        yield client, provider, fake


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_config_and_no_password_login(oidc):
    c, _, _ = oidc
    cfg = c.get("/api/v1/auth/config").json()
    assert (cfg["mode"], cfg["issuer"], cfg["web_client_id"], cfg["desktop_client_id"]) == \
        ("oidc", ISSUER, "snvr-web", "snvr-desktop")
    assert c.post("/api/v1/auth/login", json={"username": "a", "password": "b"}).status_code == 409
    assert c.post("/api/v1/auth/refresh", json={"refresh_token": "x"}).status_code == 409


def test_me_maps_codes_and_names(oidc):
    c, _, fake = oidc
    me = c.get("/api/v1/auth/me", headers=auth(fake.token(GUARD_SUB, ("live.view", "playback.view"), ("Viewer",))))
    assert me.status_code == 200, me.text
    body = me.json()
    assert (body["id"], body["username"], body["display_name"]) == (GUARD_SUB, "guard", "Night Guard")
    assert body["permissions"] == [1, 2] and not body["is_admin"] and body["roles"] == ["Viewer"]
    admin = c.get("/api/v1/auth/me", headers=auth(fake.token())).json()
    assert admin["is_admin"] and admin["scope"]["all_cameras"] and 40 in admin["permissions"]
    viewer = auth(fake.token(GUARD_SUB, ("live.view",), ("Viewer",)))
    assert c.post("/api/v1/cameras", json={"name": "X", "streams": STREAM}, headers=viewer).status_code == 403


def test_error_codes_and_revocation(oidc):
    c, provider, fake = oidc
    cases = {
        "token_expired": fake.token(now=int(time.time()) - 3600),
        "wrong_app": fake.token(aud="ANPR"),
        "invalid_token": "not.a.token",
    }
    for code, tok in cases.items():
        r = c.get("/api/v1/cameras/options", headers=auth(tok))
        assert r.status_code == 401 and r.headers["x-auth-error"] == code, (code, r.text)
    tok = fake.token(sid="sid-gone")
    assert c.get("/api/v1/cameras/options", headers=auth(tok)).status_code == 200
    fake.publish("session.revoked", {"sid": "sid-gone"})
    c.portal.call(provider.sync)
    r = c.get("/api/v1/cameras/options", headers=auth(tok))
    assert r.status_code == 401 and r.headers["x-auth-error"] == "token_revoked"


def test_role_grants_by_id_survive_rename_and_ignore_legacy(oidc):
    from app.access.models import AccessGrant

    c, provider, fake = oidc
    admin = auth(fake.token())
    gate = c.post("/api/v1/cameras", json={"name": "Gate", "streams": STREAM}, headers=admin).json()
    c.post("/api/v1/cameras", json={"name": "Back", "streams": STREAM}, headers=admin)
    viewer = auth(fake.token(GUARD_SUB, ("live.view",), ("Viewer",)))
    assert c.get("/api/v1/cameras/options", headers=viewer).json()["total"] == 0
    # a legacy grant for the same role name must not count on oidc
    c.portal.call(lambda: AccessGrant.create(subject_type="role", subject="Viewer", all_cameras=True,
                                             auth_source="legacy"))
    assert c.get("/api/v1/cameras/options", headers=viewer).json()["total"] == 0

    subjects = c.get("/api/v1/access/subjects", headers=admin).json()
    assert {(r["key"], r["name"]) for r in subjects["roles"]} == {(ROLE_ADMIN, "Admin"), (ROLE_VIEWER, "Viewer")}
    assert {(u["key"], u["username"]) for u in subjects["users"]} == {(ADMIN_SUB, "shah"), (GUARD_SUB, "guard")}
    r = c.put("/api/v1/access/grants", json={"subject_type": "role", "subject": ROLE_VIEWER,
                                             "camera_ids": [gate["id"]]}, headers=admin)
    assert r.status_code == 200 and r.json()["label"] == "Viewer"
    assert [x["name"] for x in c.get("/api/v1/cameras/options", headers=viewer).json()["items"]] == ["Gate"]

    # renamed on the Auth Server: tokens now say "Watchers", the grant (by id) still applies
    fake.roles[1]["name"] = "Watchers"
    c.portal.call(provider.reload_directory)
    renamed = auth(fake.token(GUARD_SUB, ("live.view",), ("Watchers",)))
    assert [x["name"] for x in c.get("/api/v1/cameras/options", headers=renamed).json()["items"]] == ["Gate"]
    summary = c.get("/api/v1/access/grants", headers=admin).json()
    assert [(s["subject"], s["label"]) for s in summary] == [(ROLE_VIEWER, "Watchers")]

    # deleted on the Auth Server: the grant is shown as removed, and matches no one
    del fake.roles[1]
    c.portal.call(provider.reload_directory)
    roles = c.get("/api/v1/access/subjects", headers=admin).json()["roles"]
    assert {(r["key"], r["removed"]) for r in roles} == {(ROLE_ADMIN, False), (ROLE_VIEWER, True)}
    assert c.get("/api/v1/cameras/options", headers=renamed).json()["total"] == 0


def test_user_grant_and_audit_rows(oidc):
    c, _, fake = oidc
    admin = auth(fake.token())
    gate = c.post("/api/v1/cameras", json={"name": "Gate", "streams": STREAM}, headers=admin).json()
    viewer = auth(fake.token(GUARD_SUB, ("live.view",), ("Viewer",), sid="sid-guard"))
    c.put("/api/v1/access/grants", json={"subject_type": "user", "subject": GUARD_SUB, "camera_ids": [gate["id"]]},
          headers=admin)
    assert c.get("/api/v1/cameras/options", headers=viewer).json()["total"] == 1
    c.get("/api/v1/cameras/options", headers=viewer)  # same session again: no second auth.session row
    audit = auth(fake.token(codes=("audit.view",), roles=()))
    rows = c.get("/api/v1/audit", params={"page_size": 100}, headers=audit).json()["items"]
    created = next(r for r in rows if r["action"] == "cameras.create")
    assert (created["user_id"], created["auth_source"], created["username"]) == (ADMIN_SUB, "oidc", "shah")
    sessions = [r for r in rows if r["action"] == "auth.session" and r["user_id"] == GUARD_SUB]
    assert len(sessions) == 1 and sessions[0]["detail"] == {"sid": "sid-guard"}


def test_roles_saved_for_restart(oidc, tmp_path):
    _, provider, _ = oidc
    saved = json.loads((tmp_path / "auth-roles.json").read_text())
    assert {r["name"] for r in saved["roles"]} == {"Admin", "Viewer"}
    again = OidcProvider(auth_sdk.AuthSDK(ISSUER, APP, "snvr-a", "secret"), str(tmp_path / "auth-roles.json"))
    assert again.role_ids == {"Admin": ROLE_ADMIN, "Viewer": ROLE_VIEWER}
