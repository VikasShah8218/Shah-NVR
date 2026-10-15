"""Video engine: MpvPlayer (playback logic) + one MpvSurface implementation per render mode."""

from PySide6.QtQml import qmlRegisterType

from app.video import render_mode

QML_MODULE = "Nvr.Video"


def register_video_types(mode: str) -> None:
    """Register `MpvPlayer` and `MpvSurface` (the GPU or CPU drawing item) for `import Nvr.Video`.

    QML always uses the same two names; only the class behind `MpvSurface` differs per mode.
    """
    render_mode.set_active(mode)
    from app.video.player import MpvPlayer

    if mode == "cpu":
        from app.video.sw_surface import MpvSwSurface as surface
    else:
        from app.video.gl_surface import MpvGlSurface as surface
    qmlRegisterType(MpvPlayer, QML_MODULE, 1, 0, "MpvPlayer")
    qmlRegisterType(surface, QML_MODULE, 1, 0, "MpvSurface")
