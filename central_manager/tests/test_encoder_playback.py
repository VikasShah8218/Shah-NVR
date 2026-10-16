from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.nodes.models import NodeState
from app.playback.utils import build_vod_playlist


@pytest.mark.parametrize("first,second,expected", [
    ("same", "same", 0), ("old-resolution", "new-resolution", 1),
    (None, None, 0), (None, "new-indexer", 1)])
def test_decoder_config_boundary(first, second, expected):
    start = datetime(2026, 10, 17, tzinfo=timezone.utc)
    def segment(n, signature):
        return SimpleNamespace(id=str(n), node_id=1, codec="h264", config_signature=signature,
                               start_time=start + timedelta(seconds=10 * n), parts=[5000, 5000])
    node = SimpleNamespace(api_url="http://node", state=NodeState.ACTIVE)
    playlist = build_vod_playlist([segment(0, first), segment(1, second)], {1: node}, start, start + timedelta(seconds=20))
    assert playlist.count("#EXT-X-DISCONTINUITY") == expected
    assert playlist.count("#EXT-X-MAP") == 2


def test_codec_switch_always_has_discontinuity():
    start = datetime(2026, 10, 17, tzinfo=timezone.utc)
    segments = [SimpleNamespace(id=str(i), node_id=1, codec=codec, config_signature=None,
                               start_time=start + timedelta(seconds=10*i), parts=[10000])
                for i, codec in enumerate(("h264", "h265"))]
    playlist = build_vod_playlist(segments, {1: SimpleNamespace(api_url="http://node", state=NodeState.ACTIVE)},
                                  start, start + timedelta(seconds=20))
    assert playlist.count("#EXT-X-DISCONTINUITY") == 1
