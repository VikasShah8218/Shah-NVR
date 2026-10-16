"""Small async ONVIF SOAP client: envelope, WS-UsernameToken digest, HTTP Digest fallback, typed faults.

Why not onvif-zeep: on the lab AXIS it failed where this client works, and it was 10-50x slower (docs/memory/08).

Lockout safety: some devices lock the account after a few wrong logins (a Dahua NVR replied "You still have 0
attempt(s)"). After the first authentication failure this client refuses every further authenticated call, so one
probe costs at most one wrong attempt.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from datetime import datetime, timezone

import httpx
from lxml import etree

NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "wsa": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
    "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
    "dn": "http://www.onvif.org/ver10/network/wsdl",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tr2": "http://www.onvif.org/ver20/media/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}
_WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
_WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
_DIGEST = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest"
_B64 = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary"

# Fault subcodes / texts that mean "wrong credentials or not allowed".
_AUTH_MARKERS = ("notauthorized", "failedauthentication", "invalidsecurity", "unauthorized", "not authorized",
                 "security token", "invalid username")
_UNSUPPORTED_MARKERS = ("actionnotsupported", "nosuchservice", "notsupported", "not supported")


class OnvifError(Exception):
    """Base error; `code` is what the API returns to clients."""

    code = "fault"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotAuthorized(OnvifError):
    code = "not_authorized"


class Unreachable(OnvifError):
    code = "unreachable"


class NotSupported(OnvifError):
    code = "not_supported"


class Fault(OnvifError):
    code = "fault"


def password_digest(nonce: bytes, created: str, password: str) -> str:
    """WS-Security UsernameToken digest: Base64(SHA1(nonce + created + password))."""
    return base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()


def security_header(username: str, password: str, offset: float = 0.0, *, nonce: bytes | None = None,
                    now: float | None = None) -> str:
    """UsernameToken with `Created` in the camera's clock (node time + offset), so skewed cameras accept it."""
    nonce = nonce or os.urandom(16)
    ts = (time.time() if now is None else now) + offset
    created = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return (f'<wsse:Security s:mustUnderstand="1" xmlns:wsse="{_WSSE}" xmlns:wsu="{_WSU}"><wsse:UsernameToken>'
            f"<wsse:Username>{_xml_escape(username)}</wsse:Username>"
            f'<wsse:Password Type="{_DIGEST}">{password_digest(nonce, created, password)}</wsse:Password>'
            f'<wsse:Nonce EncodingType="{_B64}">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
            f"<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security>")


def envelope(body: str, header: str = "") -> bytes:
    ns = " ".join(f'xmlns:{p}="{u}"' for p, u in NS.items() if p in ("s", "tds", "trt", "tr2", "tt"))
    return f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope {ns}><s:Header>{header}</s:Header><s:Body>{body}</s:Body></s:Envelope>'.encode()


def _xml_escape(v: str) -> str:
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def classify_fault(status: int, text: str) -> OnvifError:
    """Map an HTTP status + fault text to a typed error (unit-tested against real camera replies)."""
    low = text.lower()
    if status == 401 or any(m in low for m in _AUTH_MARKERS):
        return NotAuthorized(text or f"HTTP {status}")
    if status in (404, 405) or any(m in low for m in _UNSUPPORTED_MARKERS):
        return NotSupported(text or f"HTTP {status}")
    return Fault(text or f"HTTP {status}")


def parse_response(status: int, content: bytes) -> etree._Element:
    """The SOAP Body element, or raise the typed fault."""
    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError:
        raise classify_fault(status, f"HTTP {status}: not a SOAP reply") from None
    fault = root.find(".//s:Fault", NS)
    if fault is not None:
        parts = [t.strip() for t in fault.itertext() if t.strip()]
        raise classify_fault(status, " ".join(dict.fromkeys(parts))[:300])
    if status >= 400:
        raise classify_fault(status, f"HTTP {status}")
    body = root.find("s:Body", NS)
    if body is None:
        raise Fault("SOAP reply without Body")
    return body


class SoapClient:
    """One device's SOAP session: credentials, camera clock offset and the auth method that worked."""

    def __init__(self, http: httpx.AsyncClient, username: str = "", password: str = ""):
        self.http = http
        self.username, self.password = username or "", password or ""
        self.offset = 0.0  # camera clock - node clock, seconds
        self.http_digest = False  # device wants HTTP Digest instead of (or besides) WS-UsernameToken
        self.auth_failed: NotAuthorized | None = None

    async def call(self, url: str, body: str, *, auth: bool = True) -> etree._Element:
        if auth and self.auth_failed:
            raise self.auth_failed  # never send a second wrong login (account lockout)
        use_auth = auth and bool(self.username)
        header = security_header(self.username, self.password, self.offset) if use_auth else ""
        try:
            r = await self._post(url, envelope(body, header), digest=use_auth and self.http_digest)
            if r.status_code == 401 and use_auth and not self.http_digest and "digest" in r.headers.get("www-authenticate", "").lower():
                # HTTP-level challenge before the WS token was even read: switch to HTTP Digest (Hikvision-style).
                self.http_digest = True
                r = await self._post(url, envelope(body, header), digest=True)
            return parse_response(r.status_code, r.content)
        except NotAuthorized as exc:
            if use_auth:
                self.auth_failed = exc
            raise
        except httpx.TimeoutException:
            raise Unreachable(f"{url}: timed out") from None
        except httpx.HTTPError as exc:
            raise Unreachable(f"{url}: {type(exc).__name__}") from None

    async def _post(self, url: str, content: bytes, *, digest: bool) -> httpx.Response:
        return await self.http.post(
            url, content=content, headers={"Content-Type": "application/soap+xml; charset=utf-8"},
            auth=httpx.DigestAuth(self.username, self.password) if digest else None,
        )
