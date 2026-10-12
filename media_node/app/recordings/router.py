"""Serves recorded video. The central manager's HLS playlist points straight at these URLs:

  /api/v1/media/{segment_id}/init.mp4      -> ftyp+moov of the chunk (EXT-X-MAP)
  /api/v1/media/{segment_id}/part/{n}.m4s  -> n-th keyframe-aligned part (byte slice of the file,
                                              timestamps rebased to the absolute timeline)
  /api/v1/media/{segment_id}/file.mp4      -> whole chunk (download / export)
"""

import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse

from app.recordings.models import LocalSegment
from app.recordings.schemas import LocalSegmentOut
from app.recordings.services import file_exists, read_slice
from app.recordings.utils import rebase_timestamps
from settings.settings import settings

router = APIRouter(prefix="/api/v1", tags=["Recorded media"])

CACHE_HEADERS = {"Cache-Control": "public, max-age=86400, immutable"}


async def _segment(segment_id: UUID) -> LocalSegment:
    seg = await LocalSegment.get_or_none(id=segment_id)
    if seg is None or not file_exists(seg.rel_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found on this node")
    return seg


@router.get("/media/{segment_id}/init.mp4")
async def media_init(segment_id: UUID):
    seg = await _segment(segment_id)
    data = await asyncio.to_thread(read_slice, seg.rel_path, 0, seg.init_size)
    return Response(data, media_type="video/mp4", headers=CACHE_HEADERS)


@router.get("/media/{segment_id}/part/{index}.m4s")
async def media_part(segment_id: UUID, index: int):
    seg = await _segment(segment_id)
    if not 0 <= index < len(seg.parts):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Part not found")
    part = seg.parts[index]
    data = bytearray(await asyncio.to_thread(read_slice, seg.rel_path, part["o"], part["s"]))
    if seg.tracks:
        rebase_timestamps(data, seg.tracks, seg.start_time)
    return Response(bytes(data), media_type="video/mp4", headers=CACHE_HEADERS)


@router.get("/media/{segment_id}/file.mp4")
async def media_file(segment_id: UUID):
    seg = await _segment(segment_id)
    filename = f"cam{seg.camera_id}_{seg.profile}_{seg.start_time:%Y%m%dT%H%M%SZ}.mp4"
    return FileResponse(settings.RECORDINGS_DIR / seg.rel_path, media_type="video/mp4", filename=filename)


@router.get("/segments", response_model=list[LocalSegmentOut], summary="Chunks stored on this node (debug)")
async def list_local_segments(camera_id: int | None = None, limit: int = 50):
    qs = LocalSegment.all().order_by("-start_time").limit(min(limit, 1000))
    if camera_id is not None:
        qs = qs.filter(camera_id=camera_id)
    return [
        LocalSegmentOut(**{k: getattr(s, k) for k in LocalSegmentOut.model_fields if k != "part_count"},
                        part_count=len(s.parts))
        for s in await qs
    ]
