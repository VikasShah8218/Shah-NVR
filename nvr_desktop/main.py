"""Shah-NVR desktop client (Python + PySide6 QML + libmpv).

Run:  py main.py   (inside `workon nvr`)

Startup order matters:
1. logging, then libmpv on PATH (before anything imports `mpv`);
2. the basic render loop (rendering on the GUI thread, required by both video surfaces);
3. QGuiApplication, fonts, the "C" numeric locale libmpv requires;
   then the render mode (GPU/OpenGL or CPU/software, app/video/render_mode.py) - before any window;
4. the stores (Python state for every page), registered as QML singletons under `import App`;
5. ui/Main.qml.
"""

import locale
import logging
import os
import sys

from settings.settings import BASE_DIR, settings

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("nvr_desktop")

from app.video.loader import LibmpvMissingError, prepare_libmpv  # noqa: E402

try:
    prepare_libmpv(settings.MPV_DLL_DIR)
except LibmpvMissingError as exc:
    logger.error("%s", exc)
    sys.exit(1)

os.environ.setdefault("QSG_RENDER_LOOP", "basic")  # see app/video/gl_surface.py

from PySide6.QtCore import QThreadPool  # noqa: E402
from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon, QWindow  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance  # noqa: E402
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

UI_DIR = BASE_DIR / "ui"
ASSETS_DIR = BASE_DIR / "assets"


def load_fonts() -> None:
    for font in (ASSETS_DIR / "fonts").glob("*.ttf"):
        if QFontDatabase.addApplicationFont(str(font)) < 0:
            logger.warning("Could not load font %s", font.name)


def choose_render_mode(preference: str) -> str:
    """GPU (OpenGL) or CPU (software) drawing for this run. Must run before the first window."""
    from app.video import render_mode

    renderer = render_mode.gl_renderer_name() if preference == "auto" else None
    mode = render_mode.resolve(preference, renderer)
    logger.info("Render mode: %s (preference %s, OpenGL renderer: %s)", mode.upper(), preference,
                renderer if preference == "auto" else "not probed")
    api = QSGRendererInterface.GraphicsApi
    QQuickWindow.setGraphicsApi(api.OpenGL if mode == "gpu" else api.Software)
    return mode


def build_app():
    """Create the application, stores and QML engine. Returns (app, engine, singletons)."""
    QQuickStyle.setStyle("Basic")  # fully re-skinned by ui/theme + ui/components

    qt_app = QGuiApplication(sys.argv)
    qt_app.setApplicationName(settings.APP_NAME)
    qt_app.setOrganizationName("ShahNVR")
    qt_app.setWindowIcon(QIcon(str(ASSETS_DIR / "app-icon.svg")))
    locale.setlocale(locale.LC_NUMERIC, "C")  # libmpv requirement
    load_fonts()

    # Imported after QGuiApplication exists (QML types / image provider need it).
    from app.core.context import AppContext
    from app.core.format import Formatter
    from app.core.icons import IconProvider
    from app.core.preferences import Preferences
    from app.core.router import Router
    from app.core.status import StatusHelper
    from app.core.toasts import ToastBus
    from app.core.utils import Utils
    from app.features.assignments.store import AssignmentsStore
    from app.features.cameras.detail_store import CameraDetailStore
    from app.features.cameras.store import CamerasStore
    from app.features.dashboard.cluster_store import ClusterStore
    from app.features.dashboard.store import DashboardStore
    from app.features.live.store import LiveStore
    from app.features.nodes.detail_store import NodeDetailStore
    from app.features.nodes.store import NodesStore
    from app.features.playback.store import PlaybackStore
    from app.features.settings.store import SettingsStore
    from app.video import register_video_types

    prefs = Preferences()
    mode = choose_render_mode(settings.RENDER_MODE or prefs.renderMode)
    prefs.set_active_render_mode(mode)
    register_video_types(mode)  # import Nvr.Video: MpvPlayer + MpvSurface (GPU or CPU)
    toasts = ToastBus()
    ctx = AppContext(prefs, toasts)
    cluster = ClusterStore(ctx)
    cameras = CamerasStore(ctx)
    nodes = NodesStore(ctx)
    singletons = {
        "Prefs": prefs,
        "Toasts": toasts,
        "Router": Router(),
        "Fmt": Formatter(),
        "Status": StatusHelper(),
        "Utils": Utils(toasts),
        "Cluster": cluster,
        "Cameras": cameras,
        "Nodes": nodes,
        "Dashboard": DashboardStore(ctx, cluster, cameras, nodes),
        "CameraDetail": CameraDetailStore(ctx),
        "NodeDetail": NodeDetailStore(ctx),
        "Assignments": AssignmentsStore(ctx),
        "Live": LiveStore(ctx),
        "Playback": PlaybackStore(ctx, cameras, nodes),
        "SettingsPage": SettingsStore(ctx),
    }
    for name, instance in singletons.items():
        qmlRegisterSingletonInstance(type(instance), "App", 1, 0, name, instance)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("icon", IconProvider())
    engine.load(UI_DIR / "Main.qml")
    return qt_app, engine, singletons


def restore_window(window: QQuickWindow, prefs) -> None:
    """Reopen where the user left the window (if that place is still on a connected screen)."""
    geometry, maximized = prefs.window_state()
    if geometry is not None and any(s.availableGeometry().intersects(geometry) for s in QGuiApplication.screens()):
        window.setGeometry(geometry)
    if maximized:
        window.showMaximized()


def save_window(window: QQuickWindow, prefs) -> None:
    visibility = window.visibility()
    if visibility == QWindow.Visibility.FullScreen:  # Live/Playback fullscreen is not a window state to keep
        return
    maximized = visibility == QWindow.Visibility.Maximized
    prefs.save_window_state(None if maximized else window.geometry(), maximized)


def main() -> int:
    qt_app, engine, singletons = build_app()
    if not engine.rootObjects():
        logger.error("Failed to load ui/Main.qml")
        return 1
    window = engine.rootObjects()[0]
    restore_window(window, singletons["Prefs"])
    qt_app.aboutToQuit.connect(lambda: save_window(window, singletons["Prefs"]))
    code = qt_app.exec()
    # Orderly shutdown: destroy QML (and with it every video player) while Python is fully alive,
    # then let running background requests finish.
    del engine
    QThreadPool.globalInstance().waitForDone(3000)
    return code


if __name__ == "__main__":
    sys.exit(main())
