"""Normalize audio tracks reported by different MediaMTX API versions."""

from __future__ import annotations


def normalize_audio_codec(value: str | None, props: dict | None = None) -> str | None:
    if not value:
        return None
    compact = value.upper().replace("-", "").replace("_", "").replace(" ", "")
    if compact == "G711":
        if props and props.get("muLaw") is True:
            return "g711u"
        if props and props.get("muLaw") is False:
            return "g711a"
        return "g711"
    return {
        "MPEG4AUDIO": "aac", "AAC": "aac", "OPUS": "opus",
        "PCMA": "g711a", "ALAW": "g711a", "PCMU": "g711u", "ULAW": "g711u",
        "G722": "g722", "LPCM": "lpcm", "PCM": "lpcm", "G726": "g726",
    }.get(compact)


def observed_audio(path: dict) -> dict | None:
    """Return an observation for a ready path; None means the path is offline and must not erase known state."""
    if not path.get("ready"):
        return None
    tracks2 = path.get("tracks2")
    if isinstance(tracks2, list):
        for track in tracks2:
            if not isinstance(track, dict):
                continue
            raw = str(track.get("codec") or "")
            props = track.get("codecProps") if isinstance(track.get("codecProps"), dict) else {}
            codec = normalize_audio_codec(raw, props)
            if codec:
                return {
                    "observed": True,
                    "codec": codec,
                    "codec_raw": raw or None,
                    "sample_rate": props.get("sampleRate"),
                    "channels": props.get("channelCount"),
                }
            if raw and (props.get("sampleRate") or props.get("channelCount")):
                return {
                    "observed": True,
                    "codec": "unsupported",
                    "codec_raw": raw,
                    "sample_rate": props.get("sampleRate"),
                    "channels": props.get("channelCount"),
                }
        return {"observed": False}

    # MediaMTX versions before tracks2 expose codec names only.
    for track in path.get("tracks") or []:
        raw = track if isinstance(track, str) else str(track.get("codec") or "")
        codec = normalize_audio_codec(raw)
        if codec:
            return {"observed": True, "codec": codec, "codec_raw": raw, "sample_rate": None, "channels": None}
    return {"observed": False}
