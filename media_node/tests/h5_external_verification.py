"""Black-box verification of the implemented H5 ONVIF live-stream slice.

Edit only the configuration block below, then run:

    python3 media_node/tests/h5_external_verification.py

The script accepts no command-line arguments.  It behaves like an external VMS:
WS-Discovery, SOAP bootstrap/authentication, Device/Media calls, profile/URI
enumeration, and authenticated RTSP DESCRIBE.  It does not import Shah-NVR code.

Recording Search and Profile G replay are intentionally not tested because they
are not implemented in the current H5 slice.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import httpx


# ---------------------------------------------------------------------------
# Configuration -- edit these values; this script intentionally has no args.
# ---------------------------------------------------------------------------
NODE_HOST = "192.168.1.115"
NODE_HTTP_PORT = 7100
ONVIF_USERNAME = "shah"
ONVIF_PASSWORD = "shah"

HTTP_TIMEOUT_SECONDS = 10.0
RTSP_TIMEOUT_SECONDS = 12.0
DISCOVERY_TIMEOUT_SECONDS = 5.0
DISCOVERY_MULTICAST_HOST = "239.255.255.250"
DISCOVERY_PORT = 3702
TEST_EVERY_RTSP_PROFILE = True
PRINT_SOAP_XML = False


SOAP = "http://www.w3.org/2003/05/soap-envelope"
WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
WSD = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
TDS = "http://www.onvif.org/ver10/device/wsdl"
TRT = "http://www.onvif.org/ver10/media/wsdl"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
PASSWORD_DIGEST = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
)
NONCE_ENCODING = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-soap-message-security-1.0#Base64Binary"
)
REALM = "Shah-NVR"


class Results:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def step(self, text: str) -> None:
        print(f"\n=== {text} ===")

    def pass_(self, text: str, detail: str = "") -> None:
        self.passed += 1
        suffix = f" -- {detail}" if detail else ""
        print(f"[PASS] {text}{suffix}")

    def fail(self, text: str, detail: str = "") -> None:
        self.failed += 1
        suffix = f" -- {detail}" if detail else ""
        print(f"[FAIL] {text}{suffix}")

    def check(self, condition: bool, text: str, detail: str = "") -> bool:
        (self.pass_ if condition else self.fail)(text, detail)
        return condition


results = Results()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml_root(content: bytes) -> ET.Element:
    return ET.fromstring(content)


def values(root: ET.Element, name: str) -> list[str]:
    return [(node.text or "").strip() for node in root.iter() if local_name(node.tag) == name]


def response_name(content: bytes) -> str:
    try:
        root = xml_root(content)
        body = next(node for node in root.iter() if local_name(node.tag) == "Body")
        first = next(iter(body), None)
        return local_name(first.tag) if first is not None else "empty Body"
    except Exception as exc:
        return f"invalid XML: {exc}"


def soap_envelope(namespace: str, operation: str, inner: str = "", header: str = "") -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="{SOAP}" xmlns:tds="{TDS}" xmlns:trt="{TRT}"
 xmlns:wsse="{WSSE}" xmlns:wsu="{WSU}">
 <s:Header>{header}</s:Header>
 <s:Body><op:{operation} xmlns:op="{namespace}">{inner}</op:{operation}></s:Body>
</s:Envelope>'''.encode()


def show_soap(operation: str, response: httpx.Response) -> None:
    print(f"  {operation}: HTTP {response.status_code}, SOAP {response_name(response.content)}")
    if PRINT_SOAP_XML:
        print(response.text)


def post_soap(
    client: httpx.Client,
    url: str,
    namespace: str,
    operation: str,
    inner: str = "",
    header: str = "",
) -> httpx.Response:
    response = client.post(
        url,
        content=soap_envelope(namespace, operation, inner, header),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
    )
    show_soap(operation, response)
    return response


def ws_discovery() -> None:
    results.step("1. WS-Discovery Probe (what an external VMS sends first)")
    message_id = f"urn:uuid:{uuid.uuid4()}"
    probe = f'''<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="{SOAP}" xmlns:a="{WSA}" xmlns:d="{WSD}"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <s:Header>
  <a:Action>{WSD}/Probe</a:Action><a:MessageID>{message_id}</a:MessageID>
  <a:ReplyTo><a:Address>{WSA}/role/anonymous</a:Address></a:ReplyTo>
  <a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
 </s:Header>
 <s:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></s:Body>
</s:Envelope>'''.encode()
    found = False
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(DISCOVERY_TIMEOUT_SECONDS)
        sock.bind(("", 0))
        sock.sendto(probe, (DISCOVERY_MULTICAST_HOST, DISCOVERY_PORT))
        deadline = time.monotonic() + DISCOVERY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            sock.settimeout(max(0.1, deadline - time.monotonic()))
            try:
                data, peer = sock.recvfrom(65535)
            except socket.timeout:
                break
            try:
                root = xml_root(data)
                xaddrs = values(root, "XAddrs")
                addresses = values(root, "Address")
                scopes = values(root, "Scopes")
                print(f"  Reply from {peer[0]}:{peer[1]}")
                print(f"    Endpoint: {addresses[0] if addresses else 'missing'}")
                print(f"    XAddr:    {xaddrs[0] if xaddrs else 'missing'}")
                print(f"    Scopes:   {scopes[0] if scopes else 'missing'}")
                if peer[0] == NODE_HOST or any(NODE_HOST in item for item in xaddrs):
                    found = True
                    endpoint = addresses[0].removeprefix("urn:uuid:") if addresses else ""
                    try:
                        uuid.UUID(endpoint)
                        results.pass_("Persistent ONVIF endpoint UUID has a valid shape", endpoint)
                    except ValueError:
                        results.fail("Persistent ONVIF endpoint UUID has a valid shape", endpoint or "missing")
            except ET.ParseError as exc:
                print(f"  Ignored non-XML UDP reply from {peer}: {exc}")
    except OSError as exc:
        results.fail("WS-Discovery Probe could be sent", str(exc))
    finally:
        sock.close()
    results.check(found, "The configured Shah-NVR node answered multicast discovery")


def wsse_header() -> str:
    nonce = os.urandom(20)
    created = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + ONVIF_PASSWORD.encode()).digest()
    ).decode()
    return f'''<wsse:Security s:mustUnderstand="1"><wsse:UsernameToken>
<wsse:Username>{escape(ONVIF_USERNAME)}</wsse:Username>
<wsse:Password Type="{PASSWORD_DIGEST}">{digest}</wsse:Password>
<wsse:Nonce EncodingType="{NONCE_ENCODING}">{base64.b64encode(nonce).decode()}</wsse:Nonce>
<wsu:Created>{created}</wsu:Created>
</wsse:UsernameToken></wsse:Security>'''


def soap_checks() -> list[tuple[str, str]]:
    results.step("2. SOAP bootstrap and authentication")
    base = f"http://{NODE_HOST}:{NODE_HTTP_PORT}/onvif"
    device_url, media_url = f"{base}/device_service", f"{base}/media_service"
    plain = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    digest = httpx.Client(
        timeout=HTTP_TIMEOUT_SECONDS,
        auth=httpx.DigestAuth(ONVIF_USERNAME, ONVIF_PASSWORD),
    )
    try:
        response = post_soap(plain, device_url, TDS, "GetSystemDateAndTime")
        results.check(response.status_code == 200, "Clock bootstrap works without credentials")

        response = post_soap(plain, device_url, TDS, "GetDeviceInformation")
        results.check(
            response.status_code == 401 and response.headers.get("www-authenticate", "").startswith("Digest "),
            "Protected SOAP operation returns an HTTP Digest challenge",
            response.headers.get("www-authenticate", "missing challenge"),
        )

        header = wsse_header()
        response = post_soap(plain, device_url, TDS, "GetDeviceInformation", header=header)
        results.check(response.status_code == 200, "WS-Security PasswordDigest is accepted")
        replay = post_soap(plain, device_url, TDS, "GetDeviceInformation", header=header)
        results.check(
            replay.status_code == 400 and "NotAuthorized" in replay.text,
            "Replaying the same UsernameToken is rejected",
        )

        results.step("3. Authenticated Device service operations")
        for operation in ("GetDeviceInformation", "GetServices", "GetCapabilities", "GetScopes", "GetHostname"):
            response = post_soap(digest, device_url, TDS, operation)
            results.check(response.status_code == 200, f"Device/{operation} succeeds")
            if operation == "GetDeviceInformation" and response.status_code == 200:
                root = xml_root(response.content)
                print("  Device:", ", ".join(
                    f"{key}={next(iter(values(root, key)), 'missing')}"
                    for key in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber")
                ))
            elif operation == "GetServices" and response.status_code == 200:
                print("  Advertised services:", ", ".join(values(xml_root(response.content), "XAddr")))
            elif operation == "GetScopes" and response.status_code == 200:
                for scope in values(xml_root(response.content), "ScopeItem"):
                    print(f"  Scope: {scope}")

        unsupported = post_soap(digest, device_url, TDS, "SetHostname", "<op:Name>unsafe</op:Name>")
        results.check(
            unsupported.status_code == 400 and "ActionNotSupported" in unsupported.text,
            "Unsupported device writes are safely rejected",
        )

        results.step("4. Authenticated Media profiles and safe stream URIs")
        response = post_soap(digest, media_url, TRT, "GetProfiles")
        if not results.check(response.status_code == 200, "Media/GetProfiles succeeds"):
            return []
        root = xml_root(response.content)
        profiles: list[tuple[str, str]] = []
        for profile in (node for node in root.iter() if local_name(node.tag) == "Profiles"):
            token = profile.attrib.get("token", "")
            name = next(iter(values(profile, "Name")), token)
            print(f"  Profile: token={token}, name={name}")
            inner = f"<op:ProfileToken>{token}</op:ProfileToken>"
            detail = post_soap(digest, media_url, TRT, "GetProfile", inner)
            results.check(detail.status_code == 200, f"GetProfile accepts {token}")
            stream = post_soap(digest, media_url, TRT, "GetStreamUri", inner)
            if not results.check(stream.status_code == 200, f"GetStreamUri accepts {token}"):
                continue
            uris = values(xml_root(stream.content), "Uri")
            uri = uris[0] if uris else ""
            print(f"    Live URI: {uri}")
            safe = bool(uri.startswith("rtsp://")) and "@" not in uri and ONVIF_PASSWORD not in uri
            results.check(safe, "Returned RTSP URI hides all credentials", token)
            if safe:
                profiles.append((token, uri))
        results.check(bool(profiles), "At least one exposed media profile was enumerated")

        bad = post_soap(
            digest,
            media_url,
            TRT,
            "GetStreamUri",
            "<op:ProfileToken>profile_cam_999999_not_exposed</op:ProfileToken>",
        )
        results.check(
            bad.status_code == 400 and "InvalidToken" in bad.text,
            "A guessed/unexposed profile token is rejected",
        )
        return profiles
    except (httpx.HTTPError, OSError, ET.ParseError) as exc:
        results.fail("SOAP verification completed", repr(exc))
        return []
    finally:
        plain.close()
        digest.close()


def digest_parts(header: str) -> dict[str, str]:
    if header.lower().startswith("digest "):
        header = header[7:]
    return {
        match.group(1): match.group(2) if match.group(2) is not None else match.group(3)
        for match in re.finditer(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', header)
    }


def receive_rtsp(sock: socket.socket) -> tuple[int, dict[str, str], bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("RTSP peer closed before sending response headers")
        data += chunk
        if len(data) > 1024 * 1024:
            raise ValueError("RTSP response headers are unexpectedly large")
    head, body = data.split(b"\r\n\r\n", 1)
    lines = head.decode("latin1").split("\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    while len(body) < length:
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("RTSP peer closed before sending the complete body")
        body += chunk
    return status, headers, body[:length]


def rtsp_describe(uri: str) -> tuple[bool, str]:
    target = urlsplit(uri)
    host, port = target.hostname or NODE_HOST, target.port or 554
    with socket.create_connection((host, port), timeout=RTSP_TIMEOUT_SECONDS) as sock:
        sock.settimeout(RTSP_TIMEOUT_SECONDS)
        first = (
            f"DESCRIBE {uri} RTSP/1.0\r\nCSeq: 1\r\nAccept: application/sdp\r\n"
            f"User-Agent: Shah-NVR-H5-verifier\r\n\r\n"
        ).encode()
        sock.sendall(first)
        code, headers, _ = receive_rtsp(sock)
        if code != 401:
            return False, f"expected initial 401, received {code}"
        challenge = digest_parts(headers.get("www-authenticate", ""))
        if not {"realm", "nonce"}.issubset(challenge):
            return False, "RTSP Digest challenge is incomplete"
        nc, cnonce = "00000001", uuid.uuid4().hex[:16]
        ha1 = hashlib.md5(
            f"{ONVIF_USERNAME}:{challenge['realm']}:{ONVIF_PASSWORD}".encode(), usedforsecurity=False
        ).hexdigest()
        ha2 = hashlib.md5(f"DESCRIBE:{uri}".encode(), usedforsecurity=False).hexdigest()
        answer = hashlib.md5(
            f"{ha1}:{challenge['nonce']}:{nc}:{cnonce}:auth:{ha2}".encode(), usedforsecurity=False
        ).hexdigest()
        authorization = (
            f'Digest username="{ONVIF_USERNAME}", realm="{challenge["realm"]}", '
            f'nonce="{challenge["nonce"]}", uri="{uri}", response="{answer}", '
            f'qop=auth, nc={nc}, cnonce="{cnonce}"'
        )
        second = (
            f"DESCRIBE {uri} RTSP/1.0\r\nCSeq: 2\r\nAccept: application/sdp\r\n"
            f"Authorization: {authorization}\r\nUser-Agent: Shah-NVR-H5-verifier\r\n\r\n"
        ).encode()
        sock.sendall(second)
        code, headers, body = receive_rtsp(sock)
        if code != 200:
            return False, f"authenticated DESCRIBE returned RTSP {code}"
        if b"v=0" not in body:
            return False, "RTSP 200 response did not contain an SDP description"
        tracks = body.count(b"m=")
        return True, f"RTSP 200, SDP {len(body)} bytes, {tracks} media track(s)"


def rtsp_checks(profiles: list[tuple[str, str]]) -> None:
    results.step("5. Authenticated RTSP live gateway")
    selected = profiles if TEST_EVERY_RTSP_PROFILE else profiles[:1]
    for token, uri in selected:
        print(f"  DESCRIBE {token}: {uri}")
        try:
            okay, detail = rtsp_describe(uri)
            results.check(okay, f"RTSP Digest and DESCRIBE work for {token}", detail)
        except (OSError, ValueError, ConnectionError) as exc:
            results.fail(f"RTSP Digest and DESCRIBE work for {token}", repr(exc))


def main() -> int:
    print("Shah-NVR H5 external-service verification")
    print(f"Target SOAP: http://{NODE_HOST}:{NODE_HTTP_PORT}/onvif/device_service")
    print(f"User: {ONVIF_USERNAME}; password: <hidden>")
    print("Scope: currently implemented discovery + Device/Media + live RTSP slice")
    print("Not in current slice: Recording Search and Profile G recorded RTSP replay")
    if not NODE_HOST or ONVIF_USERNAME == "CHANGE_ME" or ONVIF_PASSWORD == "CHANGE_ME":
        print("\n[CONFIG ERROR] Edit NODE_HOST, ONVIF_USERNAME and ONVIF_PASSWORD at the top of this file.")
        return 2

    ws_discovery()
    profiles = soap_checks()
    if profiles:
        rtsp_checks(profiles)
    else:
        results.fail("RTSP verification ran", "no valid stream URIs were returned")

    results.step("Summary")
    print(f"Passed: {results.passed}")
    print(f"Failed: {results.failed}")
    if results.failed:
        print("RESULT: H5 live-slice verification FAILED")
        return 1
    print("RESULT: H5 live-slice verification PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
