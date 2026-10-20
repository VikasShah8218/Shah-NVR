from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from app.cameras.models import Camera
from app.nodes.models import MediaNode
from app.playback.utils import build_audio_playlist, build_vod_playlist
from app.recordings.router import resolve_range
from app.recordings.utils import find_segments

router = APIRouter(prefix="/api/v1/playback", tags=["Playback"])

HLS_MEDIA_TYPE = "application/vnd.apple.mpegurl"


@router.get(
    "/{camera_id}/index.m3u8",
    response_class=PlainTextResponse,
    summary="HLS VOD playlist for a time range (open this URL in VLC)",
)
async def vod_playlist(
    camera_id: int,
    profile: str = "main",
    start: datetime | None = Query(default=None, examples=["2026-10-11T10:00:00Z"]),
    end: datetime | None = Query(default=None, examples=["2026-10-11T11:00:00Z"]),
    minutes: int | None = Query(default=None, ge=1, description="Shortcut: the last N minutes"),
):
    if not await Camera.exists(id=camera_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    start, end = resolve_range(start, end, minutes)

    segments = await find_segments(camera_id, profile, start, end)
    nodes = {n.id: n for n in await MediaNode.filter(id__in={s.node_id for s in segments})}
    playlist = build_vod_playlist(segments, nodes, start, end)
    if playlist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No playable recordings in this range")
    return PlainTextResponse(playlist, media_type=HLS_MEDIA_TYPE, headers={"Cache-Control": "no-cache"})


@router.get(
    "/{camera_id}/audio.m3u8",
    response_class=PlainTextResponse,
    summary="Browser-compatible AAC audio playlist for a recorded time range",
)
async def audio_playlist(
    camera_id: int,
    profile: str = "main",
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    minutes: int | None = Query(default=None, ge=1),
):
    if not await Camera.exists(id=camera_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    start, end = resolve_range(start, end, minutes)
    segments = await find_segments(camera_id, profile, start, end)
    nodes = {n.id: n for n in await MediaNode.filter(id__in={s.node_id for s in segments})}
    playlist = build_audio_playlist(segments, nodes, start, end)
    if playlist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No audio recordings in this range")
    return PlainTextResponse(playlist, media_type=HLS_MEDIA_TYPE, headers={"Cache-Control": "no-cache"})
