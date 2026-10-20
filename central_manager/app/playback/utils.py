import math
from datetime import datetime, timedelta

from app.nodes.models import MediaNode, NodeState
from app.recordings.models import RecordingSegment

# Overlapping video (e.g. two nodes recorded during a failover) is played only once.
OVERLAP_TOLERANCE = timedelta(milliseconds=500)
GAP_TOLERANCE = timedelta(seconds=1)
UNAVAILABLE_NODE_STATES = (NodeState.UNREACHABLE, NodeState.OFFLINE)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_vod_playlist(
    segments: list[RecordingSegment], nodes: dict[int, MediaNode], start: datetime, end: datetime
) -> str | None:
    """HLS VOD playlist pointing directly at the media nodes that hold each chunk.

    Each chunk = one EXT-X-MAP (init) + N parts. Parts start on keyframes whenever the camera
    GOP lines up with the recorder's fragments; the player can seek to any part.
    Returns None when nothing playable is in range.
    """
    body: list[str] = []
    max_part = 1.0
    cursor = start
    prev_end: datetime | None = None
    prev_codec: str | None = None
    prev_config: str | None = None
    for seg in segments:
        node = nodes.get(seg.node_id)
        if node is None or node.state in UNAVAILABLE_NODE_STATES:
            continue

        chosen = []
        t = seg.start_time
        for index, dur_ms in enumerate(seg.parts):
            part_start, part_end = t, t + timedelta(milliseconds=dur_ms)
            t = part_end
            if part_end <= start or part_start >= end:
                continue
            if part_end <= cursor + OVERLAP_TOLERANCE:
                continue
            chosen.append((index, dur_ms, part_start, part_end))
        if not chosen:
            continue
        cursor = max(cursor, chosen[-1][3])

        # Nodes serve parts on one absolute timeline, so consecutive chunks join seamlessly.
        # A decoder configuration change (including resolution/SPS/PPS) needs a fresh boundary.
        base = f"{node.api_url.rstrip('/')}/api/v1/media/{seg.id}"
        config = seg.config_signature
        if body and (seg.codec != prev_codec or config != prev_config or chosen[0][2] - prev_end > GAP_TOLERANCE):
            body.append("#EXT-X-DISCONTINUITY")
        prev_end, prev_codec = chosen[-1][3], seg.codec
        prev_config = config
        body.append(f'#EXT-X-MAP:URI="{base}/init.mp4"')
        body.append(f"#EXT-X-PROGRAM-DATE-TIME:{_iso(chosen[0][2])}")
        for index, dur_ms, _, _ in chosen:
            seconds = dur_ms / 1000
            max_part = max(max_part, seconds)
            body.append(f"#EXTINF:{seconds:.3f},")
            body.append(f"{base}/part/{index}.m4s")

    if not body:
        return None
    header = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        f"#EXT-X-TARGETDURATION:{math.ceil(max_part)}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        # No EXT-X-INDEPENDENT-SEGMENTS: when a camera GOP does not line up with the recorder's
        # fragments, some parts start mid-GOP (see media_node fMP4 indexer).
    ]
    return "\n".join(header + body + ["#EXT-X-ENDLIST", ""])


_AUDIO_CODECS = {"aac", "opus", "g711", "g711a", "g711u", "g722", "lpcm", "g726"}


def _audio_codec(seg: RecordingSegment) -> str | None:
    if seg.audio_codec:
        return seg.audio_codec.lower()
    # Backward compatibility: old node indexes stored "h264+g711u" in the aggregate codec column.
    return next((c for c in (seg.codec or "").lower().split("+") if c in _AUDIO_CODECS), None)


def build_audio_playlist(
    segments: list[RecordingSegment], nodes: dict[int, MediaNode], start: datetime, end: datetime
) -> str | None:
    """Audio-only HLS. Nodes convert each selected slice to AAC; recorded video remains untouched."""
    body: list[str] = []
    max_duration = 1.0
    cursor = start
    previous_end: datetime | None = None
    for seg in segments:
        node = nodes.get(seg.node_id)
        if node is None or node.state in UNAVAILABLE_NODE_STATES or not _audio_codec(seg):
            continue
        clip_start = max(start, seg.start_time, cursor)
        clip_end = min(end, seg.end_time)
        if clip_end <= clip_start:
            continue
        if body and previous_end is not None and clip_start - previous_end > GAP_TOLERANCE:
            body.append("#EXT-X-DISCONTINUITY")
        offset_ms = max(0, round((clip_start - seg.start_time).total_seconds() * 1000))
        duration_ms = max(1, round((clip_end - clip_start).total_seconds() * 1000))
        seconds = duration_ms / 1000
        max_duration = max(max_duration, seconds)
        base = f"{node.api_url.rstrip('/')}/api/v1/media/{seg.id}/audio.aac"
        body.extend([
            f"#EXT-X-PROGRAM-DATE-TIME:{_iso(clip_start)}",
            f"#EXTINF:{seconds:.3f},",
            f"{base}?start_ms={offset_ms}&duration_ms={duration_ms}",
        ])
        previous_end = clip_end
        cursor = clip_end
    if not body:
        return None
    return "\n".join([
        "#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{math.ceil(max_duration)}",
        "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD", *body, "#EXT-X-ENDLIST", "",
    ])
