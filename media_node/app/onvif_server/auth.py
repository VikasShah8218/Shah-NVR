"""Temporary node-local H5 authentication (HTTP/RTSP Digest and WS-UsernameToken)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timezone

from lxml import etree

from settings.settings import settings

REALM = "Shah-NVR"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
_DIGEST_PART = re.compile(r'(\w+)=(?:"([^"]*)"|([^,\s]+))')
_seen: dict[str, float] = {}


def configured() -> bool:
    return settings.ONVIF_AUTH_MODE == "local" and settings.onvif_credentials_configured


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8"), usedforsecurity=False).hexdigest()


def _secret() -> bytes:
    return hashlib.sha256(
        f"{settings.NODE_NAME}\0{settings.ONVIF_SERVER_USERNAME}\0{settings.ONVIF_SERVER_PASSWORD}".encode()
    ).digest()


def make_nonce(now: int | None = None) -> str:
    stamp = str(now or int(time.time()))
    salt = base64.urlsafe_b64encode(os.urandom(9)).decode().rstrip("=")
    body = f"{stamp}:{salt}"
    signature = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}:{signature}".encode()).decode().rstrip("=")


def _nonce_valid(nonce: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(nonce + "=" * (-len(nonce) % 4)).decode()
        stamp, salt, signature = raw.split(":", 2)
        body = f"{stamp}:{salt}"
        expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected) and 0 <= time.time() - int(stamp) <= settings.ONVIF_AUTH_NONCE_SECONDS
    except (ValueError, UnicodeError):
        return False


def digest_challenge(stale: bool = False) -> str:
    return f'Digest realm="{REALM}", nonce="{make_nonce()}", algorithm=MD5, qop="auth"' + (
        ", stale=true" if stale else ""
    )


def verify_digest(header: str | None, method: str, request_uri: str | None = None) -> bool:
    if not configured() or not header or not header.lower().startswith("digest "):
        return False
    values = {m.group(1): (m.group(2) if m.group(2) is not None else m.group(3)) for m in _DIGEST_PART.finditer(header[7:])}
    required = {"username", "realm", "nonce", "uri", "response"}
    if not required.issubset(values) or values["realm"] != REALM or not _nonce_valid(values["nonce"]):
        return False
    if request_uri is not None and values["uri"] != request_uri:
        return False
    if not hmac.compare_digest(values["username"], settings.ONVIF_SERVER_USERNAME):
        return False
    ha1 = _md5(f"{settings.ONVIF_SERVER_USERNAME}:{REALM}:{settings.ONVIF_SERVER_PASSWORD}")
    ha2 = _md5(f"{method}:{values['uri']}")
    if values.get("qop"):
        if values["qop"] != "auth" or not values.get("nc") or not values.get("cnonce"):
            return False
        expected = _md5(f"{ha1}:{values['nonce']}:{values['nc']}:{values['cnonce']}:auth:{ha2}")
    else:
        expected = _md5(f"{ha1}:{values['nonce']}:{ha2}")
    return hmac.compare_digest(expected, values["response"])


def _created_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def verify_username_token(root: etree._Element) -> bool:
    if not configured():
        return False
    token = root.find(f".//{{{WSSE}}}UsernameToken")
    if token is None:
        return False
    username = token.findtext(f"{{{WSSE}}}Username") or ""
    password = token.find(f"{{{WSSE}}}Password")
    if password is None or not hmac.compare_digest(username, settings.ONVIF_SERVER_USERNAME):
        return False
    supplied = password.text or ""
    kind = password.get("Type", "")
    if kind.endswith("#PasswordText") or not kind:
        return hmac.compare_digest(supplied, settings.ONVIF_SERVER_PASSWORD)
    if not kind.endswith("#PasswordDigest"):
        return False
    nonce_text = token.findtext(f"{{{WSSE}}}Nonce") or ""
    created = token.findtext(f"{{{WSU}}}Created") or ""
    try:
        nonce = base64.b64decode(nonce_text, validate=True)
        if abs(time.time() - _created_time(created)) > settings.ONVIF_AUTH_NONCE_SECONDS:
            return False
    except (ValueError, TypeError):
        return False
    replay_key = hashlib.sha256(nonce + created.encode() + supplied.encode()).hexdigest()
    cutoff = time.time() - settings.ONVIF_AUTH_NONCE_SECONDS
    for key, seen_at in list(_seen.items()):
        if seen_at < cutoff:
            _seen.pop(key, None)
    if replay_key in _seen:
        return False
    expected = base64.b64encode(hashlib.sha1(nonce + created.encode() + settings.ONVIF_SERVER_PASSWORD.encode()).digest()).decode()
    if not hmac.compare_digest(expected, supplied):
        return False
    _seen[replay_key] = time.time()
    return True
