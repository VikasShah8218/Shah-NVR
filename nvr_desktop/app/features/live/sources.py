"""Which URL a live video surface plays. Used by the Live View tiles and the camera preview.

Desktop protocols: "auto" = RTSP (lowest delay), falling back to LL-HLS when RTSP fails;
"rtsp" = RTSP only; "hls" = LL-HLS only. mpv cannot play WebRTC/WHEP, so there is no WebRTC option.
"""

from __future__ import annotations

EMPTY = {"source": "", "fallback": "", "protocol": "", "rtsp": "", "error": ""}


def streams_by_profile(live: dict) -> dict[str, dict]:
    """GET /cameras/{id}/live -> {profile: {"rtsp": url, "hls": url}}."""
    return {s["profile"]: {"rtsp": s["rtsp"], "hls": s["hls"]} for s in live.get("streams", [])}


def pick_sources(streams: dict[str, dict] | None, profile: str, protocol: str, error: str = "") -> dict:
    """{source, fallback, protocol, rtsp, error} for one video surface."""
    if not streams:
        return {**EMPTY, "error": error}
    urls = streams.get(profile) or next(iter(streams.values()))
    if protocol == "hls":
        return {"source": urls["hls"], "fallback": "", "protocol": "LL-HLS", "rtsp": urls["rtsp"], "error": ""}
    fallback = urls["hls"] if protocol == "auto" else ""
    return {"source": urls["rtsp"], "fallback": fallback, "protocol": "RTSP", "rtsp": urls["rtsp"], "error": ""}
