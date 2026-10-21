import asyncio
from pathlib import Path

from app.exports import service


def job(mode="compressed", **options):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "source_url": "/api/v1/playback/1/index.m3u8?profile=main",
        "start_time": "2026-10-21T00:00:00Z",
        "end_time": "2026-10-21T01:00:00Z",
        "mode": mode,
        "trim_start_seconds": 1.25,
        "max_output_seconds": 3598.75,
        "options": {"video_codec": "h264", "quality": "balanced", "processor": "cpu",
                    "max_height": 720, "max_fps": 15, "include_audio": True,
                    "audio_bitrate_kbps": 128, **options},
    }


def test_ffmpeg_progress_accepts_stream_copy_na_values():
    assert service._progress_seconds("out_time_us=N/A") is None
    assert service._progress_seconds("out_time_ms=N/A") is None
    assert service._progress_seconds("progress=continue") is None
    assert service._progress_seconds("out_time_us=1250000") == 1.25


def test_original_export_is_stream_copy(monkeypatch):
    monkeypatch.setattr(service.settings, "CENTRAL_URL", "http://central:8000")
    command, encoder = asyncio.run(service._command(job("original"), Path("out.mp4")))
    assert encoder == "copy"
    assert ["-c", "copy"] == command[command.index("-c"):command.index("-c") + 2]
    assert "http://central:8000/api/v1/playback/1/index.m3u8?profile=main" in command
    assert command[command.index("-ss") + 1] == "1.250"
    assert command[command.index("-t") + 1] == "3598.750"


def test_cpu_compression_has_bounded_filters_and_audio(monkeypatch):
    monkeypatch.setattr(service.settings, "CENTRAL_URL", "http://central:8000")
    command, encoder = asyncio.run(service._command(job(), Path("out.mp4")))
    assert encoder == "libx264"
    assert "scale=-2:'min(720,ih)':force_original_aspect_ratio=decrease,fps=15" in command
    assert command[command.index("-c:a") + 1] == "aac"


def test_explicit_gpu_fails_when_unavailable(monkeypatch):
    async def none(): return set()
    monkeypatch.setattr(service, "_encoders", none)
    try:
        asyncio.run(service._command(job(processor="gpu"), Path("out.mp4")))
    except RuntimeError as exc:
        assert "GPU encoder" in str(exc)
    else:
        raise AssertionError("GPU mode must not silently fall back to CPU")


def test_auto_prefers_supported_gpu_encoder(monkeypatch):
    async def nvenc(): return {"h264_nvenc"}
    monkeypatch.setattr(service, "_encoders", nvenc)
    command, encoder = asyncio.run(service._command(job(processor="auto"), Path("out.mp4")))
    assert encoder == "h264_nvenc"
    assert command[command.index("-c:v") + 1] == "h264_nvenc"
