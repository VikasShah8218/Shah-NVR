from app.node.audio import normalize_audio_codec, observed_audio


def test_runtime_g711_law_and_properties_are_detected():
    path = {
        "ready": True,
        "tracks2": [
            {"codec": "H264", "codecProps": {"width": 1920}},
            {"codec": "G711", "codecProps": {"muLaw": True, "sampleRate": 8000, "channelCount": 1}},
        ],
    }
    assert observed_audio(path) == {
        "observed": True,
        "codec": "g711u",
        "codec_raw": "G711",
        "sample_rate": 8000,
        "channels": 1,
    }


def test_ready_video_only_and_offline_are_different():
    assert observed_audio({"ready": True, "tracks2": [{"codec": "H265", "codecProps": {}}]}) == {
        "observed": False
    }
    assert observed_audio({"ready": False, "tracks2": []}) is None


def test_legacy_codec_names_are_normalized():
    assert normalize_audio_codec("MPEG4Audio") == "aac"
    assert normalize_audio_codec("Opus") == "opus"
    assert observed_audio({"ready": True, "tracks": ["H264", "G711"]})["codec"] == "g711"


def test_unknown_audio_track_is_reported_as_unsupported_not_absent():
    result = observed_audio({
        "ready": True,
        "tracks2": [{"codec": "VendorAudio", "codecProps": {"sampleRate": 16000, "channelCount": 1}}],
    })
    assert result["observed"] is True and result["codec"] == "unsupported"
