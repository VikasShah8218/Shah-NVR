"""DiscoverStore: ONVIF discovery and lockout-safe camera onboarding for the desktop client."""

from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import Property, Signal, Slot

from app.core.context import AppContext
from app.core.store import BaseStore
from app.core.tasks import run_task
from app.features.cameras.store import CamerasStore
from app.features.nodes.store import NodesStore
from app.features.onvif.helpers import (device_label, format_offset, onvif_error_text, parse_address, profile_labels,
                                        profile_options)

ONLINE_STATES = {"READY", "ACTIVE", "DRAINING", "CORDONED"}
CHECK_CONCURRENCY = 4


class DiscoverStore(BaseStore):
    rowsChanged = Signal()
    selectedChanged = Signal()
    addRowsChanged = Signal()
    stateChanged = Signal()

    def __init__(self, ctx: AppContext, cameras: CamerasStore, nodes: NodesStore, parent=None):
        super().__init__(ctx, parent)
        self._cameras = cameras
        self._nodes = nodes
        self._rows: list[dict] = []
        self._manual: list[dict] = []
        self._selected: set[str] = set()
        self._add_rows: list[dict] = []
        self._scanned = False
        self._scanning = False
        self._busy = False
        self._scan_error = ""
        self._snapshot_files: set[str] = set()
        self.destroyed.connect(lambda: self._cleanup_snapshots())

    # ---------------------------------------------------------------- discovery
    @Slot(int)
    def scan(self, node_id: int = 0) -> None:
        if self._scanning:
            return
        self._scanning = True
        self._scan_error = ""
        self.stateChanged.emit()

        def ok(found):
            self._scanning = False
            self._scanned = True
            discovered = [row.to_qml() for row in found]
            keys = {(row["host"].lower(), row["port"]) for row in discovered}
            self._rows = [row for row in self._manual if (row["host"].lower(), row["port"]) not in keys] + discovered
            self._selected = {row["endpoint"] for row in self._rows if not row.get("camera_id")}
            self.rowsChanged.emit()
            self.selectedChanged.emit()
            self.stateChanged.emit()

        def err(exc: Exception):
            self._scanning = False
            self._scanned = True
            self._scan_error = onvif_error_text(exc)
            self.stateChanged.emit()

        run_task(lambda: self.api.onvif_discover(node_id or None), ok, err)

    @Slot(str, int, result=bool)
    def addAddress(self, value: str, node_id: int = 0) -> bool:
        target = parse_address(value)
        nodes = [node for node in self._nodes.nodes() if node.get("state") in ONLINE_STATES]
        node = next((n for n in nodes if n["id"] == node_id), nodes[0] if nodes else None)
        if target is None or node is None:
            self._scan_error = "Enter a valid camera address and choose an online media node."
            self.stateChanged.emit()
            return False
        host, port = target
        endpoint = f"manual:{host}:{port}"
        row = {
            "endpoint": endpoint, "host": host, "port": port,
            "xaddr": f"http://{host}:{port}/onvif/device_service", "name": None,
            "hardware": None, "location": None, "mac": None, "profiles": [], "profileLabels": [],
            "node_id": node["id"], "node_name": node["name"], "camera_id": None, "camera_name": None,
        }
        self._manual = [row] + [item for item in self._manual if item["endpoint"] != endpoint]
        self._rows = [row] + [item for item in self._rows if item["endpoint"] != endpoint]
        self._selected.add(endpoint)
        self._scan_error = ""
        self.rowsChanged.emit()
        self.selectedChanged.emit()
        self.stateChanged.emit()
        return True

    @Slot(str, bool)
    def select(self, endpoint: str, selected: bool) -> None:
        row = next((item for item in self._rows if item["endpoint"] == endpoint), None)
        if row is None or row.get("camera_id"):
            return
        if selected:
            self._selected.add(endpoint)
        else:
            self._selected.discard(endpoint)
        self.selectedChanged.emit()

    @Slot(bool)
    def selectAll(self, selected: bool) -> None:
        self._selected = ({row["endpoint"] for row in self._rows if not row.get("camera_id")}
                          if selected else set())
        self.selectedChanged.emit()

    @Slot(str, result=bool)
    def isSelected(self, endpoint: str) -> bool:
        return endpoint in self._selected

    # ---------------------------------------------------------------- add sheet
    @Slot()
    def beginAdd(self) -> None:
        self._cleanup_snapshots()
        picked = [row for row in self._rows if row["endpoint"] in self._selected and not row.get("camera_id")]
        self._add_rows = [{
            "device": dict(row), "endpoint": row["endpoint"], "status": "idle", "error": "", "probe": {},
            "name": "", "main": "", "sub": "", "recordSub": False, "enabled": True,
            "retentionDays": "7", "keepUntilFull": False, "snapshotUrl": "", "cameraId": 0,
            "mainOptions": [], "subOptions": [{"value": "", "label": "None"}],
        } for row in picked]
        self.addRowsChanged.emit()

    @Slot()
    def closeAdd(self) -> None:
        if self._busy:
            return
        self._cleanup_snapshots()
        self._add_rows = []
        self.addRowsChanged.emit()

    @Slot(str, str)
    def checkAll(self, username: str, password: str) -> None:
        todo = [dict(row) for row in self._add_rows if row["status"] in ("idle", "error")]
        if self._busy or not todo:
            return
        endpoints = {row["endpoint"] for row in todo}
        self._patch_statuses(endpoints, "checking")
        self._set_busy(True)

        def run() -> dict[str, dict]:
            results: dict[str, dict] = {}
            with ThreadPoolExecutor(max_workers=min(CHECK_CONCURRENCY, len(todo))) as pool:
                futures = {pool.submit(self._check_one, row, username, password): row["endpoint"] for row in todo}
                for future in as_completed(futures):
                    endpoint = futures[future]
                    try:
                        results[endpoint] = future.result()
                    except Exception as exc:
                        results[endpoint] = {"status": "error", "error": onvif_error_text(exc)}
            return results

        def done(results: dict[str, dict]) -> None:
            self._apply_results(results)
            self._set_busy(False)

        run_task(run, done, lambda exc: (self._set_busy(False), self.ctx.toasts.error(str(exc))))

    def _check_one(self, row: dict, username: str, password: str) -> dict:
        device = row["device"]
        body = self._device_body(device, username, password)
        probe = self.api.onvif_probe(body).to_qml()
        info = probe["info"]
        label = device_label(info.get("manufacturer"), info.get("model"))
        main = probe["suggested"].get("main") or ""
        sub = probe["suggested"].get("sub") or ""
        snapshot_url = ""
        snapshot_uri = next((p.get("snapshot") for p in probe["profiles"] if p["token"] == main), None)
        if snapshot_uri:
            try:
                data = self.api.onvif_snapshot({**body, "uri": snapshot_uri})
                snapshot_url = self._save_snapshot(data)
            except Exception:
                pass  # preview is optional; probing and adding still work
        return {
            "status": "ready", "error": "", "probe": probe,
            "name": row.get("name") or f'{label or device.get("name") or "Camera"} ({device["host"]})',
            "main": main, "sub": sub, "snapshotUrl": snapshot_url,
            "offsetText": format_offset(probe.get("clock", {}).get("offset_seconds")),
            "mainOptions": profile_options(probe["profiles"]),
            "subOptions": [{"value": "", "label": "None"}] + profile_options(probe["profiles"], main),
        }

    @staticmethod
    def _device_body(device: dict, username: str, password: str) -> dict:
        return {
            "node_id": device["node_id"], "host": device["host"], "port": device["port"],
            "xaddr": device.get("xaddr"), "username": username, "password": password,
        }

    def _save_snapshot(self, data: bytes) -> str:
        handle, filename = tempfile.mkstemp(prefix="shah-nvr-onvif-", suffix=".jpg")
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        self._snapshot_files.add(filename)
        return Path(filename).as_uri()

    @Slot(str, str, "QVariant")
    def updateRow(self, endpoint: str, field: str, value) -> None:
        if field not in {"name", "main", "sub", "recordSub", "enabled", "retentionDays", "keepUntilFull"}:
            return
        rows = [dict(row) for row in self._add_rows]
        for row in rows:
            if row["endpoint"] == endpoint and row["status"] == "ready":
                row[field] = value
                if field == "main":
                    profiles = row.get("probe", {}).get("profiles", [])
                    row["subOptions"] = [{"value": "", "label": "None"}] + profile_options(profiles, str(value))
                    if row.get("sub") == value:
                        row["sub"] = ""
                break
        self._add_rows = rows
        self.addRowsChanged.emit()

    @Slot(str, str)
    def addReady(self, username: str, password: str) -> None:
        todo = [dict(row) for row in self._add_rows if row["status"] == "ready"]
        if self._busy or not todo:
            return
        endpoints = {row["endpoint"] for row in todo}
        self._patch_statuses(endpoints, "adding")
        self._set_busy(True)

        def run() -> dict[str, dict]:
            results: dict[str, dict] = {}
            for row in todo:
                endpoint = row["endpoint"]
                try:
                    if not row.get("main"):
                        raise ValueError("Select a main video stream")
                    device = row["device"]
                    streams = [{"profile": "main", "token": row["main"], "record": True}]
                    if row.get("sub"):
                        streams.append({"profile": "sub", "token": row["sub"], "record": bool(row["recordSub"])})
                    retention = None if row["keepUntilFull"] else max(1, min(3650, int(row["retentionDays"] or 7)))
                    body = {
                        **self._device_body(device, username, password), "name": row["name"].strip() or None,
                        "enabled": bool(row["enabled"]), "retention_days": retention, "streams": streams,
                        "allow_duplicate": False,
                    }
                    camera = self.api.create_onvif_camera(body)
                    results[endpoint] = {
                        "status": "added", "error": "", "cameraId": camera.id, "cameraName": camera.name,
                    }
                except Exception as exc:
                    results[endpoint] = {"status": "error", "error": onvif_error_text(exc)}
            return results

        def done(results: dict[str, dict]) -> None:
            self._apply_results(results)
            self._set_busy(False)
            if any(result.get("status") == "added" for result in results.values()):
                self._rows = [
                    {**row, "camera_id": results[row["endpoint"]]["cameraId"],
                     "camera_name": results[row["endpoint"]]["cameraName"]}
                    if results.get(row["endpoint"], {}).get("status") == "added" else row
                    for row in self._rows
                ]
                self._selected.difference_update(
                    endpoint for endpoint, result in results.items() if result.get("status") == "added"
                )
                self.rowsChanged.emit()
                self.selectedChanged.emit()
                self._cameras.refresh()
                self.ctx.toasts.success("ONVIF camera added" if len(results) == 1 else "ONVIF cameras added")

        run_task(run, done, lambda exc: (self._set_busy(False), self.ctx.toasts.error(str(exc))))

    def _patch_statuses(self, endpoints: set[str], status: str) -> None:
        self._add_rows = [{**row, "status": status, "error": ""} if row["endpoint"] in endpoints else row
                          for row in self._add_rows]
        self.addRowsChanged.emit()

    def _apply_results(self, results: dict[str, dict]) -> None:
        self._add_rows = [{**row, **results.get(row["endpoint"], {})} for row in self._add_rows]
        self.addRowsChanged.emit()

    def _set_busy(self, value: bool) -> None:
        if value != self._busy:
            self._busy = value
            self.stateChanged.emit()

    def _cleanup_snapshots(self) -> None:
        for filename in self._snapshot_files:
            try:
                Path(filename).unlink(missing_ok=True)
            except OSError:
                pass
        self._snapshot_files.clear()

    # ---------------------------------------------------------------- QML properties
    rows = Property("QVariantList", lambda self: [
        {**row, "profileLabels": profile_labels(row.get("profiles"))} for row in self._rows
    ], notify=rowsChanged)
    selectedCount = Property(int, lambda self: len(self._selected), notify=selectedChanged)
    addRows = Property("QVariantList", lambda self: self._add_rows, notify=addRowsChanged)
    scanning = Property(bool, lambda self: self._scanning, notify=stateChanged)
    scanned = Property(bool, lambda self: self._scanned, notify=stateChanged)
    busy = Property(bool, lambda self: self._busy, notify=stateChanged)
    scanError = Property(str, lambda self: self._scan_error, notify=stateChanged)
    readyCount = Property(int, lambda self: sum(row["status"] == "ready" for row in self._add_rows),
                          notify=addRowsChanged)
    uncheckedCount = Property(int, lambda self: sum(row["status"] in ("idle", "error") for row in self._add_rows),
                              notify=addRowsChanged)
    addedCount = Property(int, lambda self: sum(row["status"] == "added" for row in self._add_rows),
                          notify=addRowsChanged)
