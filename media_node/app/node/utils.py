"""HTTP client for the central manager's internal API + the node's in-memory runtime state."""

from dataclasses import dataclass, field
from datetime import datetime

import httpx

from settings.settings import settings


class CentralError(Exception):
    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class NodeRuntime:
    node_id: int | None = None
    # camera_id -> assignment dict from central: {camera_id, camera_name, generation, streams: [...]}
    assignments: dict[int, dict] = field(default_factory=dict)
    central_online: bool = False
    last_central_contact: datetime | None = None
    mediamtx_running: bool = False
    mediamtx_version: str | None = None
    # Max bytes for recordings set by central (None = whole disk); cached locally.
    storage_quota_bytes: int | None = None
    # (camera_id, profile) -> end time of the latest indexed chunk
    last_segment_end: dict[tuple[int, str], datetime] = field(default_factory=dict)
    # path name -> time we first saw it "ready" in MediaMTX
    ready_since: dict[str, datetime] = field(default_factory=dict)

    def generation_for(self, camera_id: int) -> int:
        a = self.assignments.get(camera_id)
        return int(a["generation"]) if a else 0


runtime = NodeRuntime()


class CentralClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.CENTRAL_URL.rstrip("/"), timeout=settings.CENTRAL_TIMEOUT_SECONDS
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs):
        try:
            resp = await self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            runtime.central_online = False
            raise CentralError(None, f"central unreachable: {exc!r}") from exc
        runtime.central_online = True
        if resp.status_code >= 400:
            raise CentralError(resp.status_code, f"{method} {url} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else None

    async def register(self, payload: dict) -> dict:
        return await self._request("POST", "/internal/v1/nodes/register", json=payload)

    async def heartbeat(self, node_id: int, payload: dict) -> dict:
        return await self._request("POST", f"/internal/v1/nodes/{node_id}/heartbeat", json=payload)

    async def assignments(self, node_id: int) -> dict:
        return await self._request("GET", f"/internal/v1/nodes/{node_id}/assignments")

    async def stream_status(self, node_id: int, items: list[dict]) -> None:
        await self._request("POST", f"/internal/v1/nodes/{node_id}/stream-status", json={"items": items})

    async def upload_segments(self, node_id: int, items: list[dict]) -> dict:
        return await self._request("POST", "/internal/v1/recordings/segments", json={"node_id": node_id, "items": items})

    async def pending_deletions(self, node_id: int, limit: int = 500) -> list[dict]:
        return await self._request("GET", f"/internal/v1/nodes/{node_id}/deletions", params={"limit": limit})

    async def confirm_deleted(self, node_id: int, ids: list[str]) -> None:
        await self._request("POST", f"/internal/v1/nodes/{node_id}/deleted", json={"ids": ids})


central = CentralClient()
