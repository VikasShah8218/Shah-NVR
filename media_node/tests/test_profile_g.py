from datetime import datetime, timezone

import pytest

from app.onvif.profile_g import exact_replay_uri
from app.onvif.soap import Fault


def test_exact_replay_uri_replaces_vendor_range_without_credentials():
    uri = "rtsp://camera:554/recording?dev=1&start=20200101000000&stop=20200101000100&kind=0"
    start = datetime(2026, 10, 19, 12, 0, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 19, 12, 5, 2, tzinfo=timezone.utc)
    result = exact_replay_uri(uri, start, end)
    assert "start=20261019120001" in result
    assert "stop=20261019120502" in result
    assert "dev=1" in result and "kind=0" in result


def test_exact_replay_uri_refuses_unknown_format():
    with pytest.raises(Fault, match="RTSP Range"):
        exact_replay_uri(
            "rtsp://camera/replay",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
