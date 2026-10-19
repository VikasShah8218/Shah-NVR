import base64
import asyncio
import hashlib
from datetime import datetime, timezone
from uuid import UUID

from lxml import etree
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tortoise import Tortoise

from app.node.models import KeyValue
from app.node.utils import runtime
from app.onvif_server.auth import REALM, make_nonce, verify_digest, verify_username_token
from app.onvif_server.rtsp_proxy import _allowed, _rewrite_request
from app.onvif_server.router import router
from app.onvif_server.service import KV_UUID, persistent_device_uuid
from app.onvif_server.soap import dispatch, parse
from settings.settings import settings


def credentials(monkeypatch):
    monkeypatch.setattr(settings, "ONVIF_AUTH_MODE", "local")
    monkeypatch.setattr(settings, "ONVIF_SERVER_USERNAME", "viewer")
    monkeypatch.setattr(settings, "ONVIF_SERVER_PASSWORD", "secret")


def test_http_digest_and_tamper(monkeypatch):
    credentials(monkeypatch)
    nonce, uri, method, nc, cnonce = make_nonce(), "/onvif/device_service", "POST", "00000001", "abc"
    md5 = lambda value: hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()
    ha1, ha2 = md5(f"viewer:{REALM}:secret"), md5(f"{method}:{uri}")
    answer = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}")
    header = (f'Digest username="viewer", realm="{REALM}", nonce="{nonce}", uri="{uri}", '
              f'response="{answer}", qop=auth, nc={nc}, cnonce="{cnonce}"')
    assert verify_digest(header, method, uri)
    assert not verify_digest(header, method, "/onvif/media_service")
    assert not verify_digest(header.replace(answer, "0" * 32), method)


def test_username_token_digest_is_one_time(monkeypatch):
    credentials(monkeypatch)
    nonce = b"unique-nonce"
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + b"secret").digest()).decode()
    xml = f'''<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
      xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
      xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">
      <s:Header><wsse:Security><wsse:UsernameToken><wsse:Username>viewer</wsse:Username>
      <wsse:Password Type="x#PasswordDigest">{digest}</wsse:Password><wsse:Nonce>{base64.b64encode(nonce).decode()}</wsse:Nonce>
      <wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security></s:Header><s:Body/></s:Envelope>'''
    root = etree.fromstring(xml.encode())
    assert verify_username_token(root)
    assert not verify_username_token(root)


def test_media_profiles_and_rtsp_proxy_never_expose_camera_source(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_HOST", "192.168.1.10")
    runtime.assignments = {17: {"camera_id": 17, "camera_name": "Gate", "expose_via_onvif": True,
        "streams": [{"profile": "main", "path_name": "cam-17/main", "source_url": "rtsp://admin:pw@camera/private"}]}}
    request = parse(b'''<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
      xmlns:trt="http://www.onvif.org/ver10/media/wsdl"><s:Body><trt:GetProfiles/></s:Body></s:Envelope>''')
    output = dispatch("media", request)
    assert b"profile_cam_17_main" in output and b"admin" not in output and b"camera/private" not in output
    assert _allowed("/live/cam-17/main")
    message = b"DESCRIBE rtsp://192.168.1.10:8555/live/cam-17/main RTSP/1.0\r\nCSeq: 2\r\nAuthorization: Digest x\r\n\r\n"
    rewritten, _, _ = _rewrite_request(message, "rtsp://192.168.1.10:8555/live/cam-17/main")
    assert b"rtsp://127.0.0.1:8554/cam-17/main" in rewritten and b"Authorization" not in rewritten


def test_device_endpoint_challenges_then_accepts_digest(monkeypatch):
    credentials(monkeypatch)
    runtime.onvif_server_config = {"enabled": True, "discovery_name": "Test NVR", "location": None}
    app = FastAPI(); app.include_router(router)
    request_xml = b'''<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
      xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><s:Body><tds:GetDeviceInformation/></s:Body></s:Envelope>'''
    with TestClient(app) as client:
        first = client.post("/onvif/device_service", content=request_xml)
        assert first.status_code == 401 and first.headers["www-authenticate"].startswith("Digest ")
        challenge = first.headers["www-authenticate"]
        nonce = challenge.split('nonce="', 1)[1].split('"', 1)[0]
        uri, nc, cnonce = "/onvif/device_service", "00000001", "test"
        md5 = lambda value: hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()
        answer = md5(f"{md5(f'viewer:{REALM}:secret')}:{nonce}:{nc}:{cnonce}:auth:{md5(f'POST:{uri}')}")
        auth = (f'Digest username="viewer", realm="{REALM}", nonce="{nonce}", uri="{uri}", '
                f'response="{answer}", qop=auth, nc={nc}, cnonce="{cnonce}"')
        response = client.post(uri, content=request_xml, headers={"Authorization": auth})
        assert response.status_code == 200 and b"GetDeviceInformationResponse" in response.content


def test_onvif_device_uuid_uses_json_safe_persistent_shape(tmp_path):
    async def run():
        await Tortoise.init(
            db_url=f"sqlite://{(tmp_path / 'node.sqlite3').as_posix()}",
            modules={"models": ["app.node.models"]},
        )
        await Tortoise.generate_schemas()
        try:
            first = await persistent_device_uuid()
            stored = await KeyValue.get_value(KV_UUID)
            assert stored == {"uuid": first}
            assert str(UUID(first)) == first

            second = await persistent_device_uuid()
            assert second == first
        finally:
            await Tortoise.close_connections()

    asyncio.run(run())
