"""Which way video is drawn: "gpu" (OpenGL) or "cpu" (libswscale + Qt Quick software renderer).

Chosen once at startup (main.py), before the first window exists, because Qt Quick's graphics API
cannot change afterwards. The user's preference is "auto" | "cpu" | "gpu"; "auto" means GPU mode when
a real (hardware) OpenGL driver is present, otherwise CPU mode.

Why not run GPU mode everywhere: without a GPU driver, Windows/Qt fall back to a CPU-emulated OpenGL
(Mesa llvmpipe / "GDI Generic"). mpv's multi-pass GPU pipeline then runs on the CPU at full video
resolution: ~75% CPU and ~1 fps for 16 tiles. CPU mode instead scales each frame straight to tile size
in one SIMD pass (~1.6 ms per 1080p frame), which is what Chrome does.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PREFERENCES = ("auto", "cpu", "gpu")
_SOFTWARE_GL = ("llvmpipe", "softpipe", "swiftshader", "gdi generic", "microsoft basic render", "software")
_GL_RENDERER = 0x1F01

_active = "gpu"


def active() -> str:
    """The render mode of this process ("gpu" | "cpu")."""
    return _active


def set_active(mode: str) -> None:
    global _active
    if mode not in ("gpu", "cpu"):
        raise ValueError(f"unknown render mode {mode!r}")
    _active = mode


def is_software_gl(renderer: str | None) -> bool:
    """True when an OpenGL renderer string names a CPU emulation (or nothing at all)."""
    name = (renderer or "").strip().lower()
    return not name or any(marker in name for marker in _SOFTWARE_GL)


def gl_renderer_name() -> str | None:
    """GL_RENDERER of the OpenGL driver Qt would use, or None if no OpenGL context can be created.

    Needs a QGuiApplication; must run before the first QQuickWindow.
    """
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext

    context = QOpenGLContext()
    if not context.create():
        return None
    surface = QOffscreenSurface()
    surface.setFormat(context.format())
    surface.create()
    try:
        if not context.makeCurrent(surface):
            return None
        name = context.functions().glGetString(_GL_RENDERER)
        context.doneCurrent()
        return name.decode(errors="replace") if isinstance(name, bytes) else name
    finally:
        surface.destroy()


def resolve(preference: str, renderer: str | None) -> str:
    """User preference + detected OpenGL renderer -> "gpu" | "cpu"."""
    if preference == "cpu":
        return "cpu"
    if preference == "gpu":
        return "gpu"
    return "cpu" if is_software_gl(renderer) else "gpu"
