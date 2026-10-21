from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.cameras.models import Camera, CameraStream
from app.exports.schemas import ClaimIn, ClaimedExportOut, CompleteIn, ExportCreate, ExportOut, FailIn, ProgressIn, ProgressOut
from app.nodes.models import MediaNode, NodeState
from app.recordings.models import ExportJob, ExportMode, ExportState
from app.recordings.utils import compute_gaps, find_segments
from settings.settings import settings
from utilities.common import utcnow

router = APIRouter(prefix="/api/v1/exports", tags=["Exports"])
internal_router = APIRouter(prefix="/internal/v1/exports", tags=["Internal: Exports"])
ACTIVE = (ExportState.QUEUED, ExportState.CLAIMED, ExportState.PROCESSING, ExportState.FINALIZING)
LEASE = timedelta(minutes=5)


def _out(job: ExportJob) -> ExportOut:
    return ExportOut.model_validate(job, from_attributes=True)


async def _expire() -> None:
    await ExportJob.filter(state=ExportState.READY, expires_at__lt=utcnow()).update(state=ExportState.EXPIRED)


@router.post("", response_model=ExportOut, status_code=201)
async def create_export(body: ExportCreate):
    camera = await Camera.get_or_none(id=body.camera_id)
    if camera is None:
        raise HTTPException(404, "Camera not found")
    if body.end_time <= body.start_time:
        raise HTTPException(422, "Export end must be after start")
    if body.end_time - body.start_time > timedelta(hours=settings.EXPORT_MAX_HOURS):
        raise HTTPException(422, f"Export duration is limited to {settings.EXPORT_MAX_HOURS} hours")
    if body.end_time > utcnow() + timedelta(seconds=5):
        raise HTTPException(422, "Export end cannot be in the future")
    if not await CameraStream.exists(camera_id=camera.id, profile=body.profile, record=True):
        raise HTTPException(409, "The selected camera profile is not recorded")
    segments = await find_segments(camera.id, body.profile, body.start_time, body.end_time)
    if not segments:
        raise HTTPException(409, {"code": "no_recording", "message": "No recording exists in this interval"})
    weights: dict[int, int] = defaultdict(int)
    for segment in segments:
        weights[segment.node_id] += segment.size_bytes
    nodes = {n.id: n for n in await MediaNode.filter(id__in=list(weights))}
    eligible = [node_id for node_id in weights if node_id in nodes and nodes[node_id].state in
                (NodeState.READY, NodeState.ACTIVE, NodeState.CORDONED, NodeState.DRAINING)]
    if not eligible:
        raise HTTPException(409, "No healthy media node can process this export")
    playable_segments = [segment for segment in segments if segment.node_id in eligible]
    signatures = {(s.codec or "unknown", s.config_signature or "") for s in playable_segments}
    if body.mode == ExportMode.ORIGINAL and len(signatures) > 1:
        raise HTTPException(409, {"code": "incompatible_segments", "message":
            "Original export crosses a codec or encoder change. Use compressed export or select a shorter interval."})
    node_id = max(eligible, key=lambda value: weights[value])
    gaps = compute_gaps(playable_segments, body.start_time, body.end_time)
    gap_seconds = sum((end - start).total_seconds() for start, end in gaps)
    options = body.model_dump(exclude={"camera_id", "profile", "start_time", "end_time", "mode"})
    options["estimated_input_bytes"] = sum(segment.size_bytes for segment in playable_segments)
    stamp = body.start_time.astimezone().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in camera.name)[:80]
    job = await ExportJob.create(id=uuid4(), camera_id=camera.id, node_id=node_id, profile=body.profile,
        start_time=body.start_time, end_time=body.end_time, mode=body.mode, options=options,
        gap_seconds=gap_seconds, output_name=f"{safe_name}_{body.profile}_{stamp}.mp4")
    return _out(job)


@router.get("", response_model=list[ExportOut])
async def list_exports(camera_id: int | None = None, limit: int = Query(50, ge=1, le=200)):
    await _expire()
    query = ExportJob.all()
    if camera_id is not None:
        query = query.filter(camera_id=camera_id)
    return [_out(job) for job in await query.limit(limit)]


@router.get("/{job_id}", response_model=ExportOut)
async def get_export(job_id: UUID):
    await _expire()
    job = await ExportJob.get_or_none(id=job_id)
    if job is None:
        raise HTTPException(404, "Export not found")
    return _out(job)


@router.post("/{job_id}/cancel", response_model=ExportOut)
async def cancel_export(job_id: UUID):
    job = await ExportJob.get_or_none(id=job_id)
    if job is None:
        raise HTTPException(404, "Export not found")
    if job.state in ACTIVE:
        job.state, job.finished_at, job.lease_expires_at = ExportState.CANCELLED, utcnow(), None
        await job.save()
    return _out(job)


