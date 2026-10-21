"""L3 worker: claim one camera-SD recovery job, replay it, and publish an indexed fMP4."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from app.node.utils import CentralError, central, runtime
from app.onvif.profile_g import ProfileGClient, exact_replay_uri
from app.onvif.services import OnvifDevice
from app.onvif.soap import Fault, OnvifError
from app.recordings.models import LocalSegment
from app.recordings.services import register_backfill_segment
from app.recordings.utils import Mp4IndexError, index_fmp4
from app.storage.services import storage
from settings.settings import settings

logger = logging.getLogger("node.backfill")


def _auth_uri(uri: str, username: str, password: str) -> str:
    parts = urlsplit(uri)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if parts.port:
        host += f":{parts.port}"
    auth = f"{quote(username, safe='')}:{quote(password, safe='')}@" if username else ""
    return parts._replace(netloc=f"{auth}{host}").geturl()


def _run_ffmpeg(uri: str, username: str, password: str, duration: float, output: Path, include_audio: bool):
    command = [
        settings.FFMPEG_BIN, "-hide_banner", "-loglevel", "warning", "-y",
        "-rtsp_transport", "tcp", "-timeout", "15000000", "-i", _auth_uri(uri, username, password),
        "-t", f"{duration:.3f}", "-map", "0:v:0",
    ]
    if include_audio:
        command += ["-map", "0:a?"]
    command += [
        "-c", "copy", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-frag_duration", str(round(settings.HLS_PART_TARGET_SECONDS * 1_000_000)), str(output),
    ]
    return subprocess.run(command, capture_output=True, text=True, timeout=max(60, duration * 3 + 30), check=False)


def _safe_error(result: subprocess.CompletedProcess[str], username: str, password: str) -> str:
    text = result.stderr or "FFmpeg replay failed"
    if password:
        text = text.replace(password, "<hidden>")
    if username:
        text = text.replace(username, "<user>")
    return text[-500:].strip()


async def _download(job: dict, replay_uri: str) -> tuple[Path, str, int | None, object, bool]:
    start = datetime.fromisoformat(job["start_time"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(job["end_time"].replace("Z", "+00:00"))
    duration = (end - start).total_seconds()
    uri = exact_replay_uri(replay_uri, start, end)
    volume = storage.target()
    if volume is None or not volume.accepting or not volume.usable:
        raise Fault("No recording storage is accepting writes")
    local = start.astimezone()
    rel = f"cam-{job['camera_id']}/{job['profile']}/{local:%Y-%m-%d}/{local:%H-%M-%S-%f}.mp4"
    final = volume.path / rel
    existing = await LocalSegment.get_or_none(rel_path=rel)
    if existing and final.exists():
        return final, rel, existing.volume_id, None, False
    temp_dir = volume.path / ".backfill_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp = temp_dir / f"{job['id']}.partial.mp4"
    temp.unlink(missing_ok=True)
    try:
        result = await asyncio.to_thread(
            _run_ffmpeg, uri, job["username"], job["password"], duration, temp, True,
        )
        audio_omitted = False
        if result.returncode != 0 and "codec not currently supported in container" in result.stderr:
            audio_omitted = True
            temp.unlink(missing_ok=True)
            result = await asyncio.to_thread(
                _run_ffmpeg, uri, job["username"], job["password"], duration, temp, False,
            )
        if result.returncode != 0 or not temp.exists() or temp.stat().st_size == 0:
            raise Fault(_safe_error(result, job["username"], job["password"]))
        index = await asyncio.to_thread(index_fmp4, temp, settings.HLS_PART_TARGET_SECONDS)
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp, final)
        return final, rel, volume.key, index, audio_omitted
    finally:
        temp.unlink(missing_ok=True)


async def backfill_tick() -> None:
    if runtime.node_id is None:
        return
    try:
        job = await central.claim_backfill(runtime.node_id)
    except CentralError as exc:
        logger.debug("Cannot claim backfill work: %s", exc)
        return
    if not job:
        return
    job_id = str(job["id"])
    try:
        await central.backfill_progress(job_id, runtime.node_id, "DOWNLOADING", 5)
        async with OnvifDevice(job["host"], job["port"], job["username"], job["password"], timeout=20) as dev:
            await dev.clock()
            replay_uri = await ProfileGClient(dev).replay_uri(job["recording_token"])
        final, rel, volume_id, index, audio_omitted = await _download(job, replay_uri)
        if index is None:  # deterministic retry found an already published segment
            existing = await LocalSegment.get(rel_path=rel)
            seconds, size = existing.duration_ms / 1000, existing.size_bytes
            partial = False
        else:
            await central.backfill_progress(job_id, runtime.node_id, "INDEXING", 90)
            start = datetime.fromisoformat(job["start_time"].replace("Z", "+00:00"))
            await register_backfill_segment(
                volume_id=volume_id, rel_path=rel,
                camera_id=job["camera_id"], profile=job["profile"],
                generation=job["assignment_generation"], start_time=start, index=index, job_id=job["id"],
            )
            seconds, size = index.duration_ms / 1000, index.size_bytes
            requested = (datetime.fromisoformat(job["end_time"].replace("Z", "+00:00")) - start).total_seconds()
            partial = seconds + 2 < requested
        await central.backfill_complete(job_id, runtime.node_id, seconds, size, partial)
        logger.info("Backfill %s imported %.1fs (%s bytes)%s", job_id, seconds, size,
                    " without unsupported audio" if audio_omitted else "")
    except (OnvifError, CentralError, Mp4IndexError, OSError, ValueError, subprocess.SubprocessError) as exc:
        code = getattr(exc, "code", None) or ("central_error" if isinstance(exc, CentralError) else "import_failed")
        message = str(exc)[:512]
        logger.warning("Backfill %s failed: %s", job_id, message)
        try:
            await central.backfill_fail(job_id, runtime.node_id, code, message)
        except CentralError:
            pass
