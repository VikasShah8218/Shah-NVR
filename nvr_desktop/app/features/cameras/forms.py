"""Camera form validation and stream diff. Port of nvr_client/src/features/cameras/CameraFormSheet.tsx.

The form arrives from QML as a dict:
  {name, description, username, password, retention_days, keep_until_full, enabled,
   streams: [{profile, source_url, record, rtsp_transport, existing}]}
"""

from __future__ import annotations

import re

PROFILE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
URL_RE = re.compile(r"^(rtsps?|rtmp|srt|https?)://", re.IGNORECASE)

BRAND_EXAMPLES = [
    {"brand": "Axis", "url": "rtsp://IP:554/axis-media/media.amp?videocodec=h264&resolution=1920x1080"},
    {"brand": "Hikvision", "url": "rtsp://IP:554/Streaming/Channels/101  (sub: 102)"},
    {"brand": "Dahua", "url": "rtsp://IP:554/cam/realmonitor?channel=1&subtype=0  (sub: subtype=1)"},
]


def used_streams(form: dict) -> list[dict]:
    """Streams that will be saved: new ones need a URL; existing ones are always kept."""
    return [s for s in form.get("streams", []) if (s.get("source_url") or "").strip() or s.get("existing")]


def validate(form: dict) -> list[str]:
    errors: list[str] = []
    used = used_streams(form)
    if not (form.get("name") or "").strip():
        errors.append("Name is required.")
    if not used:
        errors.append("Add at least one stream URL.")
    profiles = [s.get("profile", "") for s in used]
    if len(set(profiles)) != len(profiles):
        errors.append("Stream profiles must be unique.")
    for s in used:
        profile = s.get("profile", "")
        if not PROFILE_RE.match(profile):
            errors.append(f'Profile "{profile}": use lowercase letters, digits, - or _.')
        if not URL_RE.match((s.get("source_url") or "").strip()):
            errors.append(f'Profile "{profile}": URL must start with rtsp://')
    if not form.get("keep_until_full"):
        try:
            retention = int(form.get("retention_days"))
            if retention < 1:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("Retention must be a whole number of days (1 or more).")
    return errors


def _stream_body(s: dict) -> dict:
    return {
        "profile": s["profile"],
        "source_url": s["source_url"].strip(),
        "record": bool(s.get("record")),
        "rtsp_transport": s.get("rtsp_transport") or "tcp",
    }


def retention_value(form: dict) -> int | None:
    """Days to keep, or None = keep until storage is full (age never deletes)."""
    return None if form.get("keep_until_full") else int(form["retention_days"])


def create_body(form: dict) -> dict:
    return {
        "name": form["name"].strip(),
        "description": (form.get("description") or "").strip() or None,
        "username": (form.get("username") or "").strip() or None,
        "password": form.get("password") or None,
        "retention_days": retention_value(form),
        "enabled": bool(form.get("enabled", True)),
        "streams": [_stream_body(s) for s in used_streams(form)],
    }


def update_body(form: dict) -> dict:
    body = {
        "name": form["name"].strip(),
        "description": (form.get("description") or "").strip() or None,
        "username": (form.get("username") or "").strip() or None,
        "retention_days": retention_value(form),
        "enabled": bool(form.get("enabled", True)),
    }
    if form.get("password"):  # empty = keep the current password
        body["password"] = form["password"]
    return body


def stream_diff(original_streams: list[dict], form: dict) -> dict:
    """What to add / update / remove for an existing camera (port of useSyncStreams)."""
    used = used_streams(form)
    original = {s["profile"]: s for s in original_streams}
    keep = {s["profile"] for s in used if s.get("existing")}
    update = []
    for s in used:
        if not s.get("existing"):
            continue
        o = original.get(s["profile"])
        body = _stream_body(s)
        if o and (o["source_url"] != body["source_url"] or o["record"] != body["record"]
                  or o["rtsp_transport"] != body["rtsp_transport"]):
            update.append({"profile": s["profile"], "body": {k: body[k] for k in ("source_url", "record", "rtsp_transport")}})
    return {
        "add": [_stream_body(s) for s in used if not s.get("existing")],
        "update": update,
        "remove": [p for p in original if p not in keep],
    }
