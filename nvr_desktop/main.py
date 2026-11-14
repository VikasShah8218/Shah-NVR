"""Shah-NVR desktop client (Python + PySide6 QML + libmpv).

Run:  py main.py   (inside `workon nvr`)

Startup order matters:
1. logging, then libmpv on PATH (before anything imports `mpv`);
2. the basic render loop (rendering on the GUI thread, required by both video surfaces);
3. QGuiApplication, fonts, the "C" numeric locale libmpv requires;
   then the render mode (GPU/OpenGL or CPU/software, app/video/render_mode.py) - before any window;
4. the stores (Python state for every page), registered as QML singletons under `import App`;
5. ui/Main.qml, then the sign-in session starts (`Auth`: asks central whether sign-in is needed; the shell is
   shown once the user is signed in, or right away when auth is off; docs/DESKTOP_AUTH_PLAN.md).
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

from PySide6.QtCore import QThreadPool, QUrl  # noqa: E402
from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon, QWindow  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance  # noqa: E402
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

from app.core.auth.permissions import PAGE_PERMS  # noqa: E402
from app.core.branding import PRODUCT_LOGO_PATH, PRODUCT_NAME  # noqa: E402

UI_DIR = BASE_DIR / "ui"
ASSETS_DIR = BASE_DIR / "assets"


def load_fonts() -> None:
    for font in (ASSETS_DIR / "fonts").glob("*.ttf"):
        if QFontDatabase.addApplicationFont(str(font)) < 0:
            logger.warning("Could not load font %s", font.name)


def choose_render_mode(preference: str) -> tuple[str, str | None]:
    """GPU (OpenGL) or CPU (software) drawing for this run, plus the GPU's name. Must run before the first window."""
    from app.video import render_mode

    renderer = render_mode.gl_renderer_name() if preference != "cpu" else None
    mode = render_mode.resolve(preference, renderer)
    logger.info("Render mode: %s (preference %s, OpenGL renderer: %s)", mode.upper(), preference,
                renderer if preference != "cpu" else "not probed")
    api = QSGRendererInterface.GraphicsApi
    QQuickWindow.setGraphicsApi(api.OpenGL if mode == "gpu" else api.Software)
    return mode, renderer if mode == "gpu" else None


