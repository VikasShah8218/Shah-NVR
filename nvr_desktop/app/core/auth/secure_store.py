""""Keep me signed in": the refresh token, encrypted with Windows DPAPI (docs/DESKTOP_AUTH_PLAN.md DD1).

DPAPI (CryptProtectData, CurrentUser scope) ties the blob to this Windows user on this PC: another account, or the
file copied to another machine, cannot decrypt it. The blob is kept in QSettings under a key per central server.
No new dependency (ctypes). On other systems nothing is stored: the user signs in on every start.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import logging
import sys

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

_ENTROPY = b"ShahNVR-Desktop/auth/v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def supported() -> bool:
    return sys.platform == "win32"


if supported():
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
                                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                                            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p

    def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    def _call(fn, data: bytes) -> bytes | None:
        source, _keep = _blob(data)  # the buffers must stay alive during the call
        entropy, _keep2 = _blob(_ENTROPY)
        out = _Blob()
        # 2nd argument: a description (protect) / an optional out-pointer for it (unprotect); not used either way
        if not fn(ctypes.byref(source), None, ctypes.byref(entropy), None, None, _CRYPTPROTECT_UI_FORBIDDEN,
                  ctypes.byref(out)):
            return None
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def protect(data: bytes) -> bytes | None:
    return _call(_crypt32.CryptProtectData, data) if supported() else None


def unprotect(blob: bytes) -> bytes | None:
    return _call(_crypt32.CryptUnprotectData, blob) if supported() else None


def server_key(url: str) -> str:
    """A stable QSettings key for one central server (the URL itself contains ':' and '/')."""
    return hashlib.sha256(url.strip().rstrip("/").lower().encode()).hexdigest()[:16]


class TokenStore:
    """Encrypted refresh tokens per server, and the last username (not secret) for the login form.

    Since auth v2 (docs/DESKTOP_AUTH_V2_PLAN.md DV7) the encrypted value is an entry
    `{"v": 2, "mode", "issuer", "client_id", "refresh"}`, so a token saved under one Auth Server is never sent to
    the other. A bare token saved by an older version reads as a legacy entry.
    """

    def __init__(self, settings: QSettings | None = None):
        self._settings = settings or QSettings("ShahNVR", "Desktop")

    def load(self, url: str) -> str | None:
        raw = self._settings.value(f"auth/{server_key(url)}/refresh")
        if not raw:
            return None
        try:
            plain = unprotect(base64.b64decode(str(raw)))
        except (ValueError, OSError):
            plain = None
        if plain is None:  # another Windows user, another PC, or a damaged value
            logger.info("Stored sign-in could not be decrypted; it is ignored")
            self.clear(url)
            return None
        return plain.decode("utf-8", "replace")

    def save(self, url: str, refresh_token: str) -> bool:
        blob = protect(refresh_token.encode())
        if blob is None:
            return False
        self._settings.setValue(f"auth/{server_key(url)}/refresh", base64.b64encode(blob).decode())
        self._settings.sync()
        return True

    def load_entry(self, url: str) -> dict | None:
        raw = self.load(url)
        if raw is None:
            return None
        if raw.startswith("{"):
            try:
                entry = json.loads(raw)
            except ValueError:
                entry = None
            if isinstance(entry, dict) and entry.get("v") == 2 and entry.get("refresh"):
                return entry
            self.clear(url)
            return None
        return {"v": 2, "mode": "legacy", "issuer": None, "client_id": None, "refresh": raw}

    def save_entry(self, url: str, mode: str, refresh_token: str, issuer: str | None = None,
                   client_id: str | None = None) -> bool:
        entry = {"v": 2, "mode": mode, "issuer": issuer, "client_id": client_id, "refresh": refresh_token}
        return self.save(url, json.dumps(entry, separators=(",", ":")))

    def signed_out(self, url: str) -> bool:
        """Set by a sign-out on the new Auth Server: the next browser sign-in asks for the password (DV8)."""
        return str(self._settings.value(f"auth/{server_key(url)}/signed_out", "") or "") == "1"

    def set_signed_out(self, url: str, value: bool) -> None:
        if value:
            self._settings.setValue(f"auth/{server_key(url)}/signed_out", "1")
        else:
            self._settings.remove(f"auth/{server_key(url)}/signed_out")
        self._settings.sync()

    def clear(self, url: str) -> None:
        self._settings.remove(f"auth/{server_key(url)}/refresh")
        self._settings.sync()

    def last_username(self, url: str) -> str:
        return str(self._settings.value(f"auth/{server_key(url)}/username", "") or "")

    def save_username(self, url: str, username: str) -> None:
        self._settings.setValue(f"auth/{server_key(url)}/username", username)
