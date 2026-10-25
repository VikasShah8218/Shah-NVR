import pytest

from app.video import render_mode
from app.video.profiles import options_for


@pytest.mark.parametrize("renderer", [
    "llvmpipe (LLVM 15.0.7, 256 bits)", "GDI Generic", "Microsoft Basic Render Driver", "SwiftShader Device", "", None,
])
def test_software_renderers_are_detected(renderer):
    assert render_mode.is_software_gl(renderer)


@pytest.mark.parametrize("renderer", [
    "NVIDIA GeForce RTX 3050/PCIe/SSE2", "AMD Radeon(TM) Graphics", "Intel(R) UHD Graphics 770",
])
def test_hardware_renderers_are_detected(renderer):
    assert not render_mode.is_software_gl(renderer)


def test_resolve():
    assert render_mode.resolve("auto", "NVIDIA GeForce RTX 3050/PCIe/SSE2") == "gpu"
    assert render_mode.resolve("auto", "llvmpipe (LLVM 15.0.7)") == "cpu"
    assert render_mode.resolve("auto", None) == "cpu"            # no OpenGL at all
    assert render_mode.resolve("cpu", "NVIDIA GeForce RTX 3050") == "cpu"
    assert render_mode.resolve("gpu", "llvmpipe") == "gpu"       # the user's explicit choice wins


def test_options_per_render_mode():
    cpu = options_for("live", "cpu")
    assert cpu["sws_scaler"] == "fast-bilinear" and cpu["sws_allow_zimg"] == "no"
    assert "scale" not in cpu
    gpu = options_for("live", "gpu")
    assert gpu["scale"] == "bilinear" and "sws_scaler" not in gpu
    assert options_for("playback", "cpu")["vd_lavc_threads"] == "2"
    assert options_for("live", "cpu")["vd_lavc_threads"] == "1"


def test_live_hls_uses_stability_buffer_without_changing_rtsp_policy():
    rtsp = options_for("live", "gpu", "rtsp://node:8554/cam-1/sub")
    hls = options_for("live", "gpu", "http://node:8888/cam-1/sub/index.m3u8?token=x")
    assert rtsp["cache"] == "no" and rtsp["untimed"] == "yes"
    assert hls["cache"] == "yes" and hls["cache_pause_initial"] == "yes"
    assert hls["cache_secs"] == 5 and hls["cache_pause_wait"] == 5
    assert hls["untimed"] == "no"
    safer = options_for("live", "gpu", "http://node/live.m3u8", live_buffer_seconds=8)
    assert safer["cache_secs"] == 8 and safer["demuxer_readahead_secs"] == 8


def test_active_mode_validation():
    previous = render_mode.active()
    try:
        render_mode.set_active("cpu")
        assert render_mode.active() == "cpu"
        with pytest.raises(ValueError):
            render_mode.set_active("vulkan")
    finally:
        render_mode.set_active(previous)


def test_gpu_preference_parse_and_update():
    from app.video import gpu_preference as gp

    assert gp.parse(None) == "default"
    assert gp.parse("GpuPreference=2;") == "high"
    assert gp.parse("SwapEffectUpgradeEnable=1;GpuPreference=1;") == "power"
    assert gp.parse("AppStatus=0;") == "default"
    # other entries Windows keeps in the same value survive
    assert gp.update("SwapEffectUpgradeEnable=1;", "high") == "SwapEffectUpgradeEnable=1;GpuPreference=2;"
    assert gp.update("SwapEffectUpgradeEnable=1;GpuPreference=2;", "power") == "SwapEffectUpgradeEnable=1;GpuPreference=1;"
    assert gp.update("GpuPreference=2;", "default") == ""


def test_gpu_preference_registry_round_trip():
    import pytest
    from app.video import gpu_preference as gp

    if not gp.supported():
        pytest.skip("Windows only")
    exe = r"C:\ShahNVR-test\does-not-exist.exe"  # a value of its own, removed again
    try:
        gp.write("high", exe)
        assert gp.read(exe) == "high"
        gp.write("default", exe)
        assert gp.read(exe) == "default"
    finally:
        gp.write("default", exe)
