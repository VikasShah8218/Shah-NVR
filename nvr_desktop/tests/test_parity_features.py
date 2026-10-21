from datetime import timezone

from app.core.node_access import NodeAccessResolver, public_ready
from app.features.cameras.backfill_store import local_to_utc
from app.features.live.sources import pick_sources, streams_by_profile


NODE = {
    "id": 1,
    "api_url": "http://192.168.1.10:7100",
    "public_enabled": True,
    "public_api_url": "https://nvr.example.test:7100",
    "public_media_host": "nvr.example.test",
}


def test_node_access_is_per_client_and_auto_falls_back_to_public():
    assert public_ready(NODE)
    assert NodeAccessResolver(lambda _url: True).resolve(NODE, "auto") == "lan"
    resolver = NodeAccessResolver(lambda _url: False)
    assert resolver.resolve(NODE, "auto") == "public"
    assert resolver.api_url(NODE, "auto") == "https://nvr.example.test:7100"
    assert resolver.resolve(NODE, "lan") == "lan"


def test_incomplete_public_configuration_safely_uses_lan():
    node = {**NODE, "public_media_host": None}
    assert not public_ready(node)
    assert NodeAccessResolver(lambda _url: False).resolve(node, "public") == "lan"


def test_live_source_index_preserves_audio_capability():
    live = {"streams": [{
        "profile": "main", "rtsp": "rtsp://node/main", "hls": "http://node/main.m3u8",
        "audio_state": "available", "audio_codec": "AAC", "audio_sample_rate": 48000,
    }]}
    indexed = streams_by_profile(live)
    selected = pick_sources(indexed, "main", "auto")
    assert selected["audio_state"] == "available"
    assert selected["audio_codec"] == "AAC"
    assert selected["source"] == "rtsp://node/main"


def test_backfill_local_time_is_transmitted_as_utc():
    parsed = local_to_utc("2026-10-20 18:30")
    assert parsed.endswith("+00:00")
    assert timezone.utc.utcoffset(None).total_seconds() == 0
