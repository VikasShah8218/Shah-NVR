"""Minimal async SOAP 1.2 client for ONVIF (no zeep, no WSDL): exact control of headers, auth and timing.

Auth: WS-Security UsernameToken (PasswordDigest) with the camera's clock offset applied to `Created` (cameras refuse
tokens outside a few seconds of their own clock), and HTTP Digest/Basic when the camera answers 401. Both are sent
together after a 401, which is what most vendors accept.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from lxml import etree

NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "wsse": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd",
    "wsu": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd",
    "wsa": "http://www.w3.org/2005/08/addressing",
    "wsa04": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tev": "http://www.onvif.org/ver10/events/wsdl",
    "tan": "http://www.onvif.org/ver20/analytics/wsdl",
    "tmd": "http://www.onvif.org/ver10/deviceIO/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
    "wsnt": "http://docs.oasis-open.org/wsn/b-2",
    "wstop": "http://docs.oasis-open.org/wsn/t-1",
    "tns1": "http://www.onvif.org/ver10/topics",
}
PW_DIGEST = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0"
             "#PasswordDigest")
NONCE_B64 = ("http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0"
             "#Base64Binary")


class SoapError(Exception):
    """A request that failed: HTTP error, SOAP fault, timeout or connection problem. `kind` is short and stable
    (for reports): http-401, fault, timeout, connect, http-500, bad-xml..."""

    def __init__(self, kind: str, message: str, fault_code: str | None = None):
        super().__init__(f"{kind}: {message}")
        self.kind, self.message, self.fault_code = kind, message, fault_code


@dataclass
class Credentials:
    username: str | None
    password: str | None


@dataclass
class SoapClient:
    """One camera. `offset` = camera clock - our clock (seconds), measured by the caller (GetSystemDateAndTime)."""

    creds: Credentials
    timeout: float = 10.0
    offset: float = 0.0
    http: httpx.AsyncClient | None = None
    stats: dict = field(default_factory=lambda: {"requests": 0, "errors": 0, "retried_401": 0, "ms": []})
    _http_auth: httpx.Auth | None = None

    def _security(self) -> str:
        if not self.creds.username:
            return ""
        nonce = os.urandom(16)
        created = (datetime.now(timezone.utc) + timedelta(seconds=self.offset)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        digest = base64.b64encode(hashlib.sha1(nonce + created.encode() + (self.creds.password or "").encode()).digest())
        return (f'<wsse:Security s:mustUnderstand="1" xmlns:wsse="{NS["wsse"]}" xmlns:wsu="{NS["wsu"]}">'
                f"<wsse:UsernameToken><wsse:Username>{_esc(self.creds.username)}</wsse:Username>"
                f'<wsse:Password Type="{PW_DIGEST}">{digest.decode()}</wsse:Password>'
                f'<wsse:Nonce EncodingType="{NONCE_B64}">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
                f"<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security>")

    def envelope(self, body: str, action: str | None = None, to: str | None = None, extra_headers: str = "",
                 auth: bool = True) -> str:
        wsa = ""
        if action and to:  # WS-Addressing: needed by subscription managers (PullMessages, Renew, Unsubscribe)
            wsa = (f'<wsa:Action s:mustUnderstand="1">{action}</wsa:Action>'
                   f"<wsa:MessageID>urn:uuid:{uuid.uuid4()}</wsa:MessageID>"
                   f'<wsa:To s:mustUnderstand="1">{_esc(to)}</wsa:To>')
        ns = " ".join(f'xmlns:{p}="{u}"' for p, u in NS.items() if p not in ("wsse", "wsu", "wsa04"))
        return (f'<?xml version="1.0" encoding="UTF-8"?><s:Envelope {ns}><s:Header>'
                f'{self._security() if auth else ""}{wsa}{extra_headers}</s:Header><s:Body>{body}</s:Body></s:Envelope>')

    async def call(self, url: str, body: str, action: str | None = None, *, wsa: bool = False,
                   extra_headers: str = "", timeout: float | None = None, auth: bool = True) -> etree._Element:
        """POST one SOAP request; returns the Body element. Raises SoapError."""
        assert self.http is not None
        headers = {"Content-Type": "application/soap+xml; charset=utf-8" + (f'; action="{action}"' if action else "")}
        t = timeout or self.timeout
        for attempt in (0, 1):
            data = self.envelope(body, action if wsa else None, url if wsa else None, extra_headers, auth)
            started = time.perf_counter()
            self.stats["requests"] += 1
            try:
                r = await self.http.post(url, content=data.encode(), headers=headers, timeout=t,
                                         auth=self._http_auth or httpx.USE_CLIENT_DEFAULT)
            except httpx.TimeoutException as exc:
                self.stats["errors"] += 1
                raise SoapError("timeout", f"no answer in {t:g} s ({type(exc).__name__})") from None
            except httpx.HTTPError as exc:
                self.stats["errors"] += 1
                raise SoapError("connect", f"{type(exc).__name__}: {exc}") from None
            finally:
                self.stats["ms"].append(round((time.perf_counter() - started) * 1000))
            if r.status_code == 401 and attempt == 0 and self.creds.username and self._http_auth is None:
                # HTTP-level auth wanted: Digest if offered, else Basic; keep WS-Security too
                www = r.headers.get("www-authenticate", "").lower()
                self._http_auth = (httpx.DigestAuth(self.creds.username, self.creds.password or "") if "digest" in www
                                   else httpx.BasicAuth(self.creds.username, self.creds.password or ""))
                self.stats["retried_401"] += 1
                continue
            return self._parse(r)
        raise SoapError("http-401", "refused after HTTP auth")  # pragma: no cover

    def _parse(self, r: httpx.Response) -> etree._Element:
        try:
            root = etree.fromstring(r.content, parser=etree.XMLParser(resolve_entities=False, huge_tree=True))
        except etree.XMLSyntaxError:
            self.stats["errors"] += 1
            raise SoapError(f"http-{r.status_code}" if r.status_code >= 400 else "bad-xml",
                            r.text[:200].replace("\n", " ")) from None
        fault = root.find(".//s:Fault", NS)
        if fault is not None:
            self.stats["errors"] += 1
            codes = [e.text for e in fault.iter() if etree.QName(e).localname == "Value" and e.text]
            reason = " ".join(t.strip() for t in fault.xpath(".//*[local-name()='Text']/text()") if t.strip())
            kind = "auth" if any("NotAuthorized" in c or "FailedAuthentication" in c for c in codes) else "fault"
            raise SoapError(kind, (reason or "SOAP fault")[:300], fault_code=" / ".join(codes) or None)
        if r.status_code >= 400:
            self.stats["errors"] += 1
            raise SoapError(f"http-{r.status_code}", r.text[:200].replace("\n", " "))
        body = root.find("s:Body", NS)
        if body is None:
            body = root.find("{http://schemas.xmlsoap.org/soap/envelope/}Body")  # SOAP 1.1 answer
        if body is None:
            raise SoapError("bad-xml", "no SOAP Body")
        return body


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def text(el: etree._Element | None, path: str, default: str | None = None) -> str | None:
    if el is None:
        return default
    found = el.find(path, NS)
    return found.text.strip() if found is not None and found.text else default


def parse_duration(value: str | None) -> float | None:
    """xs:duration 'PT1M30S' / 'PT60S' / 'P1D' -> seconds (enough for ONVIF termination times)."""
    if not value or not value.startswith("P"):
        return None
    import re

    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?)?", value)
    if not m:
        return None
    d, h, mi, s = (float(x) if x else 0.0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        v = value.strip().replace("Z", "+00:00")
        if "." in v:  # some cameras send 7 fraction digits
            head, frac = v.split(".", 1)
            digits = "".join(ch for ch in frac if ch.isdigit())
            tz = frac[len(digits):]
            v = f"{head}.{digits[:6]}{tz}"
        dt = datetime.fromisoformat(v)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
