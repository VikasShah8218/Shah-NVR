"""Minimal, memory-safe wrapper around libmpv's OpenGL render API (mpv/render.h, mpv/render_gl.h).

Why not python-mpv's MpvRenderContext? It builds the C parameter array from temporary Python objects;
ctypes copies only the raw struct bytes into the array, so the buffers those structs point to (the
"opengl" string, the init-params struct) can be freed before libmpv reads them. On Windows that shows
up as heap corruption (0xC0000374) when the context is created. Here every buffer is an attribute of
the object, so it lives exactly as long as libmpv may use it.

Threading: create(), render() and free() must run on the thread whose OpenGL context is current
(the Qt Quick render thread). The update callback is invoked by libmpv from its own threads.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable

import mpv

# Parameter type ids from mpv/render.h
_PARAM_INVALID = 0
_PARAM_API_TYPE = 1
_PARAM_OPENGL_INIT_PARAMS = 2
_PARAM_OPENGL_FBO = 3
_PARAM_FLIP_Y = 4

_GetProcAddressFn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
_UpdateFn = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class _Param(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("data", ctypes.c_void_p)]


class _OpenGLInitParams(ctypes.Structure):
    _fields_ = [
        ("get_proc_address", _GetProcAddressFn),
        ("get_proc_address_ctx", ctypes.c_void_p),
        ("extra_exts", ctypes.c_char_p),
    ]


class _OpenGLFbo(ctypes.Structure):
    _fields_ = [("fbo", ctypes.c_int), ("w", ctypes.c_int), ("h", ctypes.c_int), ("internal_format", ctypes.c_int)]


_NOOP_UPDATE = _UpdateFn(lambda _userdata: None)

# A separate ctypes handle to the same libmpv DLL, so our argtypes/restype don't clash with the
# error-checking wrappers python-mpv installs on its own function objects.
_lib = ctypes.CDLL(mpv.backend._name)
_lib.mpv_render_context_create.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(_Param)]
_lib.mpv_render_context_create.restype = ctypes.c_int
_lib.mpv_render_context_render.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Param)]
_lib.mpv_render_context_render.restype = ctypes.c_int
_lib.mpv_render_context_set_update_callback.argtypes = [ctypes.c_void_p, _UpdateFn, ctypes.c_void_p]
_lib.mpv_render_context_set_update_callback.restype = None
_lib.mpv_render_context_free.argtypes = [ctypes.c_void_p]
_lib.mpv_render_context_free.restype = None


class GlRenderContext:
    def __init__(self, player: mpv.MPV, get_proc_address: Callable[[bytes], int]):
        # All of these must stay alive while libmpv may read them.
        self._get_proc_address = _GetProcAddressFn(lambda _ctx, name: get_proc_address(name) or 0)
        self._api_type = ctypes.c_char_p(b"opengl")
        self._init_params = _OpenGLInitParams(self._get_proc_address, None, None)
        self._fbo = _OpenGLFbo(0, 0, 0, 0)
        self._flip_y = ctypes.c_int(0)
        self._update_fn = _NOOP_UPDATE
        self._handle = ctypes.c_void_p()

        create_params = (_Param * 3)(
            _Param(_PARAM_API_TYPE, ctypes.cast(self._api_type, ctypes.c_void_p)),
            _Param(_PARAM_OPENGL_INIT_PARAMS, ctypes.cast(ctypes.pointer(self._init_params), ctypes.c_void_p)),
            _Param(_PARAM_INVALID, None),
        )
        player_handle = ctypes.cast(player.handle, ctypes.c_void_p)
        rc = _lib.mpv_render_context_create(ctypes.byref(self._handle), player_handle, create_params)
        if rc < 0:
            raise RuntimeError(f"mpv_render_context_create failed ({rc})")

        self._render_params = (_Param * 3)(
            _Param(_PARAM_OPENGL_FBO, ctypes.cast(ctypes.pointer(self._fbo), ctypes.c_void_p)),
            _Param(_PARAM_FLIP_Y, ctypes.cast(ctypes.pointer(self._flip_y), ctypes.c_void_p)),
            _Param(_PARAM_INVALID, None),
        )

    def set_update_callback(self, callback: Callable[[], None] | None) -> None:
        """`callback` runs on a libmpv thread whenever a new frame should be drawn."""
        self._update_fn = _UpdateFn(lambda _userdata: callback() if callback else None)
        _lib.mpv_render_context_set_update_callback(self._handle, self._update_fn, None)

    def render(self, fbo: int, width: int, height: int, flip_y: bool = False) -> None:
        self._fbo.fbo, self._fbo.w, self._fbo.h = fbo, width, height
        self._flip_y.value = int(flip_y)
        _lib.mpv_render_context_render(self._handle, self._render_params)

    def free(self) -> None:
        if self._handle:
            _lib.mpv_render_context_set_update_callback(self._handle, _NOOP_UPDATE, None)
            _lib.mpv_render_context_free(self._handle)
            self._handle = ctypes.c_void_p()
