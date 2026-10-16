"""Pure ONVIF presentation helpers shared by the stores and their unit tests."""

from __future__ import annotations

from urllib.parse import urlsplit

from app.core.api.errors import ApiError

CLOCK_DRIFT_ALERT_SECONDS = 10


def parse_address(value: str) -> tuple[str, int] | None:
    """Parse `camera`, `camera:8080` or an http(s) URL into host and port."""
    text = value.strip()
    if not text:
        return None
    try:
        parsed = urlsplit(text if "://" in text else f"http://{text}")
        if not parsed.hostname:
            return None
        return parsed.hostname, parsed.port or 80
    except ValueError:
        return None


def profile_labels(profiles: list[str] | None) -> list[str]:
    labels: list[str] = []
    for value in profiles or []:
        label = "S" if value.lower() == "streaming" else value
        if label not in labels:
            labels.append(label)
    return labels


def is_video_profile(profile: dict) -> bool:
    return profile.get("encoding") in ("H264", "H265") and bool(profile.get("rtsp"))


def profile_summary(profile: dict) -> str:
    parts = [profile.get("encoding")]
    if profile.get("width") and profile.get("height"):
        parts.append(f'{profile["width"]}x{profile["height"]}')
    if profile.get("fps"):
        parts.append(f'{profile["fps"]} fps')
    if profile.get("bitrate_kbps"):
        parts.append(f'{profile["bitrate_kbps"]} kbps')
    return " · ".join(str(part) for part in parts if part)


def profile_options(profiles: list[dict] | None, exclude: str = "") -> list[dict]:
    return [
        {"value": p["token"], "label": f'{p.get("name") or p["token"]} · {profile_summary(p)}'}
        for p in profiles or [] if is_video_profile(p) and p["token"] != exclude
    ]


def format_offset(seconds: float | None) -> str:
    if seconds is None:
        return "Unknown"
    sign = "+" if seconds > 0 else "-" if seconds < 0 else ""
    value = abs(seconds)
    if value < 1:
        return "In sync"
    if value < 60:
        return f"{sign}{round(value)} s"
    if value < 3600:
        return f"{sign}{int(value // 60)} min {round(value % 60)} s"
    if value < 86400:
        return f"{sign}{value / 3600:.1f} h"
    if value < 86400 * 365:
        return f"{sign}{round(value / 86400)} days"
    return f"{sign}{value / (86400 * 365.25):.1f} years"


def service_names(namespaces: list[str] | None) -> list[str]:
    rules = [
        ("ver20/media", "Media2"), ("ver10/media", "Media"), ("events", "Events"),
        ("ptz", "PTZ"), ("imaging", "Imaging"), ("deviceio", "I/O"),
        ("recording", "Recording"), ("replay", "Replay"), ("search", "Search"),
        ("analytics", "Analytics"),
    ]
    result: list[str] = []
    for namespace in namespaces or []:
        lower = namespace.lower()
        for needle, label in rules:
            if needle in lower and label not in result:
                result.append(label)
                break
    return result


def device_label(manufacturer: str | None, model: str | None) -> str:
    if not model:
        return manufacturer or ""
    if manufacturer and manufacturer.lower() not in model.lower():
        return f"{manufacturer} {model}"
    return model


def onvif_error_text(error: Exception) -> str:
    code = error.code if isinstance(error, ApiError) else None
    if code == "not_authorized":
        return ("Wrong username or password. Not retried automatically: many cameras lock the account "
                "after a few wrong logins.")
    if code == "unreachable":
        return "The camera did not answer (wrong address, port or camera offline)."
    if code == "not_supported":
        return "The camera does not support this ONVIF function."
    if code in ("node_offline", "node_unreachable", "node_timeout", "no_node_online"):
        return str(error) or "Media node not reachable"
    return str(error)
