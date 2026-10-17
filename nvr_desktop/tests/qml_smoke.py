"""Real desktop/QML smoke runner, isolated settings, fixtures and no network.

Run via test_desktop_qml.py so Qt and libmpv live in a dedicated process.
"""
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QSG_RHI_BACKEND"] = "software"
os.environ["RENDER_MODE"] = "cpu"

from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject, QSettings, QUrl, qInstallMessageHandler
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from unittest.mock import patch

from app.core.api.models import Camera, OnvifDiscovered
from app.core.poller import Poller
from app.core.preferences import Preferences
from app.core.store import BaseStore
from app.features.cameras.store import _decorate
from tests.test_api import CAMERA
from tests.test_onvif import DISCOVERED, PROBE
from tests.test_encoder import immediate, mock_api


def walk(obj):
    seen = set()
    todo = [obj]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        yield current
        todo.extend(current.children())
        if isinstance(current, QQuickWindow):
            todo.append(current.contentItem())
        if isinstance(current, QQuickItem):
            todo.extend(current.childItems())


def main():
    import main as desktop

    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    original_init = Preferences.__init__

    def isolated_init(self, parent=None):
        original_init(self, parent)
        self._store = QSettings(str(output / "settings.ini"), QSettings.Format.IniFormat)

    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    try:
        with patch.object(Preferences, "__init__", isolated_init), \
             patch.object(Poller, "start", lambda self, **kw: None), \
             patch.object(BaseStore, "fetch", lambda *a, **kw: None):
            app, engine, stores = desktop.build_app()
            assert engine.rootObjects(), messages
            window = engine.rootObjects()[0]
            router, cameras = stores["Router"], stores["Cameras"]
            camera = _decorate(Camera.model_validate({**CAMERA, "model": "AXIS M1125", "manufacturer": "AXIS",
                "onvif_host": "192.168.1.241", "clock_offset_seconds": -12}).to_qml())
            manual = _decorate(Camera.model_validate({**CAMERA, "id": 2, "name": "Manual disabled",
                "enabled": False, "model": None}).to_qml())
            cameras._apply([camera, manual])
            cameras._set_loading(False)
            stores["Cluster"]._apply({"cameras_total": 2, "cameras_enabled": 1, "streams_by_status": {"RECORDING": 1},
                "nodes_by_state": {"ACTIVE": 1}, "segments_last_hour": 10, "segments_total": 100})

            def settle():
                for _ in range(3):
                    app.processEvents()
                    QTest.qWait(20)

            def texts():
                return [o.property("text") for o in walk(window) if o.metaObject().indexOfProperty("text") >= 0]

            # Exercise the exact delegate contract that the old `model` role broke.
            engine.rootContext().setContextProperty("CameraRows", cameras.model)
            component = QQmlComponent(engine)
            component.setData(b'''import QtQuick
Item {
    Repeater {
        model: CameraRows
        delegate: Item {
            required property var model
            objectName: "role-" + model.id
            property string cameraName: model.name
            property bool cameraEnabled: model.enabled
            property var hardwareModel: model.deviceModel
        }
    }
}''', QUrl())
            role_root = component.create()
            assert role_root is not None, [e.toString() for e in component.errors()]
            first = next(o for o in walk(role_root) if o.objectName() == "role-1")
            assert first.property("cameraName") == "Gate"
            assert first.property("cameraEnabled") is True
            assert first.property("hardwareModel") == "AXIS M1125"
            second = next(o for o in walk(role_root) if o.objectName() == "role-2")
            assert second.property("cameraEnabled") is False

            for page in ("cameras", "live", "playback", "dashboard", "discover", "nodes", "assignments", "settings"):
                router.go(page)
                settle()
                if page in ("cameras", "live", "playback"):
                    assert "Gate" in texts(), (page, texts(), messages)
                if page == "cameras":
                    assert "Manual disabled" in texts()
                    assert window.grabWindow().save(str(output / "cameras.png"))

            router.go("live")
            stores["Live"].place(1, 0)
            settle()
            cameras._apply([{**camera, "name": "Gate renamed"}, manual])
            settle()
            assert first.property("cameraName") == "Gate renamed"
            assert texts().count("Gate renamed") >= 2  # list AND existing tile

            # Device tab, including nullable device fields, and all camera-detail tabs.
            detail = stores["CameraDetail"]
            router.go("camera", 1, {"tab": "device"})
            detail._apply_camera(1, camera)
            detail._set_loading(False)
            detail._device_busy = False
            detail._device = {"info": PROBE["info"], "clock": PROBE["clock"], "host": "192.168.1.241",
                "port": 80, "ntp": None, "network": None, "serviceNames": ["Media"], "offsetText": "-12 s"}
            detail.deviceChanged.emit()
            settle()
            page = window.findChild(QObject, "cameraDetail")
            assert page is not None and "M1125" in texts()
            assert window.grabWindow().save(str(output / "device.png"))
            for tab in ("overview", "recordings", "assignment", "device"):
                page.setProperty("tab", tab)
                settle()

            # Real Video tab, fake API: exercise field bindings, alternative H265
            # options, review dialog and stream navigation without touching a camera.
            encoder = stores["Encoder"]
            encoder._ctx.central = mock_api()
            with patch("app.features.encoder.store.run_task", immediate):
                page.setProperty("tab", "video")
                settle()
                assert "Video encoder" in " ".join(texts())
                assert "Gate" in texts()
                field = next(o for o in walk(window) if o.objectName() == "encoderInput-bitrate_kbps")
                field.forceActiveFocus()
                field.setProperty("text", "4096")
                QMetaObject.invokeMethod(field, "textEdited")
                encoder.refreshStatus()
                settle()
                assert field.property("activeFocus") and field.property("text") == "4096"
                assert next(o for o in walk(window) if o.objectName() == "encoderInput-bitrate_kbps") == field
                settle()
                assert encoder.view["canApply"] and not encoder.view["errors"]
                assert "44.2 GB/day" in " ".join(texts())
                button = next(o for o in walk(window) if o.objectName() == "encoderReview")
                QMetaObject.invokeMethod(button, "clicked")
                settle()
                dialog = next(o for o in walk(window) if o.objectName() == "encoderConfirmation")
                assert dialog.property("visible")
                encoder._ctx.central.encoder_apply.assert_not_called()
                dialog.close()
                encoder.confirm()
                settle()
                encoder._ctx.central.encoder_apply.assert_called_once()
                assert window.grabWindow().save(str(output / "video.png"))
                fallback = "Camera advertises Media2, but GetProfiles failed (HTTP 503). Using Media1 fallback."
                state = dict(encoder.view["state"])
                state["warnings"] = [fallback]
                encoder._accept_state(state)
                encoder.changed.emit()
                settle()
                assert fallback in texts()
                page.setProperty("tab", "overview")
                settle()
                assert encoder.view["state"] == {}

            router.go("discover")
            discover = stores["Discover"]
            discover._rows = [OnvifDiscovered.model_validate(DISCOVERED).to_qml()]
            discover.rowsChanged.emit()
            discover.selectAll(True)
            discover.beginAdd()
            settle()
            sheet = window.findChild(QObject, "addOnvifSheet")
            assert sheet is not None
            sheet.open()
            QTest.qWait(300)  # finish the drawer's entrance animation
            settle()
            discover._apply_results({DISCOVERED["endpoint"]: {
                "status": "ready", "probe": PROBE, "name": "Gate", "main": "main-token", "sub": "",
                "mainOptions": [{"value": "main-token", "label": "Main H264 1280x720"}],
                "offsetText": "-12 s"}})
            settle()
            name_field = next((o for o in walk(window) if o.objectName() == "onvifName-" + DISCOVERED["endpoint"]), None)
            assert name_field is not None
            name_field.setProperty("text", "New gate name")
            QMetaObject.invokeMethod(name_field, "editingFinished")
            settle()
            assert discover.addRows[0]["name"] == "New gate name"
            assert window.grabWindow().save(str(output / "onboarding.png"))
            sheet.close()
            QTest.qWait(300)
            settle()
            router.go("cameras")
            settle()
            assert "Gate renamed" in texts()

            # No page should generate a QML warning, binding error or layout loop.
            bad = [m for m in messages if any(s in m for s in
                (".qml:", "ReferenceError", "TypeError", "Binding loop", "Cannot assign", "failed to load"))]
            assert not bad, "\n".join(bad)
            role_root.deleteLater()
            window.close()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            print("QML smoke passed: camera roles, populated pages, live metadata updates, Device, H2 Video and onboarding")
    finally:
        qInstallMessageHandler(previous)


if __name__ == "__main__":
    main()
