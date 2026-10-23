from app.mediamtx.utils import render_config
from settings.settings import settings


def test_hls_stability_window_is_explicit_in_generated_config():
    config = render_config()
    assert f"hlsSegmentCount: {settings.HLS_SEGMENT_COUNT}" in config
    assert f"hlsSegmentDuration: {round(settings.HLS_SEGMENT_SECONDS * 1000)}ms" in config
    assert f"hlsPartDuration: {round(settings.HLS_PART_SECONDS * 1000)}ms" in config
    assert "hlsAlwaysRemux: false" in config
