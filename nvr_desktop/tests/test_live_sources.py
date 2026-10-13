from app.features.live.sources import pick_sources, streams_by_profile

LIVE = {"streams": [
    {"profile": "main", "rtsp": "rtsp://n:8554/cam-1/main", "hls": "http://n:8888/cam-1/main/index.m3u8"},
    {"profile": "sub", "rtsp": "rtsp://n:8554/cam-1/sub", "hls": "http://n:8888/cam-1/sub/index.m3u8"},
]}


def test_auto_plays_rtsp_with_hls_fallback():
    s = pick_sources(streams_by_profile(LIVE), "sub", "auto")
    assert s["source"] == "rtsp://n:8554/cam-1/sub"
    assert s["fallback"] == "http://n:8888/cam-1/sub/index.m3u8"
    assert s["protocol"] == "RTSP"


def test_forced_protocols():
    streams = streams_by_profile(LIVE)
    assert pick_sources(streams, "main", "rtsp")["fallback"] == ""
    hls = pick_sources(streams, "main", "hls")
    assert hls["source"].endswith("index.m3u8") and hls["protocol"] == "LL-HLS"
    assert hls["rtsp"] == "rtsp://n:8554/cam-1/main"  # still offered for "Copy RTSP URL"


def test_unknown_profile_falls_back_to_first_stream():
    assert pick_sources(streams_by_profile(LIVE), "nope", "rtsp")["source"] == "rtsp://n:8554/cam-1/main"


def test_no_urls_yet_reports_error():
    s = pick_sources(None, "main", "auto", "Camera is disabled")
    assert s["source"] == "" and s["error"] == "Camera is disabled"
