from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.nodes.models import NodeState
from app.playback.utils import build_audio_playlist, build_vod_playlist


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


def test_audio_playlist_uses_node_aac_sidecar_and_clips_range():
    start = datetime(2026, 10, 17, tzinfo=timezone.utc)
    segment = SimpleNamespace(
        id="abc", node_id=1, codec="h264+g711u", audio_codec=None,
        start_time=start, end_time=start + timedelta(seconds=60),
    )
    node = SimpleNamespace(api_url="http://node:7100", state=NodeState.ACTIVE)
    playlist = build_audio_playlist(
        [segment], {1: node}, start + timedelta(seconds=10), start + timedelta(seconds=20),
    )
    assert "#EXT-X-PROGRAM-DATE-TIME:2026-10-17T00:00:10.000Z" in playlist
    assert "audio.aac?start_ms=10000&duration_ms=10000" in playlist
    assert "#EXTINF:10.000" in playlist


def test_audio_playlist_skips_video_only_segments():
    start = datetime(2026, 10, 17, tzinfo=timezone.utc)
    segment = SimpleNamespace(
        id="abc", node_id=1, codec="h264", audio_codec=None,
        start_time=start, end_time=start + timedelta(seconds=60),
    )
    node = SimpleNamespace(api_url="http://node", state=NodeState.ACTIVE)
    assert build_audio_playlist([segment], {1: node}, start, start + timedelta(seconds=60)) is None


def test_playback_playlist_uses_browser_facing_node_url():
    start = datetime(2026, 10, 17, tzinfo=timezone.utc)
    segment = SimpleNamespace(
        id="abc", node_id=1, codec="h264", config_signature=None,
        start_time=start, end_time=start + timedelta(seconds=10), parts=[10000],
    )
    node = SimpleNamespace(
        api_url="http://192.168.1.115:7100", state=NodeState.ACTIVE,
        api_url_for=lambda access: "https://nvr.example.com:17100" if access == "public" else "http://192.168.1.115:7100",
    )
    playlist = build_vod_playlist([segment], {1: node}, start, start + timedelta(seconds=10), "public")
    assert "https://nvr.example.com:17100/api/v1/media/abc" in playlist
    assert "192.168.1.115" not in playlist
