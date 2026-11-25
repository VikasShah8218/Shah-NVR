"""Event helpers (ports of nvr_client markers.ts / lib/eventSettings.ts): same cases as nvr_client/tests/markers.test.ts."""

from datetime import datetime, timezone

from app.features.events import event_settings as es
from app.features.events.store import bookmark_body, duration_text, event_row
from app.features.playback import markers as m

T0 = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc).timestamp() * 1000


def ev(**kw):
    return {"id": 1, "camera_id": 3, "camera_name": "Gate", "type": "manual", "source": "user:admin",
            "start_time": "2026-11-18T10:00:00+00:00", "end_time": "2026-11-18T10:00:00+00:00", "label": None,
            "pre_seconds": 10, "post_seconds": 30, **kw}


def test_moment_is_a_pin_and_plays_from_pre_seconds():
    mk = m.event_marker(ev(), T0 + 60_000)
    assert mk["t"] == T0 and mk["end_t"] is None and mk["kind"] == "event"
    assert mk["seek_t"] == T0 - 10_000 and mk["label"] == "Marked" and mk["color"] == "#3b82f6"


def test_range_and_open_event_runs_to_now():
    closed = m.event_marker(ev(type="video_loss", end_time="2026-11-18T10:02:00+00:00"), T0 + 600_000)
    assert closed["end_t"] == T0 + 120_000 and closed["label"] == "Video loss" and closed["color"] == "#ef4444"
    open_ = m.event_marker(ev(type="api", label="Door 4", end_time=None), T0 + 90_000)
    assert open_["end_t"] == T0 + 90_000 and open_["label"] == "External: Door 4 (ongoing)"
    placed = m.place_markers([open_], T0 - 3_600_000, T0 + 3_600_000)
    assert placed[0]["width"] is not None and abs(placed[0]["x"] - 0.5) < 1e-9


def test_unknown_type_is_grey_with_a_readable_label():
    assert m.event_color("onvif.tns1:VideoSource") == m.UNKNOWN_COLOR
    assert m.event_type_label("line_crossing") == "Line crossing"
    assert m.event_type_label("tns1:RuleEngine.Cell") == "Tns1 RuleEngine Cell"


def test_rows_duration_and_bookmark_body():
    assert duration_text(ev()) == "" and duration_text(ev(end_time=None)) == "ongoing"
    assert duration_text(ev(end_time="2026-11-18T10:00:12+00:00")) == "12 s"
    assert duration_text(ev(end_time="2026-11-18T10:03:05+00:00")) == "3 min 5 s"
    assert duration_text(ev(end_time="2026-11-18T11:30:00+00:00")) == "1.5 h"
    row = event_row(ev(label="Fight"), T0)
    assert row["title"] == "Marked: Fight" and row["seekMs"] == T0 - 10_000 and not row["ongoing"]
    body = bookmark_body(ev(label="Fight"))
    assert body == {"camera_id": 3, "start_time": "2026-11-18T10:00:00+00:00", "end_time": None,
                    "note": "Marked: Fight", "label": "event", "color": "#3b82f6"}
    assert bookmark_body(ev(type="video_loss", end_time="2026-11-18T10:02:00+00:00"))["end_time"].endswith("10:02:00+00:00")


def test_event_settings():
    assert es.valid(es.EVENT_DEFAULTS) and es.valid({"pre": 0, "post": 600})
    assert not es.valid({"pre": 61, "post": 30}) and not es.valid({"pre": 1.5, "post": 30})
    assert not es.valid({"pre": "", "post": 30})
    assert es.of_camera(None) == {"pre": 10, "post": 30, "marking": True}
    assert es.of_camera({"event_pre_seconds": 5, "event_post_seconds": 60, "event_marking": False}) == \
        {"pre": 5, "post": 60, "marking": False}
    assert es.body({"pre": 5, "post": 60, "marking": False}) == \
        {"event_pre_seconds": 5, "event_post_seconds": 60, "event_marking": False}


def test_camera_event_types_have_web_colours_and_labels():
    for t, color, label in (("motion", "#f59e0b", "Motion"), ("tamper", "#f97316", "Tamper"),
                            ("digital_input", "#14b8a6", "Input"), ("onvif", "#94a3b8", "Camera event")):
        mk = m.event_marker(ev(type=t), T0)
        assert (mk["color"], m.event_type_label(t)) == (color, label)
