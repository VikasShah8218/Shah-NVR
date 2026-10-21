from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from app.node.utils import CentralError, central, runtime
from settings.settings import settings

logger = logging.getLogger("node.exports")
EXPORT_DIR = settings.EXPORTS_DIR


class ExportCancelled(Exception):
    pass


async def _encoders() -> set[str]:
    try:
        proc = await asyncio.create_subprocess_exec(settings.FFMPEG_BIN, "-hide_banner", "-encoders",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output, _ = await asyncio.wait_for(proc.communicate(), 15)
        text = output.decode(errors="replace")
        return {name for name in ("h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv") if name in text}
    except (OSError, asyncio.TimeoutError):
        return set()


async def capabilities() -> dict:
    encoders = await _encoders()
    return {"cpu": ["libx264", "libx265"], "gpu": sorted(encoders), "gpu_available": bool(encoders)}


async def _command(job: dict, output: Path) -> tuple[list[str], str]:
    options = job["options"]
    source = urljoin(settings.CENTRAL_URL.rstrip("/") + "/", job["source_url"].lstrip("/"))
    command = [settings.FFMPEG_BIN, "-hide_banner", "-loglevel", "warning", "-y", "-i", source,
               "-ss", f"{float(job.get('trim_start_seconds') or 0):.3f}",
               "-t", f"{float(job.get('max_output_seconds') or 0.1):.3f}",
               "-map", "0:v:0", "-map", "0:a?", "-dn", "-sn"]
    if job["mode"] == "original":
        command += ["-c", "copy", "-movflags", "+faststart+use_metadata_tags"]
        encoder = "copy"
    else:
        codec = options.get("video_codec", "h264")
        processor = options.get("processor", "auto")
        available = await _encoders()
        gpu_choices = [f"{codec}_nvenc" if codec == "h264" else "hevc_nvenc",
                       f"{codec}_qsv" if codec == "h264" else "hevc_qsv"]
        encoder = next((name for name in gpu_choices if name in available), None) if processor != "cpu" else None
        if processor == "gpu" and not encoder:
            raise RuntimeError(f"No supported {codec.upper()} GPU encoder is available")
        encoder = encoder or ("libx264" if codec == "h264" else "libx265")
        quality = options.get("quality", "balanced")
        if encoder.startswith("libx"):
            values = ({"high": 18, "balanced": 23, "small": 28} if codec == "h264" else
                      {"high": 22, "balanced": 27, "small": 31})
            command += ["-c:v", encoder, "-preset", "medium", "-crf", str(values[quality])]
        elif encoder.endswith("_nvenc"):
            values = {"high": 19, "balanced": 24, "small": 29}
            command += ["-c:v", encoder, "-preset", "p5", "-rc", "vbr", "-cq", str(values[quality]), "-b:v", "0"]
        else:
            values = {"high": 19, "balanced": 24, "small": 29}
            command += ["-c:v", encoder, "-preset", "medium", "-global_quality", str(values[quality])]
        if codec == "h264":
            command += ["-pix_fmt", "yuv420p"]
        else:
            command += ["-tag:v", "hvc1"]
        filters = []
        if int(options.get("max_height") or 0):
            filters.append(f"scale=-2:'min({int(options['max_height'])},ih)':force_original_aspect_ratio=decrease")
        if int(options.get("max_fps") or 0):
            filters.append(f"fps={int(options['max_fps'])}")
        if filters:
            command += ["-vf", ",".join(filters)]
        if options.get("include_audio", True):
            command += ["-c:a", "aac", "-b:a", f"{int(options.get('audio_bitrate_kbps', 128))}k"]
        else:
            command += ["-an"]
        command += ["-movflags", "+faststart"]
    command += ["-progress", "pipe:1", "-nostats", str(output)]
    return command, encoder


async def _run(job: dict, output: Path) -> tuple[str, float]:
    command, encoder = await _command(job, output)
    expected_us = max(1, int((datetime.fromisoformat(job["end_time"].replace("Z", "+00:00")) -
        datetime.fromisoformat(job["start_time"].replace("Z", "+00:00"))).total_seconds() * 1_000_000))
    proc = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, creationflags=(0x08000000 if os.name == "nt" else 0))
    last_report, recorded = 0.0, 0.0
    recent_output: deque[str] = deque(maxlen=20)
    assert proc.stdout is not None
    try:
        while True:
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=2)
            except asyncio.TimeoutError:
                raw = b""
            if raw:
                line = raw.decode(errors="replace").strip()
                recent_output.append(line)
                key, _, value = line.partition("=")
                if key in ("out_time_us", "out_time_ms"):
                    recorded = max(recorded, int(value or 0) / 1_000_000)
            now = time.monotonic()
            if now - last_report >= 2:
                result = await central.export_progress(str(job["id"]), runtime.node_id, "PROCESSING",
                    min(98, max(1, recorded * 1_000_000 / expected_us * 98)))
                last_report = now
                if result.get("cancelled"):
                    raise ExportCancelled()
            if proc.returncode is not None:
                break
            if not raw:
                await asyncio.sleep(.05)
        if proc.returncode != 0:
            detail = " | ".join(recent_output)[-900:]
            raise RuntimeError(detail or f"FFmpeg exited with code {proc.returncode}")
    except BaseException:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        raise
    return encoder, recorded


