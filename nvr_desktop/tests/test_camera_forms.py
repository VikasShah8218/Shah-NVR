from app.features.cameras.forms import create_body, stream_diff, update_body, validate


def form(**overrides):
    f = {
        "name": "Gate", "description": "", "username": "admin", "password": "", "retention_days": "7",
        "enabled": True,
        "streams": [
            {"profile": "main", "source_url": "rtsp://10.0.0.5/main", "record": True, "rtsp_transport": "tcp", "existing": False},
            {"profile": "sub", "source_url": "", "record": False, "rtsp_transport": "tcp", "existing": False},
        ],
    }
    f.update(overrides)
    return f


def test_valid_form_ignores_empty_new_streams():
    assert validate(form()) == []
    body = create_body(form())
    assert [s["profile"] for s in body["streams"]] == ["main"]
    assert body["description"] is None and body["password"] is None and body["retention_days"] == 7


def test_validation_messages():
    errors = validate(form(name=" ", retention_days="0", streams=[
        {"profile": "Main", "source_url": "http:/x", "record": True, "rtsp_transport": "tcp", "existing": False},
        {"profile": "Main", "source_url": "file://x", "record": True, "rtsp_transport": "tcp", "existing": False},
    ]))
    assert "Name is required." in errors
    assert "Stream profiles must be unique." in errors
    assert any("lowercase" in e for e in errors)
    assert any("must start with rtsp://" in e for e in errors)
    assert any("Retention" in e for e in errors)
    assert validate(form(streams=[])) == ["Add at least one stream URL."]


def test_update_body_keeps_password_when_empty():
    assert "password" not in update_body(form())
    assert update_body(form(password="new"))["password"] == "new"


def test_stream_diff():
    original = [
        {"profile": "main", "source_url": "rtsp://10.0.0.5/main", "record": True, "rtsp_transport": "tcp"},
        {"profile": "sub", "source_url": "rtsp://10.0.0.5/sub", "record": False, "rtsp_transport": "tcp"},
        {"profile": "old", "source_url": "rtsp://10.0.0.5/old", "record": False, "rtsp_transport": "tcp"},
    ]
    edited = form(streams=[
        {"profile": "main", "source_url": "rtsp://10.0.0.5/main", "record": True, "rtsp_transport": "tcp", "existing": True},
        {"profile": "sub", "source_url": "rtsp://10.0.0.5/sub2", "record": False, "rtsp_transport": "udp", "existing": True},
        {"profile": "third", "source_url": "rtsp://10.0.0.5/3", "record": False, "rtsp_transport": "tcp", "existing": False},
    ])
    diff = stream_diff(original, edited)
    assert [s["profile"] for s in diff["add"]] == ["third"]
    assert diff["update"] == [{"profile": "sub", "body": {"source_url": "rtsp://10.0.0.5/sub2", "record": False, "rtsp_transport": "udp"}}]
    assert diff["remove"] == ["old"]


def test_keep_until_full_sends_null_and_skips_days_check():
    f = form(retention_days="", keep_until_full=True)
    assert validate(f) == []
    assert create_body(f)["retention_days"] is None
    assert update_body(f)["retention_days"] is None
    assert create_body(form(retention_days="30"))["retention_days"] == 30
    assert any("Retention" in e for e in validate(form(retention_days="", keep_until_full=False)))
