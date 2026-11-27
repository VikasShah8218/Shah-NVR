"""Camera events helpers (port of nvr_client/src/lib/cameraEvents.ts): same cases as nvr_client/tests/cameraEvents.test.ts."""

from app.features.cameras import camera_events as ce

ALL = list(ce.KINDS)


def ago(_iso):
    return "3 minutes ago"


def test_status_line_off():
    assert ce.status_line(False, ALL, None, ago) == {"tone": "muted",
                                                     "text": "Off. Press Detect to see what the camera offers."}
    line = ce.status_line(False, ALL, {"offered": ["motion", "digital_input"]}, ago)
    assert line["text"] == "Off. The camera offers: Motion, Digital inputs."
    assert ce.status_line(False, ALL, {"offered": []}, ago)["text"] == "Off. The camera offers: none of these events."


def test_status_line_receiving_and_not_offered():
    ok = ce.status_line(True, ALL, {"state": "ok", "offered": ALL, "last_event_at": "2026-11-24T10:00:00Z"}, ago)
    assert ok == {"tone": "success", "text": "Receiving events (last 3 minutes ago)."}
    none_yet = ce.status_line(True, ["motion", "tamper"], {"state": "ok", "offered": ["motion"]}, ago)
    assert none_yet == {"tone": "warning", "text": "Receiving events; none yet. Tamper not offered by the camera."}


def test_status_line_problems():
    tone = lambda s, **kw: ce.status_line(True, ALL, {"state": s, **kw}, ago)  # noqa: E731
    assert tone("auth_failed")["tone"] == "danger" and tone("auth_failed")["text"].startswith("Login failed")
    assert tone("no_topics")["tone"] == "warning"
    assert tone("unsupported")["text"] == "This camera has no ONVIF event service."
    assert tone("unreachable", detail="timeout")["text"] == "Camera not answering (timeout). Retrying."
    assert tone("error")["text"] == "Error: unknown. Retrying."
    assert tone(None)["text"].startswith("Starting:")


def test_form_body_and_save_rules():
    cam = {"id": 4, "onvif_events_enabled": False, "onvif_event_kinds": None, "onvif_events_store_other": False}
    form = ce.form_from_camera(cam)
    assert form == {"enabled": False, "kinds": ALL, "storeOther": False}  # null kinds = all
    assert not ce.can_save(form, cam)  # nothing changed
    form["enabled"] = True
    assert ce.can_save(form, cam)
    assert ce.body_from_form(form) == {"onvif_events_enabled": True, "onvif_event_kinds": None,
                                       "onvif_events_store_other": False}
    form["kinds"] = ce.with_kind(ce.with_kind(form["kinds"], "motion", False), "motion", True)
    assert form["kinds"] == ALL  # order kept
    form["kinds"] = ce.with_kind(form["kinds"], "tamper", False)
    assert ce.body_from_form(form)["onvif_event_kinds"] == ["motion", "digital_input"]
    form["kinds"] = []
    assert not ce.can_save(form, cam)  # on with nothing chosen
    form["storeOther"] = True
    assert ce.can_save(form, cam)


def test_form_key_changes_on_save():
    cam = {"id": 4, "onvif_events_enabled": True, "onvif_event_kinds": ["motion"], "onvif_events_store_other": False}
    assert ce.form_key(cam) == (4, True, ("motion",), False)
    assert ce.form_key({**cam, "onvif_event_kinds": None}) != ce.form_key(cam)


def test_apply_body():
    assert ce.apply_body(True, ALL, group_id=7, include_subgroups=False) == {
        "enabled": True, "kinds": None, "group_id": 7, "include_subgroups": False}
    assert ce.apply_body(False, ["tamper"], camera_ids=[1, 2]) == {
        "enabled": False, "kinds": ["tamper"], "camera_ids": [1, 2], "include_subgroups": False}


# ---------------------------------------------------------------- analytics (docs/ONVIF_ANALYTICS_EVENTS_PLAN.md §8)


def test_analytics_kinds_are_opt_in():
    assert ce.saved_kinds({"onvif_event_kinds": None}) == ["motion", "tamper", "digital_input"]
    assert ce.saved_kinds({"onvif_event_kinds": ["line_crossing", "motion", "bogus"]}) == ["motion", "line_crossing"]
    assert ce.kinds_body(["motion", "tamper", "digital_input"]) is None
    assert ce.kinds_body(["motion", "tamper", "digital_input", "face"]) == ["motion", "tamper", "digital_input", "face"]
    assert ce.with_kind(["audio_alarm", "motion"], "intrusion", True) == ["motion", "intrusion", "audio_alarm"]
    form = {"enabled": True, "kinds": ["line_crossing"], "storeOther": False}
    assert ce.body_from_form(form)["onvif_event_kinds"] == ["line_crossing"]
    assert ce.apply_body(True, ["motion", "counting"], [3])["kinds"] == ["motion", "counting"]
    assert ce.kind_title("audio_alarm") == "Audio alarm"


def test_status_line_busy():
    line = ce.status_line(True, ["line_crossing"], {"state": "ok", "offered": ["line_crossing"],
                                                     "detail": "busy: 4 analytics event(s) not stored (over 30 a minute)"},
                          lambda _s: "now")
    assert line["tone"] == "warning" and "busy: 4" in line["text"]