async def _probe(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(settings.FFPROBE_BIN, "-v", "error", "-show_streams",
        "-show_format", "-of", "json", str(path), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, creationflags=(0x08000000 if os.name == "nt" else 0))
    stdout, stderr = await asyncio.wait_for(proc.communicate(), 30)
    if proc.returncode != 0:
        raise RuntimeError(f"Export validation failed: {stderr.decode(errors='replace')[-500:]}")
    data = json.loads(stdout)
    if not any(stream.get("codec_type") == "video" for stream in data.get("streams", [])):
        raise RuntimeError("Export validation failed: output contains no video stream")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("Export validation failed: output duration is missing")
    return duration


async def export_tick() -> None:
    if runtime.node_id is None:
        return
    try:
        job = await central.claim_export(runtime.node_id)
    except CentralError as exc:
        logger.debug("Cannot claim export work: %s", exc)
        return
    if not job:
        return
    job_id = str(job["id"])
    job_dir = EXPORT_DIR / job_id
    partial, final = job_dir / "output.partial.mp4", job_dir / "output.mp4"
    try:
        job_dir.mkdir(parents=True, exist_ok=True)
        estimated = int(job["options"].get("estimated_input_bytes") or 0)
        required = settings.EXPORT_MIN_FREE_BYTES + int(estimated * 1.2)
        if shutil.disk_usage(EXPORT_DIR).free < required:
            raise RuntimeError("Not enough free disk space to safely create this export")
        partial.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        try:
            encoder, recorded = await _run(job, partial)
        except RuntimeError:
            if job["mode"] != "compressed" or job["options"].get("processor", "auto") != "auto":
                raise
            logger.info("Export %s automatic GPU attempt failed; retrying on CPU", job_id)
            partial.unlink(missing_ok=True)
            job = {**job, "options": {**job["options"], "processor": "cpu"}}
            encoder, recorded = await _run(job, partial)
        if not partial.exists() or partial.stat().st_size == 0:
            raise RuntimeError("FFmpeg produced no output")
        await central.export_progress(job_id, runtime.node_id, "FINALIZING", 99)
        recorded = await _probe(partial)
        os.replace(partial, final)
        def checksum() -> str:
            digest = hashlib.sha256()
            with final.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest()
        digest = await asyncio.to_thread(checksum)
        metadata = {"name": job["output_name"], "created": time.time()}
        (job_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        await central.export_complete(job_id, runtime.node_id, final.stat().st_size, digest, encoder, recorded)
        logger.info("Export %s ready (%s bytes, %s)", job_id, final.stat().st_size, encoder)
    except ExportCancelled:
        logger.info("Export %s cancelled", job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
    except CentralError as exc:
        logger.warning("Export %s lost central contact: %s", job_id, exc)
        # If completion may have committed before the connection failed, retain the atomically
        # published file. Otherwise the expired lease safely requeues the job and clears partials.
        if not final.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, asyncio.TimeoutError) as exc:
        logger.warning("Export %s failed: %s", job_id, exc)
        shutil.rmtree(job_dir, ignore_errors=True)
        try:
            await central.export_fail(job_id, runtime.node_id, "export_failed", str(exc))
        except CentralError:
            pass


async def export_cleanup_tick() -> None:
    if not EXPORT_DIR.exists():
        return
    cutoff = time.time() - settings.EXPORT_FILE_TTL_HOURS * 3600
    for path in EXPORT_DIR.iterdir():
        if path.is_dir() and path.stat().st_mtime < cutoff:
            shutil.rmtree(path, ignore_errors=True)
