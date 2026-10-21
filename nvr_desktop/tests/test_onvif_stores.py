"""Offline workflow and stale-response regressions. No cameras or services are contacted."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication, QObject, Signal

from app.core.api.errors import ApiError
from app.core.api.models import OnvifDiscovered, OnvifProbe
from app.core.list_model import DictListModel
from app.core.poller import Poller
from app.features.cameras.detail_store import CameraDetailStore
from app.features.cameras.store import CAMERA_ROLES, _decorate
from app.features.onvif.store import DiscoverStore
from tests.test_onvif import DISCOVERED, PROBE


class Context(QObject):
    centralChanged = Signal()


@pytest.fixture
def setup(monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(Poller, "start", lambda self: None)
    ctx = Context()
    ctx.central = Mock()
    ctx.prefs = SimpleNamespace(pollSeconds=5)
    ctx.toasts = Mock()
    cameras, nodes = Mock(), Mock()
    nodes.nodes.return_value = [{"id": 2, "name": "node-2", "state": "ACTIVE"}]
    store = DiscoverStore(ctx, cameras, nodes)

    def immediate(fn, ok, err):
        try:
            result = fn()
        except Exception as exc:
            err(exc)
        else:
            ok(result)

    monkeypatch.setattr("app.features.onvif.store.run_task", immediate)
    monkeypatch.setattr("app.features.cameras.detail_store.run_task", immediate)
    monkeypatch.setattr("app.core.store.run_task", immediate)
    ctx.central.onvif_discover.return_value = [OnvifDiscovered.model_validate(DISCOVERED)]
    ctx.central.onvif_probe.return_value = OnvifProbe.model_validate(PROBE)
    ctx.central.onvif_snapshot.side_effect = ApiError(502, "No snapshot")
    yield app, ctx, cameras, store


def checked(store):
    store.scan(2)
    store.beginAdd()
    store.checkAll("admin", "test-password")


def test_camera_roles_do_not_shadow_qml_row():
    assert "model" not in CAMERA_ROLES
    row = _decorate({"id": 1, "model": "AXIS M1125", "streams": [], "enabled": True})
    assert row["deviceModel"] == row["model"] == "AXIS M1125"
    for role in ("model", "modelData", "index"):
        with pytest.raises(ValueError):
            DictListModel(["id", role])


def test_onboard_success_snapshot_failure_is_optional(setup):
    _, ctx, cameras, store = setup
    checked(store)
    assert store.readyCount == 1 and not store.busy
    assert store.addRows[0]["snapshotUrl"] == ""
    ctx.central.create_onvif_camera.return_value = SimpleNamespace(id=7, name="Gate")
    store.addReady("admin", "test-password")
    body = ctx.central.create_onvif_camera.call_args.args[0]
    assert body["streams"] == [{"profile": "main", "token": "main-token", "record": True}]
    assert body["allow_duplicate"] is False and body["retention_days"] == 7
    assert store.addedCount == 1 and store.selectedCount == 0
    assert store.rows[0]["camera_id"] == 7
    cameras.refresh.assert_called_once()
    store.addReady("admin", "test-password")
    ctx.central.create_onvif_camera.assert_called_once()


def test_wrong_password_is_not_automatically_retried(setup):
    _, ctx, _, store = setup
    ctx.central.onvif_probe.side_effect = ApiError(401, "denied", code="not_authorized")
    checked(store)
    assert store.uncheckedCount == 1 and store.readyCount == 0
    assert "Not retried automatically" in store.addRows[0]["error"]
    ctx.central.onvif_probe.assert_called_once()
    ctx.central.onvif_snapshot.assert_not_called()
    store.addReady("admin", "test-password")
    ctx.central.create_onvif_camera.assert_not_called()


def test_no_video_profile_cannot_be_added(setup):
    _, ctx, _, store = setup
    probe = deepcopy(PROBE)
    probe["profiles"][0]["encoding"] = "JPEG"
    ctx.central.onvif_probe.return_value = OnvifProbe.model_validate(probe)
    checked(store)
    assert store.readyCount == 0
    assert "No H.264/H.265" in store.addRows[0]["error"]


def test_duplicate_discovered_camera_is_not_selectable(setup):
    _, ctx, _, store = setup
    ctx.central.onvif_discover.return_value = [OnvifDiscovered.model_validate({**DISCOVERED, "camera_id": 7})]
    store.scan(2)
    store.select(DISCOVERED["endpoint"], True)
    store.selectAll(True)
    store.beginAdd()
    assert store.selectedCount == 0 and store.addRows == []


def test_manual_address_requires_selected_node_online(setup):
    _, _, _, store = setup
    assert not store.addAddress("camera.local", 999)
    assert store.addAddress("camera.local:8080", 2)
    assert store.rows[0]["port"] == 8080


def test_changing_main_removes_duplicate_sub(setup):
    _, ctx, _, store = setup
    probe = deepcopy(PROBE)
    probe["profiles"].append({**probe["profiles"][0], "token": "sub-token"})
    probe["suggested"]["sub"] = "sub-token"
    ctx.central.onvif_probe.return_value = OnvifProbe.model_validate(probe)
    checked(store)
    store.updateRow(DISCOVERED["endpoint"], "main", "sub-token")
    assert store.addRows[0]["sub"] == ""
    assert "sub-token" not in [p["value"] for p in store.addRows[0]["subOptions"]]


def test_close_ignores_late_probe_result(setup, monkeypatch):
    _, _, _, store = setup
    store.scan(2)
    store.beginAdd()
    pending = []
    monkeypatch.setattr("app.features.onvif.store.run_task", lambda *args: pending.append(args))
    store.checkAll("admin", "test-password")
    assert store.busy
    store.closeAdd()
    pending[0][1]({DISCOVERED["endpoint"]: {"status": "ready"}})
    assert not store.busy and store.addRows == []


def test_server_change_ignores_old_scan(setup, monkeypatch):
    _, ctx, _, store = setup
    pending = []
    monkeypatch.setattr("app.features.onvif.store.run_task", lambda *args: pending.append(args))
    store.scan(2)
    ctx.centralChanged.emit()
    pending[0][1]([OnvifDiscovered.model_validate(DISCOVERED)])
    assert store.rows == [] and not store.scanning


def test_device_switch_ignores_stale_success_and_error(setup, monkeypatch):
    _, ctx, _, _ = setup
    detail = CameraDetailStore(ctx)
    pending = []
    monkeypatch.setattr("app.core.store.run_task", lambda *args: pending.append(args))
    monkeypatch.setattr(detail, "refresh", lambda: None)
    detail.cameraId = 1
    detail.loadDevice()
    detail.cameraId = 2
    detail.loadDevice()
    assert len(pending) == 2  # old camera must not block a new read
    pending[0][1]({"info": {"model": "Old"}})
    assert detail.device == {} and detail.deviceBusy
    pending[1][2](ApiError(401, "denied", code="not_authorized"))
    assert not detail.deviceBusy and "Wrong username" in detail.deviceError


def test_device_action_completion_cannot_change_new_camera(setup, monkeypatch):
    _, ctx, _, _ = setup
    detail = CameraDetailStore(ctx)
    pending = []
    monkeypatch.setattr("app.features.cameras.detail_store.run_task", lambda *args: pending.append(args))
    detail.cameraId = 1
    detail.reboot()
    detail.cameraId = 2
    pending[0][1]({"message": "rebooting"})
    assert not detail.deviceBusy and detail.device == {}
    ctx.toasts.success.assert_not_called()


def test_ntp_success_signal_only_after_success(setup, monkeypatch):
    _, ctx, _, _ = setup
    detail = CameraDetailStore(ctx)
    detail.cameraId = 1
    monkeypatch.setattr(detail, "loadDevice", lambda: None)
    saved = []
    detail.ntpSaved.connect(lambda: saved.append(True))
    ctx.central.onvif_set_ntp.side_effect = ApiError(502, "unsupported")
    detail.setNtp(False, "clock.local")
    assert not saved and not detail.deviceBusy
    ctx.central.onvif_set_ntp.side_effect = None
    detail.setNtp(False, "clock.local, 192.168.1.3")
    assert saved == [True]
    ctx.central.onvif_set_ntp.assert_called_with(1, False, ["clock.local", "192.168.1.3"])


def test_scan_can_finish_after_add_sheet_closed(setup, monkeypatch):
    _, _, _, store = setup
    pending = []
    monkeypatch.setattr("app.features.onvif.store.run_task", lambda *args: pending.append(args))
    store.scan(2)
    store.closeAdd()
    pending[0][1]([OnvifDiscovered.model_validate(DISCOVERED)])
    assert not store.scanning and len(store.rows) == 1


def test_add_duplicate_error_is_not_retried(setup):
    _, ctx, _, store = setup
    checked(store)
    ctx.central.create_onvif_camera.side_effect = ApiError(409, "Camera already exists", code="duplicate")
    store.addReady("admin", "test-password")
    store.addReady("admin", "test-password")
    assert store.addRows[0]["error"] == "Camera already exists"
    ctx.central.create_onvif_camera.assert_called_once()


def test_memory_only_snapshot(setup):
    _, ctx, _, store = setup
    ctx.central.onvif_snapshot.side_effect = None
    ctx.central.onvif_snapshot.return_value = b"jpeg"
    checked(store)
    assert store.addRows[0]["snapshotUrl"] == "data:image/jpeg;base64,anBlZw=="
    store.closeAdd()
    assert store.addRows == []


def test_retention_validation_does_not_send_request(setup):
    _, ctx, _, store = setup
    checked(store)
    store.updateRow(DISCOVERED["endpoint"], "retentionDays", "0")
    store.addReady("admin", "test-password")
    ctx.central.create_onvif_camera.assert_not_called()
    assert "Retention" in store.addRows[0]["error"]