def build_app():
    """Create the application, stores and QML engine. Returns (app, engine, singletons)."""
    QQuickStyle.setStyle("Basic")  # fully re-skinned by ui/theme + ui/components

    qt_app = QGuiApplication(sys.argv)
    qt_app.setApplicationName(PRODUCT_NAME)
    qt_app.setOrganizationName("ShahNVR")
    qt_app.setWindowIcon(QIcon(str(PRODUCT_LOGO_PATH)))
    locale.setlocale(locale.LC_NUMERIC, "C")  # libmpv requirement
    load_fonts()

    # Imported after QGuiApplication exists (QML types / image provider need it).
    from app.core.auth.session import AuthSession
    from app.core.context import AppContext
    from app.core.format import Formatter
    from app.core.icons import IconProvider
    from app.core.preferences import Preferences
    from app.core.router import Router
    from app.core.status import StatusHelper
    from app.core.toasts import ToastBus
    from app.core.utils import Utils
    from app.features.access.store import AccessStore
    from app.features.assignments.store import AssignmentsStore
    from app.features.audit.store import AuditStore
    from app.features.cameras.detail_store import CameraDetailStore
    from app.features.cameras.backfill_store import BackfillStore
    from app.features.cameras.options_store import EncoderCamerasStore, LiveCamerasStore, PlaybackCamerasStore
    from app.features.cameras.store import CamerasStore
    from app.features.dashboard.cluster_store import ClusterStore
    from app.features.dashboard.store import DashboardStore
    from app.features.groups.store import GroupsStore
    from app.features.groups.tree_store import LiveGroupsStore, ManageGroupsStore, PickerGroupsStore
    from app.features.live.store import LiveStore
    from app.features.live.ptz_store import PtzStore
    from app.features.live.ptz_ws_store import PtzWsStore
    from app.features.nodes.detail_store import NodeDetailStore
    from app.features.nodes.store import NodesStore
    from app.features.onvif.store import DiscoverStore
    from app.features.encoder.store import EncoderStore
    from app.features.playback.bookmarks_store import BookmarksStore
    from app.features.playback.store import PlaybackStore
    from app.features.settings.store import SettingsStore
    from app.video import register_video_types
    from app.video.player import set_source_signer

    prefs = Preferences()
    mode, gpu_name = choose_render_mode(settings.RENDER_MODE or prefs.renderMode)
    prefs.set_active_render_mode(mode, gpu_name)
    register_video_types(mode)  # import Nvr.Video: MpvPlayer + MpvSurface (GPU or CPU)
    toasts = ToastBus()
    auth = AuthSession(prefs.centralUrl)
    set_source_signer(auth.sign_url)  # playback playlists get a fresh token on every load
    ctx = AppContext(prefs, toasts, auth)
    router = Router()
    auth.sessionStarted.connect(lambda: _open_start_page(auth, router))
    cluster = ClusterStore(ctx)
    cameras = CamerasStore(ctx)
    nodes = NodesStore(ctx)
    playback_cameras = PlaybackCamerasStore(ctx)
    playback = PlaybackStore(ctx, cameras, nodes, playback_cameras)
    live_groups, manage_groups, picker_groups = LiveGroupsStore(ctx), ManageGroupsStore(ctx), PickerGroupsStore(ctx)
    singletons = {
        "Prefs": prefs,
        "Toasts": toasts,
        "Auth": auth,
        "Router": router,
        "Fmt": Formatter(),
        "Status": StatusHelper(),
        "Utils": Utils(toasts),
        "Cluster": cluster,
        "Cameras": cameras,
        "LiveCameras": LiveCamerasStore(ctx),
        "PlaybackCameras": playback_cameras,
        "EncoderCameras": EncoderCamerasStore(ctx),
        "LiveGroups": live_groups,
        "ManageGroups": manage_groups,
        "PickerGroups": picker_groups,
        "Groups": GroupsStore(ctx, [live_groups, manage_groups, picker_groups]),
        "Nodes": nodes,
        "Discover": DiscoverStore(ctx, cameras, nodes),
        "Dashboard": DashboardStore(ctx, cluster, nodes),
        "CameraDetail": CameraDetailStore(ctx, nodes),
        "Backfill": BackfillStore(ctx),
        "Encoder": EncoderStore(ctx, cameras),
        "NodeDetail": NodeDetailStore(ctx, cameras, nodes),
        "Assignments": AssignmentsStore(ctx),
        "Live": LiveStore(ctx, cameras, nodes),
        "Ptz": PtzStore(ctx),
        "PtzWs": PtzWsStore(ctx, cameras, nodes),
        "Playback": playback,
        "Bookmarks": BookmarksStore(ctx, playback),
        "SettingsPage": SettingsStore(ctx),
        "Access": AccessStore(ctx),
        "AuditLog": AuditStore(ctx),
    }
    for name, instance in singletons.items():
        qmlRegisterSingletonInstance(type(instance), "App", 1, 0, name, instance)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("ProductName", PRODUCT_NAME)
    engine.rootContext().setContextProperty("ProductLogo", QUrl.fromLocalFile(str(PRODUCT_LOGO_PATH)))
    engine.addImageProvider("icon", IconProvider())
    engine.load(UI_DIR / "Main.qml")
    return qt_app, engine, singletons


def _open_start_page(auth, router) -> None:
    """After sign-in: another user starts on their start page; the same user keeps their page if still allowed."""
    if auth.user_switched() or not auth.can(*PAGE_PERMS.get(router.page, ())):
        router.reset(auth.start_page())


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
    from app.core.single_instance import SingleInstance  # docs/DESKTOP_AUTH_PLAN.md DD2
    if SingleInstance.notify_running():
        logger.info("Shah-NVR is already running: showing that window")
        return 0
    qt_app, engine, singletons = build_app()
    if not engine.rootObjects():
        logger.error("Failed to load ui/Main.qml")
        return 1
    instance = SingleInstance(qt_app)
    instance.listen()
    window = engine.rootObjects()[0]
    def bring_to_front():
        if window.visibility() == QWindow.Visibility.Minimized:
            window.showNormal()
        window.raise_()
        window.requestActivate()

    instance.activated.connect(bring_to_front)
    singletons["Auth"].bringToFront.connect(bring_to_front)  # browser sign-in finished (DESKTOP_AUTH_V2_PLAN)
    from app.core.window_chrome import apply_window_chrome
    apply_window_chrome(window)
    restore_window(window, singletons["Prefs"])
    qt_app.aboutToQuit.connect(lambda: save_window(window, singletons["Prefs"]))
    singletons["Auth"].start()
    code = qt_app.exec()
    # Orderly shutdown: destroy QML (and with it every video player) while Python is fully alive,
    # then let running background requests finish.
    del engine
    QThreadPool.globalInstance().waitForDone(3000)
    return code


if __name__ == "__main__":
    sys.exit(main())
