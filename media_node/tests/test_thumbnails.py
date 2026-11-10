"""Timeline thumbnails: grid snapping, cache, de-duplication, concurrency bound, and one real ffmpeg run."""

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from app.recordings.thumbnails import (
    MAX_WIDTH,
    MIN_WIDTH,
    ThumbnailError,
    ThumbnailService,
    clamp_width,
    run_ffmpeg,
    thumb_command,
    thumb_slot,
)

GRID = 30_000
SEG = uuid.uuid4()
FILE = Path("chunk.mp4")


def test_times_in_one_slot_share_a_key():
    assert thumb_slot(0, 60_000, GRID) == (0, 0)
    assert thumb_slot(12_000, 60_000, GRID) == (0, 0)
    assert thumb_slot(29_999, 60_000, GRID) == (0, 0)
    assert thumb_slot(30_000, 60_000, GRID) == (1, 30_000)
    assert thumb_slot(59_999, 60_000, GRID) == (1, 30_000)


def test_times_outside_the_chunk_are_rejected():
    for at in (-1, 60_000, 90_000):
        with pytest.raises(ValueError):
            thumb_slot(at, 60_000, GRID)


def test_width_is_clamped_and_defaults():
    assert clamp_width(None) == 240
    assert clamp_width(10) == MIN_WIDTH
    assert clamp_width(5000) == MAX_WIDTH


def test_command_is_a_cheap_keyframe_grab():
    cmd = thumb_command(FILE, 30.0, 240)
    for flag in ("-noaccurate_seek", "-skip_frame", "nokey", "-frames:v", "-an"):
        assert flag in cmd
    assert cmd.index("-ss") < cmd.index("-i")  # input seek, not output seek
    assert "scale=240:-2" in cmd


def _fake_runner(calls: list, delay: float = 0.0, fail: bool = False):
    async def run(path, seconds, width):
        calls.append((path, seconds, width))
        await asyncio.sleep(delay)
        if fail:
            raise ThumbnailError("broken")
        return f"jpeg@{seconds}:{width}".encode()
    return run


def test_second_request_is_a_cache_hit():
    calls = []
    svc = ThumbnailService(10, 2, _fake_runner(calls))

    async def go():
        a = await svc.get(SEG, FILE, 1, 30_000, 240)
        b = await svc.get(SEG, FILE, 1, 30_000, 240)
        return a, b

    a, b = asyncio.run(go())
    assert a == b == b"jpeg@30.0:240"
    assert len(calls) == 1 and svc.generated == 1


def test_concurrent_requests_for_one_slot_run_ffmpeg_once():
    calls = []
    svc = ThumbnailService(10, 2, _fake_runner(calls, delay=0.05))

    async def go():
        return await asyncio.gather(*(svc.get(SEG, FILE, 0, 0, 240) for _ in range(5)))

    results = asyncio.run(go())
    assert len(set(results)) == 1
    assert len(calls) == 1


def test_semaphore_bounds_parallel_ffmpeg_runs():
    running = 0
    peak = 0

    async def run(path, seconds, width):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return b"x"

    svc = ThumbnailService(100, 2, run)

    async def go():
        await asyncio.gather(*(svc.get(SEG, FILE, slot, slot * GRID, 240) for slot in range(8)))

    asyncio.run(go())
    assert peak == 2
    assert svc.generated == 8


def test_lru_evicts_oldest_and_forget_segment():
    calls = []
    svc = ThumbnailService(2, 2, _fake_runner(calls))
    other = uuid.uuid4()

    async def go():
        await svc.get(SEG, FILE, 0, 0, 240)
        await svc.get(SEG, FILE, 1, GRID, 240)
        await svc.get(other, FILE, 0, 0, 240)  # evicts (SEG, 0)

    asyncio.run(go())
    assert svc.cached((SEG, 0, 240)) is None
    assert svc.cached((SEG, 1, 240)) is not None
    svc.forget_segment(SEG)
    assert svc.cached((SEG, 1, 240)) is None
    assert svc.cached((other, 0, 240)) is not None


def test_failure_is_not_cached():
    calls = []
    svc = ThumbnailService(10, 2, _fake_runner(calls, fail=True))

    async def go():
        for _ in range(2):
            with pytest.raises(ThumbnailError):
                await svc.get(SEG, FILE, 0, 0, 240)

    asyncio.run(go())
    assert len(calls) == 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_ffmpeg_makes_a_jpeg(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
         "-t", "4", "-g", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-movflags", "+frag_keyframe+empty_moov+default_base_moof", str(clip)],
        check=True,
    )
    data = asyncio.run(run_ffmpeg(clip, 2.0, 160))
    assert data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"  # JPEG SOI / EOI
    assert len(data) < 30_000


def test_endpoint_snaps_caches_and_404s_outside(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.recordings import router

    seg = SimpleNamespace(id=SEG, duration_ms=60_000, rel_path="cam1/a.mp4")
    calls = []

    async def fake_segment(segment_id):
        return seg, Path("vol")

    monkeypatch.setattr(router, "_segment", fake_segment)
    monkeypatch.setattr(router, "thumbnails", ThumbnailService(10, 2, _fake_runner(calls)))

    async def go():
        a = await router.media_thumb(SEG, at_ms=31_000)
        b = await router.media_thumb(SEG, at_ms=58_000)  # same 30 s slot -> cache
        with pytest.raises(HTTPException) as exc:
            await router.media_thumb(SEG, at_ms=60_000)
        return a, b, exc.value

    a, b, err = asyncio.run(go())
    assert a.media_type == "image/jpeg" and a.body == b.body == b"jpeg@30.0:240"
    assert "immutable" in a.headers["cache-control"]
    assert len(calls) == 1 and calls[0][0] == Path("vol") / "cam1/a.mp4"
    assert err.status_code == 404
