"""Timeline preview thumbnails: one small JPEG per grid slot, made on demand and cached.

Why CPU stays low:
  - the requested time snaps to a grid (default 30 s = 2 per 60 s chunk), so hovering anywhere in a slot
    reuses one picture;
  - ffmpeg input-seeks without accurate seek and decodes only keyframes, so a thumbnail is one I-frame
    decode + a tiny scale/encode on a single thread;
  - results are kept in an in-memory LRU (recordings never change, so a thumbnail never goes stale);
  - concurrent requests for the same slot share one ffmpeg run, and a semaphore bounds how many run at once.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from settings.settings import settings

logger = logging.getLogger("node.thumbnails")

MIN_WIDTH, MAX_WIDTH = 80, 640

ThumbKey = tuple[UUID, int, int]  # (segment id, slot index, width)
Runner = Callable[[Path, float, int], Awaitable[bytes]]


class ThumbnailError(Exception):
    """ffmpeg could not make a picture (no video track, corrupt file, ...)."""


def thumb_slot(at_ms: int, duration_ms: int, grid_ms: int) -> tuple[int, int]:
    """(slot index, slot start ms) for a time inside the chunk. ValueError when outside it."""
    if at_ms < 0 or at_ms >= max(duration_ms, 1):
        raise ValueError("at_ms is outside the recording")
    slot = at_ms // grid_ms
    return slot, slot * grid_ms


def clamp_width(width: int | None) -> int:
    return min(MAX_WIDTH, max(MIN_WIDTH, width or settings.THUMBNAIL_WIDTH))


def thumb_command(path: Path, seconds: float, width: int) -> list[str]:
    return [
        settings.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-threads", "1",
        "-skip_frame", "nokey", "-noaccurate_seek", "-ss", f"{seconds:.3f}", "-i", str(path),
        "-an", "-sn", "-dn", "-frames:v", "1", "-vf", f"scale={width}:-2",
        "-q:v", "5", "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1",
    ]


async def run_ffmpeg(path: Path, seconds: float, width: int) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *thumb_command(path, seconds, width), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise
    if process.returncode or not stdout:
        raise ThumbnailError(stderr.decode("utf-8", "replace")[-300:] or "no picture")
    return stdout


class ThumbnailService:
    def __init__(self, max_entries: int, max_jobs: int, runner: Runner = run_ffmpeg):
        self.max_entries = max_entries
        self.runner = runner
        self._cache: OrderedDict[ThumbKey, bytes] = OrderedDict()
        self._inflight: dict[ThumbKey, asyncio.Future[bytes]] = {}
        self._jobs = asyncio.Semaphore(max_jobs)
        self.generated = 0  # ffmpeg runs (for tests / debugging)

    def _remember(self, key: ThumbKey, data: bytes) -> None:
        self._cache[key] = data
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)

    def cached(self, key: ThumbKey) -> bytes | None:
        data = self._cache.get(key)
        if data is not None:
            self._cache.move_to_end(key)
        return data

    async def get(self, segment_id: UUID, path: Path, slot: int, slot_ms: int, width: int) -> bytes:
        key = (segment_id, slot, width)
        data = self.cached(key)
        if data is not None:
            return data
        pending = self._inflight.get(key)
        if pending is not None:  # same slot already being made: wait for that run
            return await asyncio.shield(pending)
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            async with self._jobs:
                self.generated += 1
                data = await self.runner(path, slot_ms / 1000, width)
            self._remember(key, data)
            future.set_result(data)
            return data
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved: no "never retrieved" warning when nobody else waits
            raise
        finally:
            self._inflight.pop(key, None)

    def forget_segment(self, segment_id: UUID) -> None:
        for key in [k for k in self._cache if k[0] == segment_id]:
            del self._cache[key]


thumbnails = ThumbnailService(settings.THUMBNAIL_CACHE_MAX, settings.THUMBNAIL_JOBS)
