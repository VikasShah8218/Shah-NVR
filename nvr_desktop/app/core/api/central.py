"""Central manager API client: one method per endpoint the desktop app uses.

Blocking (httpx) by design: stores call these through app/core/tasks.py::run_task, which runs them
on a worker thread, so the UI thread never waits on the network.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

import httpx

from app.core.api.errors import ApiError, raise_for_response
from app.core.api.models import (
    Assignment,
    AssignmentHistory,
    Camera,
    ClusterHealth,
    LiveInfo,
    MediaNode,
    StorageVolume,
    Timeline,
)
from settings.settings import settings


class CentralApi:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=settings.HTTP_TIMEOUT_SECONDS)

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ plumbing
    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(0, f"Central manager unreachable ({self.base_url})") from exc
        raise_for_response(response)
        return response.json() if response.content else None

    # ------------------------------------------------------------------ system
    def ping(self) -> dict:
        return self._request("GET", "/")

    def cluster_health(self) -> ClusterHealth:
        return ClusterHealth.model_validate(self._request("GET", "/api/v1/cluster/health"))

    # ------------------------------------------------------------------ cameras
    def cameras(self) -> list[Camera]:
        return [Camera.model_validate(c) for c in self._request("GET", "/api/v1/cameras")]

    def camera(self, camera_id: int) -> Camera:
        return Camera.model_validate(self._request("GET", f"/api/v1/cameras/{camera_id}"))

    def create_camera(self, body: dict) -> Camera:
        return Camera.model_validate(self._request("POST", "/api/v1/cameras", json=body))

    def update_camera(self, camera_id: int, body: dict) -> Camera:
        return Camera.model_validate(self._request("PATCH", f"/api/v1/cameras/{camera_id}", json=body))

    def delete_camera(self, camera_id: int) -> None:
        self._request("DELETE", f"/api/v1/cameras/{camera_id}")

    def add_stream(self, camera_id: int, body: dict) -> None:
        self._request("POST", f"/api/v1/cameras/{camera_id}/streams", json=body)

    def update_stream(self, camera_id: int, profile: str, body: dict) -> None:
        self._request("PATCH", f"/api/v1/cameras/{camera_id}/streams/{profile}", json=body)

    def delete_stream(self, camera_id: int, profile: str) -> None:
        self._request("DELETE", f"/api/v1/cameras/{camera_id}/streams/{profile}")

    def live(self, camera_id: int) -> LiveInfo:
        return LiveInfo.model_validate(self._request("GET", f"/api/v1/cameras/{camera_id}/live"))

    def timeline(self, camera_id: int, profile: str, start: datetime, end: datetime) -> Timeline:
        params = {"profile": profile, "start": start.isoformat(), "end": end.isoformat()}
        return Timeline.model_validate(self._request("GET", f"/api/v1/cameras/{camera_id}/recordings", params=params))

    def playlist_url(self, camera_id: int, profile: str, start: datetime, end: datetime) -> str:
        query = urlencode({"profile": profile, "start": start.isoformat(), "end": end.isoformat()})
        return f"{self.base_url}/api/v1/playback/{camera_id}/index.m3u8?{query}"

    # ------------------------------------------------------------------ nodes
    def nodes(self) -> list[MediaNode]:
        return [MediaNode.model_validate(n) for n in self._request("GET", "/api/v1/nodes")]

    def node(self, node_id: int) -> MediaNode:
        return MediaNode.model_validate(self._request("GET", f"/api/v1/nodes/{node_id}"))

    def update_node(self, node_id: int, body: dict) -> MediaNode:
        return MediaNode.model_validate(self._request("PATCH", f"/api/v1/nodes/{node_id}", json=body))

    def node_action(self, node_id: int, action: str) -> MediaNode:
        if action not in ("drain", "cordon", "activate"):
            raise ValueError(f"unknown node action {action!r}")
        return MediaNode.model_validate(self._request("POST", f"/api/v1/nodes/{node_id}/{action}"))

    def delete_node(self, node_id: int, force: bool) -> None:
        self._request("DELETE", f"/api/v1/nodes/{node_id}", params={"force": str(force).lower()})

    # ------------------------------------------------------------------ storage volumes
    def add_volume(self, node_id: int, path: str, quota_gb: float | None) -> StorageVolume:
        body = {"path": path, "quota_gb": quota_gb, "accepting": True}
        return StorageVolume.model_validate(self._request("POST", f"/api/v1/nodes/{node_id}/volumes", json=body))

    def update_volume(self, node_id: int, volume_id: int, body: dict) -> StorageVolume:
        """body: {"quota_gb": float | None} and/or {"accepting": bool}."""
        return StorageVolume.model_validate(
            self._request("PATCH", f"/api/v1/nodes/{node_id}/volumes/{volume_id}", json=body)
        )

    def reorder_volumes(self, node_id: int, volume_ids: list[int]) -> list[StorageVolume]:
        rows = self._request("POST", f"/api/v1/nodes/{node_id}/volumes/reorder", json={"volume_ids": volume_ids})
        return [StorageVolume.model_validate(v) for v in rows]

    def delete_volume(self, node_id: int, volume_id: int, force: bool) -> None:
        self._request("DELETE", f"/api/v1/nodes/{node_id}/volumes/{volume_id}", params={"force": str(force).lower()})

    # ------------------------------------------------------------------ assignments
    def assignments(self) -> list[Assignment]:
        return [Assignment.model_validate(a) for a in self._request("GET", "/api/v1/assignments")]

    def move_camera(self, camera_id: int, node_id: int) -> Assignment:
        return Assignment.model_validate(
            self._request("PUT", f"/api/v1/assignments/{camera_id}", json={"node_id": node_id})
        )

    def assignment_history(self, camera_id: int) -> list[AssignmentHistory]:
        rows = self._request("GET", f"/api/v1/assignments/{camera_id}/history")
        return [AssignmentHistory.model_validate(r) for r in rows]

    def run_scheduler(self) -> None:
        self._request("POST", "/api/v1/assignments/run-scheduler")
