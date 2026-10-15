"""Minimal, memory-safe wrappers around libmpv's render API (mpv/render.h, render_gl.h).

* GlRenderContext - GPU mode: mpv draws into an OpenGL framebuffer (Qt Quick's FBO).
* SwRenderContext - CPU mode: mpv converts + scales each frame with libswscale straight into a memory
  buffer at the requested size (one SIMD pass, no OpenGL at all).

Why not python-mpv's MpvRenderContext? It builds the C parameter array from temporary Python objects;
ctypes copies only the raw struct bytes into the array, so the buffers those structs point to (the
"opengl" string, the init-params struct) can be freed before libmpv reads them. On Windows that shows
up as heap corruption (0xC0000374) when the context is created. Here every buffer is an attribute of
the object, so it lives exactly as long as libmpv may use it.

Threading: GL create(), render() and free() must run on the thread whose OpenGL context is current
(the Qt Quick render thread). SW calls may run on any thread, one at a time. The update callback is
invoked by libmpv from its own threads and must not call back into libmpv.
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
_PARAM_BLOCK_FOR_TARGET_TIME = 12
_PARAM_SW_SIZE = 17
_PARAM_SW_FORMAT = 18
_PARAM_SW_STRIDE = 19
_PARAM_SW_POINTER = 20

UPDATE_FRAME = 1  # mpv_render_update_flag: a new video frame must be rendered

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
_lib.mpv_render_context_update.argtypes = [ctypes.c_void_p]
_lib.mpv_render_context_update.restype = ctypes.c_uint64


def _create(player: mpv.MPV, params) -> ctypes.c_void_p:
    handle = ctypes.c_void_p()
    rc = _lib.mpv_render_context_create(ctypes.byref(handle), ctypes.cast(player.handle, ctypes.c_void_p), params)
    if rc < 0:
        raise RuntimeError(f"mpv_render_context_create failed ({rc})")
    return handle


class GlRenderContext:
    def __init__(self, player: mpv.MPV, get_proc_address: Callable[[bytes], int]):
        # All of these must stay alive while libmpv may read them.
        self._get_proc_address = _GetProcAddressFn(lambda _ctx, name: get_proc_address(name) or 0)
        self._api_type = ctypes.c_char_p(b"opengl")
        self._init_params = _OpenGLInitParams(self._get_proc_address, None, None)
        self._fbo = _OpenGLFbo(0, 0, 0, 0)
        self._flip_y = ctypes.c_int(0)
        # 0 = return immediately: rendering runs on the GUI thread, which must never wait for a frame's
        # display time (playback paces itself through the update callback instead).
        self._block = ctypes.c_int(0)
        self._update_fn = _NOOP_UPDATE

        create_params = (_Param * 3)(
            _Param(_PARAM_API_TYPE, ctypes.cast(self._api_type, ctypes.c_void_p)),
            _Param(_PARAM_OPENGL_INIT_PARAMS, ctypes.cast(ctypes.pointer(self._init_params), ctypes.c_void_p)),
            _Param(_PARAM_INVALID, None),
        )
        self._handle = _create(player, create_params)

        self._render_params = (_Param * 4)(
            _Param(_PARAM_OPENGL_FBO, ctypes.cast(ctypes.pointer(self._fbo), ctypes.c_void_p)),
            _Param(_PARAM_FLIP_Y, ctypes.cast(ctypes.pointer(self._flip_y), ctypes.c_void_p)),
            _Param(_PARAM_BLOCK_FOR_TARGET_TIME, ctypes.cast(ctypes.pointer(self._block), ctypes.c_void_p)),
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


class SwRenderContext:
    """CPU mode: mpv renders each frame into caller-provided memory, already scaled to that size.

    Pixel format "rgb0" = bytes R, G, B, padding: the same layout as QImage.Format_RGBX8888.
    """

    FORMAT = b"rgb0"

    def __init__(self, player: mpv.MPV):
        self._api_type = ctypes.c_char_p(b"sw")
        self._size = (ctypes.c_int * 2)(0, 0)
        self._format = ctypes.c_char_p(self.FORMAT)
        self._stride = ctypes.c_size_t(0)
        self._block = ctypes.c_int(0)  # never wait for the frame's display time (the worker paces itself)
        self._update_fn = _NOOP_UPDATE

        create_params = (_Param * 2)(
            _Param(_PARAM_API_TYPE, ctypes.cast(self._api_type, ctypes.c_void_p)),
            _Param(_PARAM_INVALID, None),
        )
        self._handle = _create(player, create_params)

        self._render_params = (_Param * 6)(
            _Param(_PARAM_SW_SIZE, ctypes.cast(self._size, ctypes.c_void_p)),
            _Param(_PARAM_SW_FORMAT, ctypes.cast(self._format, ctypes.c_void_p)),
            _Param(_PARAM_SW_STRIDE, ctypes.cast(ctypes.pointer(self._stride), ctypes.c_void_p)),
            _Param(_PARAM_BLOCK_FOR_TARGET_TIME, ctypes.cast(ctypes.pointer(self._block), ctypes.c_void_p)),
            _Param(_PARAM_SW_POINTER, None),  # set per call
            _Param(_PARAM_INVALID, None),
        )

    def set_update_callback(self, callback: Callable[[], None] | None) -> None:
        """`callback` runs on a libmpv thread; it must only signal (never call libmpv)."""
        self._update_fn = _UpdateFn(lambda _userdata: callback() if callback else None)
        _lib.mpv_render_context_set_update_callback(self._handle, self._update_fn, None)

    def update(self) -> int:
        """Flags for the next render (UPDATE_FRAME when there is a new frame)."""
        return int(_lib.mpv_render_context_update(self._handle))

    def render(self, pointer: int, width: int, height: int, stride: int) -> None:
        """Draw the current frame into `pointer` (width x height, `stride` bytes per row).

        The ctypes call releases the GIL, so several tiles convert in parallel on their own threads.
        """
        self._size[0], self._size[1] = width, height
        self._stride.value = stride
        self._render_params[4].data = pointer
        _lib.mpv_render_context_render(self._handle, self._render_params)

    def free(self) -> None:
        if self._handle:
            _lib.mpv_render_context_set_update_callback(self._handle, _NOOP_UPDATE, None)
            _lib.mpv_render_context_free(self._handle)
            self._handle = ctypes.c_void_p()