@router.get("/{job_id}/download")
async def download_export(job_id: UUID, access: str = Query("lan", pattern="^(lan|public)$")):
    await _expire()
    job = await ExportJob.get_or_none(id=job_id).prefetch_related("node")
    if job is None:
        raise HTTPException(404, "Export not found")
    if job.state != ExportState.READY or job.node is None:
        raise HTTPException(409, "Export is not ready for download")
    return RedirectResponse(f"{job.node.api_url_for(access).rstrip('/')}/api/v1/exports/{job.id}/file")


@internal_router.post("/claim", response_model=ClaimedExportOut | None)
async def claim_export(body: ClaimIn):
    if not await MediaNode.exists(id=body.node_id):
        raise HTTPException(404, "Node not found")
    now = utcnow()
    await ExportJob.filter(node_id=body.node_id, state__in=(ExportState.CLAIMED, ExportState.PROCESSING,
        ExportState.FINALIZING), lease_expires_at__lt=now).update(state=ExportState.QUEUED)
    job = await ExportJob.filter(node_id=body.node_id, state=ExportState.QUEUED).order_by("created_at").first()
    if job is None:
        return None
    camera = await Camera.get(id=job.camera_id)
    segments = await find_segments(camera.id, job.profile, job.start_time, job.end_time)
    segment_nodes = {node.id: node for node in await MediaNode.filter(id__in={s.node_id for s in segments})}
    segments = [s for s in segments if s.node_id in segment_nodes and
                segment_nodes[s.node_id].state not in (NodeState.UNREACHABLE, NodeState.OFFLINE)]
    first_part_start = None
    cursor = job.start_time
    for segment in segments:
        part_start = segment.start_time
        for duration_ms in segment.parts:
            part_end = part_start + timedelta(milliseconds=duration_ms)
            if part_end > job.start_time and part_start < job.end_time and part_end > cursor + timedelta(milliseconds=500):
                first_part_start = first_part_start or part_start
                cursor = max(cursor, part_end)
            part_start = part_end
    trim_start = max(0.0, (job.start_time - (first_part_start or job.start_time)).total_seconds())
    media_seconds = max(0.1, (job.end_time - job.start_time).total_seconds() - job.gap_seconds)
    job.state, job.started_at, job.lease_expires_at = ExportState.CLAIMED, job.started_at or now, now + LEASE
    job.attempt_count += 1
    await job.save()
    query = urlencode({"profile": job.profile, "start": job.start_time.isoformat(),
                       "end": job.end_time.isoformat(), "access": "lan"})
    return {"id": job.id, "source_url": f"/api/v1/playback/{camera.id}/index.m3u8?{query}",
            "camera_id": camera.id, "camera_name": camera.name, "profile": job.profile,
            "start_time": job.start_time, "end_time": job.end_time, "mode": job.mode,
            "options": job.options, "output_name": job.output_name,
            "trim_start_seconds": trim_start, "max_output_seconds": media_seconds}


async def _job(job_id: UUID, node_id: int) -> ExportJob:
    job = await ExportJob.get_or_none(id=job_id, node_id=node_id)
    if job is None:
        raise HTTPException(404, "Export not found")
    return job


@internal_router.post("/{job_id}/progress", response_model=ProgressOut)
async def export_progress(job_id: UUID, body: ProgressIn):
    job = await _job(job_id, body.node_id)
    if job.state == ExportState.CANCELLED:
        return {"cancelled": True}
    if job.state not in ACTIVE:
        raise HTTPException(409, "Export lease is no longer active")
    job.state, job.progress_percent, job.lease_expires_at = ExportState(body.state), body.progress_percent, utcnow() + LEASE
    await job.save()
    return {"cancelled": False}


@internal_router.post("/{job_id}/complete", status_code=204)
async def export_complete(job_id: UUID, body: CompleteIn):
    job = await _job(job_id, body.node_id)
    if job.state == ExportState.CANCELLED:
        raise HTTPException(409, "Export was cancelled")
    if job.state not in ACTIVE:
        raise HTTPException(409, "Export lease is no longer active")
    job.state, job.progress_percent = ExportState.READY, 100
    job.output_size_bytes, job.output_sha256, job.encoder = body.size_bytes, body.sha256, body.encoder
    job.recorded_seconds, job.finished_at = body.recorded_seconds, utcnow()
    job.expires_at = job.finished_at + timedelta(hours=settings.EXPORT_FILE_TTL_HOURS)
    job.lease_expires_at = None
    await job.save()


@internal_router.post("/{job_id}/fail", status_code=204)
async def export_fail(job_id: UUID, body: FailIn):
    job = await _job(job_id, body.node_id)
    if job.state == ExportState.CANCELLED:
        return
    job.state, job.error_code, job.error_message = ExportState.FAILED, body.code, body.message
    job.finished_at, job.lease_expires_at = utcnow(), None
    await job.save()
