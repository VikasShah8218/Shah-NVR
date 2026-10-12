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

    Each chunk = one EXT-X-MAP (init) + N parts. Every part starts on a keyframe, so the
    player can seek to any part. Returns None when nothing playable is in range.
    """
    body: list[str] = []
    max_part = 1.0
    cursor = start
    prev_end: datetime | None = None
    prev_codec: str | None = None
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
        # A discontinuity is only needed at a real gap in the recording or a codec change.
        base = f"{node.api_url.rstrip('/')}/api/v1/media/{seg.id}"
        if body and (seg.codec != prev_codec or chosen[0][2] - prev_end > GAP_TOLERANCE):
            body.append("#EXT-X-DISCONTINUITY")
        prev_end, prev_codec = chosen[-1][3], seg.codec
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
        "#EXT-X-INDEPENDENT-SEGMENTS",
    ]
    return "\n".join(header + body + ["#EXT-X-ENDLIST", ""])
