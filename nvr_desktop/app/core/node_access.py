"""Per-workstation LAN/public node routing with a short independent cache."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import httpx


def public_ready(node: dict) -> bool:
    return bool(node.get("public_enabled") and node.get("public_api_url") and node.get("public_media_host"))


class NodeAccessResolver:
    def __init__(self, probe: Callable[[str], bool] | None = None, ttl: float = 60.0):
        self._probe = probe or self._probe_lan
        self._ttl = ttl
        self._cache: dict[tuple, tuple[float, str]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _probe_lan(api_url: str) -> bool:
        try:
            response = httpx.get(api_url.rstrip("/") + "/api/v1/status", timeout=1.5)
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    @staticmethod
    def _key(node: dict) -> tuple:
        return (node.get("id"), node.get("api_url"), node.get("public_enabled"), node.get("public_api_url"))

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def resolve(self, node: dict | None, preference: str) -> str:
        if not node:
            return "lan"
        if preference == "lan":
            return "lan"
        if preference == "public":
            return "public" if public_ready(node) else "lan"
        key, now = self._key(node), time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
        if cached and now - cached[0] < self._ttl:
            return cached[1]
        route = "lan" if self._probe(str(node.get("api_url") or "")) else (
            "public" if public_ready(node) else "lan"
        )
        with self._lock:
            self._cache[key] = (now, route)
        return route

    def api_url(self, node: dict | None, preference: str) -> str:
        if not node:
            return ""
        route = self.resolve(node, preference)
        return str(node.get("public_api_url") if route == "public" else node.get("api_url") or "")
