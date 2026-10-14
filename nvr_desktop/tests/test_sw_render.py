"""CPU mode end to end at the libmpv level: mpv draws a test pattern straight into our buffer."""

import ctypes
import threading
import time

import pytest

from settings.settings import settings

if not (settings.MPV_DLL_DIR / "libmpv-2.dll").exists():
    pytest.skip("libmpv-2.dll not installed (see README)", allow_module_level=True)

from app.video.loader import prepare_libmpv  # noqa: E402

prepare_libmpv(settings.MPV_DLL_DIR)

import mpv  # noqa: E402

from app.video.profiles import BASE_OPTIONS, CPU_RENDER_OPTIONS  # noqa: E402
from app.video.render_context import UPDATE_FRAME, SwRenderContext  # noqa: E402


def test_sw_render_draws_scaled_frames():
    player = mpv.MPV(**BASE_OPTIONS, **CPU_RENDER_OPTIONS)  # the app's own options (no Lua scripts)
    ctx = SwRenderContext(player)
    wake = threading.Event()
    ctx.set_update_callback(wake.set)
    try:
        player.play("av://lavfi:testsrc=size=1280x720:rate=25")
        width, height, stride = 320, 180, 320 * 4
        raw = (ctypes.c_ubyte * (stride * height + 64))()
        pointer = (ctypes.addressof(raw) + 63) // 64 * 64
        frames, spent = 0, 0.0
        deadline = time.time() + 5
        while frames < 10 and time.time() < deadline:
            if wake.wait(1):
                wake.clear()
                if ctx.update() & UPDATE_FRAME:
                    start = time.perf_counter()
                    ctx.render(pointer, width, height, stride)
                    spent += time.perf_counter() - start
                    frames += 1
        assert frames == 10
        pixels = bytes((ctypes.c_ubyte * (stride * height)).from_address(pointer))
        coloured = sum(1 for i in range(0, len(pixels), 4 * 37) if any(pixels[i:i + 3]))
        assert coloured > len(pixels) // (4 * 37) * 0.8      # the test pattern, not a black buffer
        assert spent / frames < 0.02                        # never blocks for the frame's display time
    finally:
        ctx.free()
        player.terminate()
