"""Media node API client (read-only): status, MediaMTX paths, recorded chunks, logs, media files.

All actions go through the central manager; this client only reads what happens on a node.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

from app.core.api.errors import ApiError, raise_for_response
from app.core.api.models import LocalSegment, NodeStatus
from settings.settings import settings

_clients: dict[str, httpx.Client] = {}


def _client(api_url: str) -> httpx.Client:
    base = api_url.rstrip("/")
    if base not in _clients:
        _clients[base] = httpx.Client(base_url=base, timeout=settings.HTTP_TIMEOUT_SECONDS)
    return _clients[base]


def _get(api_url: str, path: str, **params):
    try:
        response = _client(api_url).get(path, params=params or None)
    except httpx.HTTPError as exc:
        raise ApiError(0, f"Node unreachable at {api_url}") from exc
    raise_for_response(response)
    return response.json()


def status(api_url: str) -> NodeStatus:
    return NodeStatus.model_validate(_get(api_url, "/api/v1/status"))


def assignments(api_url: str) -> list[dict]:
    return _get(api_url, "/api/v1/assignments")


def mediamtx_paths(api_url: str) -> list[dict]:
    return _get(api_url, "/api/v1/mediamtx/paths")


def segments(api_url: str, limit: int = 100) -> list[LocalSegment]:
    return [LocalSegment.model_validate(s) for s in _get(api_url, "/api/v1/segments", limit=limit)]


def logs(api_url: str, source: str, lines: int = 500) -> list[str]:
    return _get(api_url, "/api/v1/logs", source=source, lines=lines)["lines"]


def media_file_url(api_url: str, segment_id: str) -> str:
    return f"{api_url.rstrip('/')}/api/v1/media/{segment_id}/file.mp4"


def download(url: str, target: Path, on_progress: Callable[[int, int], None] | None = None) -> Path:
    """Stream a file to disk (used for chunk downloads). Returns the saved path."""
    try:
        with httpx.stream("GET", url, timeout=settings.HTTP_TIMEOUT_SECONDS * 6) as response:
            if response.status_code >= 400:
                response.read()  # load the error body so its message can be shown
                raise_for_response(response)
            total = int(response.headers.get("content-length") or 0)
            done = 0
            with open(target, "wb") as f:
                for chunk in response.iter_bytes(64 * 1024):
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
    except httpx.HTTPError as exc:
        raise ApiError(0, f"Download failed: {exc}") from exc
    return target
