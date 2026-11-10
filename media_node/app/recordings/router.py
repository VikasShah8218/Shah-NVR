"""Serves recorded video. The central manager's HLS playlist points straight at these URLs:

  /api/v1/media/{segment_id}/init.mp4      -> ftyp+moov of the chunk (EXT-X-MAP)
  /api/v1/media/{segment_id}/part/{n}.m4s  -> n-th part (byte slice of the file,
                                              timestamps rebased to the absolute timeline)
  /api/v1/media/{segment_id}/file.mp4      -> whole chunk (download / export)

`?video_only=true` on init/part drops every non-video track: browsers refuse a whole stream when one
track is unplayable (see recordings/utils.py), and they get audio from the AAC playlist instead.
"""

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse

from app.recordings.models import LocalSegment
from app.recordings.schemas import LocalSegmentOut
from app.recordings.services import file_exists, read_slice
from app.recordings.utils import (
    Mp4IndexError,
    rebase_timestamps,
    video_only_init,
    video_only_part,
    video_track_ids,
)
from app.storage.services import storage
from settings.settings import settings

router = APIRouter(prefix="/api/v1", tags=["Recorded media"])
logger = logging.getLogger("node.recordings")
_audio_jobs = asyncio.Semaphore(4)

CACHE_HEADERS = {"Cache-Control": "public, max-age=86400, immutable"}


async def _segment(segment_id: UUID) -> tuple[LocalSegment, Path]:
    """The chunk and the folder of the volume that holds it."""
    seg = await LocalSegment.get_or_none(id=segment_id)
    if seg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found on this node")
    volume = storage.get(seg.volume_id)
    if volume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The storage holding this recording was removed")
    if not volume.usable:  # e.g. network share offline: answer at once instead of hanging on the path
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Storage offline: {volume.path}")
    if not await asyncio.to_thread(file_exists, volume.path, seg.rel_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found on this node")
    return seg, volume.path


@router.get("/media/{segment_id}/init.mp4")
async def media_init(segment_id: UUID, video_only: bool = False):
    seg, root = await _segment(segment_id)
    data = await asyncio.to_thread(read_slice, root, seg.rel_path, 0, seg.init_size)
    if video_only:
        video_ids = video_track_ids(data)
        if video_ids:
            data = video_only_init(data, video_ids)
    return Response(data, media_type="video/mp4", headers=CACHE_HEADERS)


@router.get("/media/{segment_id}/part/{index}.m4s")
async def media_part(segment_id: UUID, index: int, video_only: bool = False):
    seg, root = await _segment(segment_id)
    if not 0 <= index < len(seg.parts):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Part not found")
    part = seg.parts[index]
    data = bytearray(await asyncio.to_thread(read_slice, root, seg.rel_path, part["o"], part["s"]))
    if seg.tracks:
        rebase_timestamps(data, seg.tracks, seg.start_time)
    if video_only:
        init = await asyncio.to_thread(read_slice, root, seg.rel_path, 0, seg.init_size)
        video_ids = video_track_ids(init)
        if video_ids:
            try:
                data = video_only_part(bytes(data), video_ids)
            except Mp4IndexError as exc:  # not MediaMTX's layout: the original part is still correct
                logger.warning("Serving segment %s part %d with all tracks: %s", segment_id, index, exc)
    return Response(bytes(data), media_type="video/mp4", headers=CACHE_HEADERS)


@router.get("/media/{segment_id}/file.mp4")
async def media_file(segment_id: UUID):
    seg, root = await _segment(segment_id)
    filename = f"cam{seg.camera_id}_{seg.profile}_{seg.start_time:%Y%m%dT%H%M%SZ}.mp4"
    return FileResponse(root / seg.rel_path, media_type="video/mp4", filename=filename)


@router.get("/media/{segment_id}/audio.aac", summary="AAC rendition of a recording's first audio track")
async def media_audio(segment_id: UUID, start_ms: int = 0, duration_ms: int | None = None):
    """Transcode audio only; the original recording and video track are never modified or decoded."""
    seg, root = await _segment(segment_id)
    if start_ms < 0 or start_ms >= max(seg.duration_ms, 1):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "start_ms is outside the recording")
    remaining = max(seg.duration_ms - start_ms, 1)
    duration_ms = remaining if duration_ms is None else min(max(duration_ms, 1), remaining)
    command = [
        settings.FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
        "-ss", f"{start_ms / 1000:.3f}", "-i", str(root / seg.rel_path),
        "-t", f"{duration_ms / 1000:.3f}", "-map", "0:a:0", "-vn",
        "-c:a", "aac", "-b:a", "128k", "-f", "adts", "pipe:1",
    ]
    try:
        async with _audio_jobs:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=45)
    except FileNotFoundError as exc:
        logger.error("FFmpeg is unavailable at %s", settings.FFMPEG_BIN)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Recorded audio converter is not installed") from exc
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Recorded audio conversion timed out") from exc
    if process.returncode or not stdout:
        detail = stderr.decode("utf-8", "replace")[-300:]
        logger.warning("No playable audio for segment %s: %s", segment_id, detail)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This recording has no playable audio track")
    return Response(
        stdout,
        media_type="audio/aac",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


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
