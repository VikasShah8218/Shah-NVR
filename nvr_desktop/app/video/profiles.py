"""mpv option sets, in one place.

LIVE RTSP - camera streams at minimum delay, with no cache.
LIVE HLS  - camera streams with a five-second safety buffer for smoothness.
PLAYBACK - recorded HLS VOD from the central manager: normal buffering, exact seeking, and
           `rebase-start-time=no` so `time-pos` is the absolute media timestamp.

Why the playback wall clock works: the media node rewrites every recorded part's timestamps to
"seconds since 2020-01-01 UTC" (media_node/app/recordings/utils.py::rebase_timestamps). With
`rebase-start-time=no`, mpv reports exactly that value, so wall time = TIMELINE_EPOCH + time-pos.
"""

from datetime import datetime, timezone

TIMELINE_EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)

# Options applied when each player is created (shared by all modes).
BASE_OPTIONS = {
    "vo": "libmpv",
    "keep_open": "yes",
    "idle": "yes",
    "osc": False,
    "input_default_bindings": False,
    "input_vo_keyboard": False,
    "ytdl": False,
    "audio": "auto",  # tracks are available, while MpvPlayer remains muted by default
    "mute": "yes",
    "volume": 80,
    "background": "color",
    "background_color": "#1f232b",  # letterbox bars = Theme.video (same as the web client)
    "terminal": False,
    "msg_level": "all=warn",
    # No Lua scripts: an embedded video surface needs none of mpv's on-screen tools, and each one
    # costs a Lua VM + thread per player (x16 tiles).
    "load_scripts": False,
    "load_stats_overlay": False,
    "load_console": False,
    "load_osd_console": False,
    "load_auto_profiles": False,
    "load_select": False,
    "load_positioning": False,
    "load_commands": False,
    "load_context_menu": False,
}

# Every option that differs between the modes is listed in BOTH dicts, so switching a player
# from live to playback (or back) never leaves a stale value behind.
# LIVE spells out mpv's built-in "low-latency" profile explicitly (profiles can't be applied
# as runtime properties).
LIVE_OPTIONS = {
    "cache": "no",
    "cache_pause": "no",
    "cache_pause_initial": "no",
    "cache_pause_wait": 1,
    "cache_secs": 1,
    "demuxer_readahead_secs": 1,
    "untimed": "yes",
    "video_sync": "audio",
    "video_latency_hacks": "yes",
    "interpolation": "no",
    "vd_lavc_threads": "1",
    "stream_buffer_size": "4KiB",
    "demuxer_lavf_o": "fflags=+nobuffer",
    "demuxer_lavf_probe_info": "nostreams",
    "demuxer_lavf_analyzeduration": "0.1",
    "rtsp_transport": "tcp",
    "network_timeout": "10",
    "rebase_start_time": "yes",
    "hr_seek": "no",
}

LIVE_HLS_OPTIONS = {
    "cache": "yes",
    "cache_pause": "yes",
    "cache_pause_initial": "yes",
    "cache_pause_wait": 5,
    "cache_secs": 5,
    "demuxer_readahead_secs": 5,
    "untimed": "no",
    "video_sync": "audio",
    "video_latency_hacks": "no",
    "interpolation": "no",
    "vd_lavc_threads": "1",
    "stream_buffer_size": "128KiB",
    "demuxer_lavf_o": "",
    "demuxer_lavf_probe_info": "auto",
    "demuxer_lavf_analyzeduration": "0.1",
    "rtsp_transport": "tcp",
    "network_timeout": "10",
    "rebase_start_time": "yes",
    "hr_seek": "no",
}

PLAYBACK_OPTIONS = {
    "cache": "yes",
    "cache_pause": "yes",
    "cache_pause_initial": "no",
    "cache_pause_wait": 1,
    "cache_secs": 30,
    "demuxer_readahead_secs": 1,
    "untimed": "no",
    "video_sync": "audio",
    "video_latency_hacks": "no",
    "interpolation": "no",
    "vd_lavc_threads": "0",
    "stream_buffer_size": "128KiB",
    "demuxer_lavf_o": "",
    "demuxer_lavf_probe_info": "auto",
    "demuxer_lavf_analyzeduration": "0",
    "rtsp_transport": "tcp",
    "network_timeout": "20",
    "rebase_start_time": "no",
    "hr_seek": "yes",
}

# Render-mode options (see app/video/render_mode.py).
# GPU mode: simple bilinear scaling. mpv's defaults are tuned for one full-screen movie; for a wall of
# tiles they cost ~2x GPU time and ~45% more GPU memory with no visible difference at tile size.
GPU_RENDER_OPTIONS = {
    "scale": "bilinear",
    "dscale": "bilinear",
    "cscale": "bilinear",
    "dither": "no",
    "correct_downscaling": "no",
    "linear_downscaling": "no",
    "sigmoid_upscaling": "no",
}

# CPU mode: libswscale's fast bilinear path converts + scales a 1080p frame to tile size in ~1.6 ms
# (zimg, mpv's default software scaler, takes ~4 ms; plain bilinear ~5 ms).
CPU_RENDER_OPTIONS = {
    "keepaspect": "no",  # the surface renders at the picture's own aspect ratio (no letterbox bars)
    "sws_allow_zimg": "no",
    "sws_scaler": "fast-bilinear",
    "sws_fast": "yes",
}

HWDEC_CHOICES = ["auto-safe", "nvdec", "d3d11va-copy", "nvdec-copy", "no"]


def options_for(mode: str, render_mode: str = "gpu", source: str = "", live_buffer_seconds: int = 5) -> dict:
    """Return complete options for the mode, renderer and active media URL."""
    is_live_hls = mode == "live" and source.partition("?")[0].lower().endswith(".m3u8")
    options = dict(LIVE_HLS_OPTIONS if is_live_hls else LIVE_OPTIONS if mode == "live" else PLAYBACK_OPTIONS)
    if is_live_hls:
        buffer_seconds = max(2, min(10, int(live_buffer_seconds)))
        options.update(cache_pause_wait=buffer_seconds, cache_secs=buffer_seconds,
                       demuxer_readahead_secs=buffer_seconds)
    options.update(CPU_RENDER_OPTIONS if render_mode == "cpu" else GPU_RENDER_OPTIONS)
    if render_mode == "cpu" and mode == "playback":
        options["vd_lavc_threads"] = "2"  # one big view: a second decode thread keeps seeking snappy
    return options
