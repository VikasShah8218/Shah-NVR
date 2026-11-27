"""Camera events from ONVIF (docs/DESKTOP_ONVIF_EVENTS_PLAN.md, docs/ONVIF_ANALYTICS_EVENTS_PLAN.md §8; port of
nvr_client/src/lib/cameraEvents.ts): kinds, labels, the status line and the form draft of the Camera events tab.
Pure (unit-tested)."""

from __future__ import annotations

from typing import Callable

KINDS = ("motion", "tamper", "digital_input")  # the basic kinds: what "all kinds" (null) means
# the camera's own analytics: opt-in per kind (null never includes them)
ANALYTICS_KINDS = ("line_crossing", "intrusion", "loitering", "object_left", "person", "face", "counting",
                   "audio_alarm")
ALL_KINDS = KINDS + ANALYTICS_KINDS

LABELS = {
    "motion": {"title": "Motion", "hint": "The camera's own motion detection"},
    "tamper": {"title": "Tamper", "hint": "Lens covered, blurred or camera turned"},
    "digital_input": {"title": "Digital inputs", "hint": "Door contacts, alarm panels, buttons wired to the camera"},
    "line_crossing": {"title": "Line crossing", "hint": "An object crossed a virtual line"},
    "intrusion": {"title": "Intrusion", "hint": "An object is inside a zone"},
    "loitering": {"title": "Loitering", "hint": "An object stays in a zone too long"},
    "object_left": {"title": "Object left", "hint": "An object was left behind or removed"},
    "person": {"title": "Person", "hint": "A person is detected"},
    "face": {"title": "Face", "hint": "A face is detected"},
    "counting": {"title": "People counting", "hint": "In / out counts (can be noisy)"},
    "audio_alarm": {"title": "Audio alarm", "hint": "The camera's audio analytics (scream, glass break…)"},
}


def kinds_body(kinds) -> list[str] | None:
    """What to send: None when exactly the basic three are on (keeps "all kinds" for old cameras)."""
    picked = [k for k in ALL_KINDS if k in kinds]
    return None if picked == list(KINDS) else picked


def kind_title(kind: str) -> str:
    return LABELS.get(kind, {}).get("title", kind)


def status_line(enabled: bool, kinds: list[str] | tuple[str, ...], status: dict | None,
                ago: Callable[[str], str]) -> dict:
    """{"tone": success | warning | danger | muted, "text"} for the camera's event state (same text as the web)."""
    status = status or {}
    offered = status.get("offered")
    missing = [k for k in kinds if k not in offered] if offered is not None else []
    missing_text = f" {', '.join(kind_title(k) for k in missing)} not offered by the camera." if missing else ""
    if not enabled:
        if offered is not None:
            return {"tone": "muted", "text": "Off. The camera offers: "
                    + (", ".join(kind_title(k) for k in offered) if offered else "none of these events") + "."}
        return {"tone": "muted", "text": "Off. Press Detect to see what the camera offers."}
    state = status.get("state")
    if state == "ok" and str(status.get("detail") or "").startswith("busy"):
        return {"tone": "warning", "text": f"Receiving events, {status['detail']}. "
                                           "Narrow the camera's rules or switch noisy kinds off."}
    if state == "ok":
        last = status.get("last_event_at")
        text = f"Receiving events (last {ago(last)})." if last else "Receiving events; none yet."
        return {"tone": "warning" if missing else "success", "text": text + missing_text}
    if state == "auth_failed":
        return {"tone": "danger", "text": "Login failed: check the camera's username and password. "
                                          "Retried when they change or after 30 min."}
    if state == "no_topics":
        return {"tone": "warning", "text": "The camera offers none of the chosen events. Enable motion detection "
                                           "(or the event) in the camera's own web page, then press Detect."}
    if state == "unsupported":
        return {"tone": "danger", "text": "This camera has no ONVIF event service."}
    if state == "unreachable":
        detail = f" ({status['detail']})" if status.get("detail") else ""
        return {"tone": "danger", "text": f"Camera not answering{detail}. Retrying."}
    if state == "error":
        return {"tone": "danger", "text": f"Error: {status.get('detail') or 'unknown'}. Retrying."}
    return {"tone": "muted", "text": "Starting: the recording node subscribes within a few seconds." + missing_text}


def saved_kinds(camera: dict) -> list[str]:
    """The camera's chosen kinds; null on central = the basic three."""
    kinds = camera.get("onvif_event_kinds")
    return [k for k in ALL_KINDS if k in kinds] if kinds is not None else list(KINDS)


def form_from_camera(camera: dict) -> dict:
    return {"enabled": bool(camera.get("onvif_events_enabled")), "kinds": saved_kinds(camera),
            "storeOther": bool(camera.get("onvif_events_store_other"))}


def form_key(camera: dict) -> tuple:
    """The draft is rebuilt when this changes (the web's remount key): a save or another client's change."""
    return (camera.get("id"), bool(camera.get("onvif_events_enabled")), tuple(saved_kinds(camera)),
            bool(camera.get("onvif_events_store_other")))


def with_kind(kinds: list[str], kind: str, on: bool) -> list[str]:
    return [k for k in ALL_KINDS if (on if k == kind else k in kinds)]


def body_from_form(form: dict) -> dict:
    return {"onvif_events_enabled": bool(form["enabled"]),
            "onvif_event_kinds": kinds_body(form["kinds"]),
            "onvif_events_store_other": bool(form["storeOther"])}


def is_dirty(form: dict, camera: dict) -> bool:
    return form != form_from_camera(camera)


def can_save(form: dict, camera: dict) -> bool:
    """Something changed, and "on" has at least one kind or "store other"."""
    return is_dirty(form, camera) and not (form["enabled"] and not form["kinds"] and not form["storeOther"])


def apply_body(enabled: bool, kinds: list[str], camera_ids: list[int] | None = None, group_id: int | None = None,
               include_subgroups: bool = True) -> dict:
    """POST /api/v1/onvif/events/apply body (a group, or selected cameras)."""
    body: dict = {"enabled": enabled, "kinds": kinds_body(kinds)}
    if group_id:
        body.update(group_id=group_id, include_subgroups=include_subgroups)
    else:
        body.update(camera_ids=list(camera_ids or []), include_subgroups=False)
    return body
