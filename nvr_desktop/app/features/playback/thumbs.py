"""Timeline hover thumbnails (port of nvr_client/src/features/playback/thumbs.ts).

Hovered time -> (chunk, offset of its 30 s slot). The node snaps to the same grid; snapping here too keeps
every hover inside one slot on the same URL, so Qt's image cache answers before the node is asked.
"""

from __future__ import annotations

from app.features.playback.timeline import to_ms

THUMB_GRID_MS = 30_000  # must match the node's THUMBNAIL_GRID_SECONDS (it snaps anyway)
THUMB_DEBOUNCE_MS = 150


def thumb_target(segments: list[dict], t_ms: float, grid_ms: int = THUMB_GRID_MS) -> dict | None:
    """{segment_id, node_id, at_ms, slot_start} for the chunk recorded at `t_ms`, or None (gap)."""
    for s in segments:
        start, end = to_ms(s["start_time"]), to_ms(s["end_time"])
        if start <= t_ms < end:
            at_ms = int((t_ms - start) // grid_ms) * grid_ms
            return {"segment_id": s["id"], "node_id": s["node_id"], "at_ms": at_ms, "slot_start": start + at_ms}
    return None


def thumbnail_url(api_url: str, segment_id: str, at_ms: int, width: int = 240) -> str:
    return f"{api_url.rstrip('/')}/api/v1/media/{segment_id}/thumb.jpg?at_ms={at_ms}&w={width}"
