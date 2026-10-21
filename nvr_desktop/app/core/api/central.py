"""Central manager API client: one method per endpoint the desktop app uses.

Blocking (httpx) by design: stores call these through app/core/tasks.py::run_task, which runs them
on a worker thread, so the UI thread never waits on the network.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote, urlencode

import httpx

from app.core.api.errors import ApiError, raise_for_response
from app.core.api.encoder_models import EncoderChange, EncoderHistory, EncoderState
from app.core.api.models import (
    Assignment,
    AssignmentHistory,
    BackfillConfig,
    BackfillJob,
    BackfillProbe,
    ExportJob,
    Camera,
    ClusterHealth,
    LiveInfo,
    MediaNode,
    OnvifClock,
    OnvifDeviceState,
    OnvifDiscovered,
    OnvifProbe,
    OnvifServer,
    PtzResult,
    PtzState,
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

    # H2: no automatic retries, especially after an uncertain camera write.
    @staticmethod
    def _encoder_path(camera_id: int, profile: str) -> str:
        return f"/api/v1/cameras/{camera_id}/streams/{quote(profile, safe='')}/encoder"

    def encoder(self, camera_id: int, profile: str) -> EncoderState:
        return EncoderState.model_validate(self._request("GET", self._encoder_path(camera_id, profile), timeout=75))

    def encoder_mapping(self, camera_id: int, profile: str, token: str) -> EncoderState:
        return EncoderState.model_validate(self._request("PUT", self._encoder_path(camera_id, profile) + "/mapping",
                                                       json={"profile_token": token}, timeout=75))

    def encoder_check(self, camera_id: int, profile: str, body: dict) -> EncoderState:
        return EncoderState.model_validate(self._request("POST", self._encoder_path(camera_id, profile) + "/check",
                                                       json=body, timeout=75))

    def encoder_apply(self, camera_id: int, profile: str, body: dict) -> EncoderChange:
        # Central performs a 60s preflight followed by a bounded 100s apply/readback.
        return EncoderChange.model_validate(self._request("PUT", self._encoder_path(camera_id, profile),
                                                        json=body, timeout=190))

    def encoder_history(self, camera_id: int, profile: str) -> EncoderHistory:
        return EncoderHistory.model_validate(self._request("GET", self._encoder_path(camera_id, profile) + "/history"))

    def encoder_recovery(self, camera_id: int, profile: str) -> dict:
        return self._request("GET", self._encoder_path(camera_id, profile) + "/recovery")

    def encoder_resolve(self, camera_id: int, profile: str) -> dict:
        return self._request("POST", self._encoder_path(camera_id, profile) + "/resolve", timeout=75)

    # ------------------------------------------------------------------ plumbing
    def _request(self, method: str, path: str, *, raw: bool = False, **kwargs):
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(0, f"Central manager unreachable ({self.base_url})") from exc
        raise_for_response(response)
        if raw:
            return response
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

    def live(self, camera_id: int, access: str = "lan") -> LiveInfo:
        return LiveInfo.model_validate(self._request(
            "GET", f"/api/v1/cameras/{camera_id}/live", params={"access": access},
        ))

    def timeline(self, camera_id: int, profile: str, start: datetime, end: datetime) -> Timeline:
        params = {"profile": profile, "start": start.isoformat(), "end": end.isoformat()}
        return Timeline.model_validate(self._request("GET", f"/api/v1/cameras/{camera_id}/recordings", params=params))

    def playlist_url(self, camera_id: int, profile: str, start: datetime, end: datetime,
                     access: str = "lan", audio: bool = False) -> str:
        query = urlencode({"profile": profile, "start": start.isoformat(), "end": end.isoformat(),
                           "access": access})
        media = "audio.m3u8" if audio else "index.m3u8"
        return f"{self.base_url}/api/v1/playback/{camera_id}/{media}?{query}"

    # ------------------------------------------------------------------ H3 PTZ
    def ptz_open(self, camera_id: int, profile: str) -> PtzState:
        path = f"/api/v1/cameras/{camera_id}/streams/{quote(profile, safe='')}/ptz"
        return PtzState.model_validate(self._request("POST", path, timeout=60))

    def ptz_command(self, camera_id: int, profile: str, body: dict) -> PtzResult:
        path = f"/api/v1/cameras/{camera_id}/streams/{quote(profile, safe='')}/ptz/command"
        return PtzResult.model_validate(self._request("POST", path, json=body, timeout=60))

    # ------------------------------------------------------------------ L3 backfill
    def backfill(self, camera_id: int) -> BackfillConfig:
        return BackfillConfig.model_validate(self._request("GET", f"/api/v1/cameras/{camera_id}/backfill"))

    def backfill_probe(self, camera_id: int) -> BackfillProbe:
        return BackfillProbe.model_validate(self._request(
            "POST", f"/api/v1/cameras/{camera_id}/backfill/probe", timeout=60,
        ))

    def update_backfill(self, camera_id: int, body: dict) -> BackfillConfig:
        return BackfillConfig.model_validate(self._request(
            "PATCH", f"/api/v1/cameras/{camera_id}/backfill", json=body,
        ))

    def backfill_jobs(self, camera_id: int) -> list[BackfillJob]:
        rows = self._request("GET", f"/api/v1/cameras/{camera_id}/backfill/jobs", params={"limit": 50})
        return [BackfillJob.model_validate(row) for row in rows]

    def create_backfill_job(self, camera_id: int, body: dict) -> BackfillJob:
        return BackfillJob.model_validate(self._request(
            "POST", f"/api/v1/cameras/{camera_id}/backfill/jobs", json=body,
        ))

    # ------------------------------------------------------------------ recording exports
    def exports(self, camera_id: int) -> list[ExportJob]:
        rows = self._request("GET", "/api/v1/exports", params={"camera_id": camera_id, "limit": 50})
        return [ExportJob.model_validate(row) for row in rows]

    def create_export(self, body: dict) -> ExportJob:
        return ExportJob.model_validate(self._request("POST", "/api/v1/exports", json=body))

    def cancel_export(self, export_id: str) -> ExportJob:
        return ExportJob.model_validate(self._request("POST", f"/api/v1/exports/{export_id}/cancel"))

    def export_download_url(self, export_id: str, access: str = "lan") -> str:
        return f"{self.base_url}/api/v1/exports/{export_id}/download?{urlencode({'access': access})}"

    # ------------------------------------------------------------------ ONVIF H1
    def onvif_discover(self, node_id: int | None = None, seconds: float = 3.0) -> list[OnvifDiscovered]:
        body = {"node_id": node_id, "seconds": seconds}
        rows = self._request("POST", "/api/v1/onvif/discover", json=body, timeout=seconds + 15)
        return [OnvifDiscovered.model_validate(row) for row in rows]

    def onvif_probe(self, body: dict) -> OnvifProbe:
        return OnvifProbe.model_validate(
            self._request("POST", "/api/v1/onvif/probe", json=body, timeout=60)
        )

    def onvif_snapshot(self, body: dict) -> bytes:
        response = self._request("POST", "/api/v1/onvif/snapshot", json=body, timeout=30, raw=True)
        return response.content

    def create_onvif_camera(self, body: dict) -> Camera:
        return Camera.model_validate(
            self._request("POST", "/api/v1/onvif/cameras", json=body, timeout=60)
        )

    def onvif_device(self, camera_id: int) -> OnvifDeviceState:
        return OnvifDeviceState.model_validate(
            self._request("GET", f"/api/v1/onvif/cameras/{camera_id}/device", timeout=60)
        )

    def onvif_time_sync(self, camera_id: int) -> OnvifClock:
        return OnvifClock.model_validate(
            self._request("POST", f"/api/v1/onvif/cameras/{camera_id}/time-sync", timeout=60)
        )

    def onvif_set_ntp(self, camera_id: int, from_dhcp: bool, servers: list[str]) -> dict:
        return self._request(
            "POST", f"/api/v1/onvif/cameras/{camera_id}/ntp",
            json={"from_dhcp": from_dhcp, "servers": servers}, timeout=60,
        )

    def onvif_reboot(self, camera_id: int) -> dict:
        return self._request("POST", f"/api/v1/onvif/cameras/{camera_id}/reboot", timeout=60)

    # ------------------------------------------------------------------ nodes
    def nodes(self) -> list[MediaNode]:
        return [MediaNode.model_validate(n) for n in self._request("GET", "/api/v1/nodes")]

    def node(self, node_id: int) -> MediaNode:
        return MediaNode.model_validate(self._request("GET", f"/api/v1/nodes/{node_id}"))

    def update_node(self, node_id: int, body: dict) -> MediaNode:
        return MediaNode.model_validate(self._request("PATCH", f"/api/v1/nodes/{node_id}", json=body))

    def onvif_server(self, node_id: int) -> OnvifServer:
        return OnvifServer.model_validate(self._request("GET", f"/api/v1/nodes/{node_id}/onvif-server"))

    def update_onvif_server(self, node_id: int, body: dict) -> OnvifServer:
        return OnvifServer.model_validate(self._request(
            "PATCH", f"/api/v1/nodes/{node_id}/onvif-server", json=body,
        ))

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
