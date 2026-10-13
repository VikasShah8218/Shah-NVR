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
