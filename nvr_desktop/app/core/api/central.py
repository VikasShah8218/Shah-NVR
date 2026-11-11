"""Central manager API client: one method per endpoint the desktop app uses.

Blocking (httpx) by design: stores call these through app/core/tasks.py::run_task, which runs them
on a worker thread, so the UI thread never waits on the network.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Protocol
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
    Bookmark,
    ExportJob,
    GroupDetail,
    Camera,
    CameraAlert,
    CameraGroup,
    CameraOption,
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


def _page(body: dict, model) -> tuple[list, int]:
    """(rows of one page, total rows) from a paged list response `{items, total, limit, offset}`."""
    return [model.model_validate(row) for row in body["items"]], body["total"]


def _clean(params: dict) -> dict:
    """Drop empty filters so the server applies its defaults."""
    return {k: v for k, v in params.items() if v is not None and v != ""}


def _scope(group_id: int | None, ungrouped: bool, recursive: bool) -> dict:
    """Camera group filter: directly in a group, its whole subtree (recursive) or no group (ungrouped)."""
    return {"group_id": group_id, "ungrouped": True if ungrouped else None,
            "recursive": True if recursive and group_id is not None else None}


class TokenSource(Protocol):
    """The sign-in session (app/core/auth/session.py::AuthSession); None when the client has none."""

    def token(self) -> str | None: ...
    def valid_token(self) -> str | None: ...
    def refresh_after_expired(self, stale: str | None) -> str: ...
    def report(self, code: str | None) -> None: ...


class CentralApi:
    def __init__(self, base_url: str, auth: TokenSource | None = None):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
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
    def _send(self, method: str, path: str, token: str | None, kwargs: dict) -> httpx.Response:
        headers = dict(kwargs.pop("headers", None) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            return self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ApiError(0, f"Central manager unreachable ({self.base_url})") from exc

    def _request(self, method: str, path: str, *, raw: bool = False, **kwargs):
        """One call. With a sign-in session: Bearer token; an expired token is refreshed once and the call repeated
        (safe for writes too: central's guard refuses before the handler runs); other 401s end the session."""
        token = self.auth.token() if self.auth else None
        response = self._send(method, path, token, dict(kwargs))
        code = response.headers.get("X-Auth-Error")
        if response.status_code == 401 and self.auth:
            if code == "token_expired":
                token = self.auth.refresh_after_expired(token)
                response = self._send(method, path, token, dict(kwargs))
                code = response.headers.get("X-Auth-Error")
            if response.status_code == 401:
                self.auth.report(code)
        elif response.status_code == 503 and code == "auth_syncing":  # central just started: one short retry
            time.sleep(1.5)
            response = self._send(method, path, token, dict(kwargs))
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
    def cameras(self, *, q: str | None = None, enabled: bool | None = None, node_id: int | None = None,
                status: str | None = None, limit: int = 50, offset: int = 0, group_id: int | None = None,
                ungrouped: bool = False, recursive: bool = False) -> tuple[list[Camera], int]:
        """One page of full camera rows, ordered by name. Returns (cameras, total)."""
        params = _clean({"q": (q or "").strip(), "enabled": enabled, "node_id": node_id, "status": status,
                         "limit": limit, "offset": offset, **_scope(group_id, ungrouped, recursive)})
        return _page(self._request("GET", "/api/v1/cameras", params=params), Camera)

    def cameras_by_ids(self, ids: list[int]) -> list[Camera]:
        """Full rows for just these cameras (live tiles, the picked playback camera). At most 200."""
        ids = sorted(set(ids))[:200]
        if not ids:
            return []
        return _page(self._request("GET", "/api/v1/cameras", params={"ids": ",".join(map(str, ids)),
                                                                     "limit": 200}), Camera)[0]

    def camera_options(self, *, q: str | None = None, enabled: bool | None = None, node_id: int | None = None,
                       limit: int = 50, offset: int = 0, group_id: int | None = None, ungrouped: bool = False,
                       recursive: bool = False) -> tuple[list[CameraOption], int]:
        """Small searchable camera rows for pickers, the live sidebar and the group tree. Returns (rows, total)."""
        params = _clean({"q": (q or "").strip(), "enabled": enabled, "node_id": node_id, "limit": limit,
                         "offset": offset, **_scope(group_id, ungrouped, recursive)})
        return _page(self._request("GET", "/api/v1/cameras/options", params=params), CameraOption)

    # ------------------------------------------------------------------ camera groups (lazy tree)
    def groups(self, parent_id: int | None = None, limit: int = 50, offset: int = 0) -> tuple[list[CameraGroup], int]:
        """Direct sub-groups of one group (None = the top level). Returns (rows, total)."""
        params = _clean({"parent_id": parent_id, "limit": limit, "offset": offset})
        return _page(self._request("GET", "/api/v1/groups", params=params), CameraGroup)

    def group(self, group_id: int) -> GroupDetail:
        return GroupDetail.model_validate(self._request("GET", f"/api/v1/groups/{group_id}"))

    def group_search(self, q: str, limit: int = 20, offset: int = 0) -> tuple[list[CameraGroup], int]:
        params = {"q": q.strip(), "limit": limit, "offset": offset}
        return _page(self._request("GET", "/api/v1/groups/search", params=params), CameraGroup)

    def create_group(self, name: str, description: str | None = None, parent_id: int | None = None) -> GroupDetail:
        body = {"name": name, "description": description, "parent_id": parent_id}
        return GroupDetail.model_validate(self._request("POST", "/api/v1/groups", json=body))

    def update_group(self, group_id: int, body: dict) -> GroupDetail:
        """Send only the keys to change; `{"parent_id": None}` moves the group to the top level."""
        return GroupDetail.model_validate(self._request("PATCH", f"/api/v1/groups/{group_id}", json=body))

    def delete_group(self, group_id: int, move_children: bool = False) -> None:
        params = {"move_children": "parent"} if move_children else None
        self._request("DELETE", f"/api/v1/groups/{group_id}", params=params)

    def assign_cameras(self, camera_ids: list[int], group_id: int | None) -> int:
        """Move cameras into a group (None = out of every group), at most 500. Returns how many changed."""
        body = {"camera_ids": sorted(set(camera_ids))[:500], "group_id": group_id}
        return self._request("POST", "/api/v1/groups/assign", json=body)["updated"]

    def alerts(self, *, level: str | None = None, limit: int = 10, offset: int = 0) -> tuple[list[CameraAlert], int, dict]:
        """Camera alerts built by central, danger first. Returns (rows, total, {"danger": n, "warning": n})."""
        body = self._request("GET", "/api/v1/cluster/alerts", params=_clean({"level": level, "limit": limit,
                                                                              "offset": offset}))
        rows, total = _page(body, CameraAlert)
        return rows, total, body["counts"]

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

    def ptz_session(self, camera_id: int, profile: str, access: str = "lan") -> dict:
        """Mint a direct-to-node PTZ WebSocket session. Returns the PtzState fields plus ws_url."""
        path = f"/api/v1/cameras/{camera_id}/streams/{quote(profile, safe='')}/ptz/session"
        return self._request("POST", path, params={"access": access}, timeout=60)

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

    def backfill_jobs(self, camera_id: int, limit: int = 10, offset: int = 0) -> tuple[list[BackfillJob], int]:
        body = self._request("GET", f"/api/v1/cameras/{camera_id}/backfill/jobs",
                             params={"limit": limit, "offset": offset})
        return _page(body, BackfillJob)

    def create_backfill_job(self, camera_id: int, body: dict) -> BackfillJob:
        return BackfillJob.model_validate(self._request(
            "POST", f"/api/v1/cameras/{camera_id}/backfill/jobs", json=body,
        ))

    # ------------------------------------------------------------------ recording exports
    def exports(self, camera_id: int, limit: int = 5, offset: int = 0) -> tuple[list[ExportJob], int]:
        body = self._request("GET", "/api/v1/exports", params={"camera_id": camera_id, "limit": limit, "offset": offset})
        return _page(body, ExportJob)

    def create_export(self, body: dict) -> ExportJob:
        return ExportJob.model_validate(self._request("POST", "/api/v1/exports", json=body))

    def cancel_export(self, export_id: str) -> ExportJob:
        return ExportJob.model_validate(self._request("POST", f"/api/v1/exports/{export_id}/cancel"))

    def export_download_url(self, export_id: str, access: str = "lan") -> str:
        return f"{self.base_url}/api/v1/exports/{export_id}/download?{urlencode({'access': access})}"

    def auth_headers(self) -> dict:
        """Authorization header for a download made outside this client (worker thread: may refresh first)."""
        token = self.auth.valid_token() if self.auth else None
        return {"Authorization": f"Bearer {token}"} if token else {}

    # ------------------------------------------------------------------ bookmarks
    def bookmarks(self, *, camera_id: int | None = None, profile: str | None = None, q: str | None = None,
                  start: datetime | None = None, end: datetime | None = None, order: str = "asc",
                  limit: int = 200, offset: int = 0) -> tuple[list[Bookmark], int]:
        """Search bookmarks. `start`/`end` = overlap with the window; `profile` also matches camera-wide ones.
        Returns (bookmarks, total)."""
        params: dict = {"order": order, "limit": limit}
        if offset:
            params["offset"] = offset
        if camera_id:
            params["camera_id"] = camera_id
        if profile:
            params["profile"] = profile
        if q and q.strip():
            params["q"] = q.strip()
        if start is not None:
            params["start"] = start.isoformat()
        if end is not None:
            params["end"] = end.isoformat()
        return _page(self._request("GET", "/api/v1/bookmarks", params=params), Bookmark)

    def create_bookmark(self, body: dict) -> Bookmark:
        return Bookmark.model_validate(self._request("POST", "/api/v1/bookmarks", json=body))

    def update_bookmark(self, bookmark_id: int, body: dict) -> Bookmark:
        return Bookmark.model_validate(self._request("PATCH", f"/api/v1/bookmarks/{bookmark_id}", json=body))

    def delete_bookmark(self, bookmark_id: int) -> None:
        self._request("DELETE", f"/api/v1/bookmarks/{bookmark_id}")

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
    def assignments(self, *, q: str | None = None, node_id: int | None = None, limit: int = 50,
                    offset: int = 0) -> tuple[list[Assignment], int]:
        params = _clean({"q": (q or "").strip(), "node_id": node_id, "limit": limit, "offset": offset})
        return _page(self._request("GET", "/api/v1/assignments", params=params), Assignment)

    def move_camera(self, camera_id: int, node_id: int) -> Assignment:
        return Assignment.model_validate(
            self._request("PUT", f"/api/v1/assignments/{camera_id}", json={"node_id": node_id})
        )

    def assignment_history(self, camera_id: int, limit: int = 10, offset: int = 0) -> tuple[list[AssignmentHistory], int]:
        body = self._request("GET", f"/api/v1/assignments/{camera_id}/history", params={"limit": limit, "offset": offset})
        return _page(body, AssignmentHistory)

    def run_scheduler(self) -> None:
        self._request("POST", "/api/v1/assignments/run-scheduler")

    # ------------------------------------------------------------------ sign-in, access grants, audit
    # (docs/DESKTOP_AUTH_PLAN.md; plain dicts: QML shows them as they come)
    def me(self) -> dict:
        return self._request("GET", "/api/v1/auth/me")

    def access_subjects(self) -> dict:
        """{roles: [name], users: [{id, username, display_name, roles, is_active}]}"""
        return self._request("GET", "/api/v1/access/subjects")

    def access_summary(self) -> list[dict]:
        """[{subject_type, subject, all_cameras, groups: count, cameras: count}]"""
        return self._request("GET", "/api/v1/access/grants")

    def access_grants(self, subject_type: str, subject: str) -> dict:
        """{subject_type, subject, all_cameras, groups: [{id, name}], cameras: [{id, name}]}"""
        return self._request("GET", "/api/v1/access/grants", params={"subject_type": subject_type, "subject": subject})

    def put_access_grants(self, body: dict) -> dict:
        return self._request("PUT", "/api/v1/access/grants", json=body)

    def audit(self, *, username: str | None = None, action: str | None = None, camera_id: int | None = None,
              status: str | None = None, start: datetime | None = None, end: datetime | None = None,
              limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        params = _clean({"username": (username or "").strip(), "action": (action or "").strip(),
                         "camera_id": camera_id or None, "status": status,
                         "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
                         "limit": limit, "offset": offset})
        body = self._request("GET", "/api/v1/audit", params=params)
        return body["items"], body["total"]
