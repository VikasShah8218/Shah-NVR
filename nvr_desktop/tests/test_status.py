from app.core.status import label_of, tone_of


def test_tones_match_web_client():
    assert tone_of("RECORDING") == "success"
    assert tone_of("NOT_RECORDING") == "danger"
    assert tone_of("DRAINING") == "warning"
    assert tone_of("READY") == "info"
    assert tone_of("SOMETHING_NEW") == "muted"
    assert tone_of(None) == "muted"


def test_labels():
    assert label_of("NOT_RECORDING") == "Not recording"
    assert label_of("ACTIVE") == "Active"
    assert label_of(None) == ""


def test_event_standby_is_muted_not_an_error():
    assert tone_of("EVENT_STANDBY") == "muted" and label_of("EVENT_STANDBY") == "Event standby"
    assert tone_of("SCHEDULED_OFF") == "muted" and label_of("SCHEDULED_OFF") == "Off (schedule)"
