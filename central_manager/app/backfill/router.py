from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query

from app.assignments.models import CameraAssignment
from app.backfill.schemas import (
    BackfillConfigOut, BackfillConfigUpdate, BackfillJobCreate, BackfillJobOut, BackfillProbeOut,
    ClaimIn, ClaimedJobOut, JobCompleteIn, JobFailIn, JobProgressIn,
)
from app.cameras.models import Camera, CameraStream
from app.nodes.client import call_node, pick_node
from app.nodes.models import MediaNode
from app.onvif.services import device_target
from app.recordings.models import BackfillJob, BackfillState
from app.recordings.utils import compute_gaps, find_segments
from utilities.common import utcnow

router = APIRouter(prefix="/api/v1/cameras", tags=["L3 Backfill"])
internal_router = APIRouter(prefix="/internal/v1/backfill", tags=["Internal: L3 Backfill"])

ACTIVE = (BackfillState.QUEUED, BackfillState.CLAIMED, BackfillState.DOWNLOADING, BackfillState.INDEXING)
MAX_JOB = timedelta(minutes=15)
RECENT_SAFETY = timedelta(minutes=5)
LEASE = timedelta(minutes=20)


async def _camera(camera_id: int) -> Camera:
    camera = await Camera.get_or_none(id=camera_id)
    if camera is None:
        raise HTTPException(404, "Camera not found")
    return camera


def _config(camera: Camera) -> dict:
    return {
        "camera_id": camera.id,
        "mode": camera.backfill_mode,
        "profile": camera.backfill_profile,
        "capability": camera.backfill_capability,
        "recording_token": camera.backfill_recording_token,
        "earliest": camera.backfill_earliest,
        "latest": camera.backfill_latest,
        "checked_at": camera.backfill_checked_at,
        "error": camera.backfill_error,
    }


def _job(job: BackfillJob) -> BackfillJobOut:
    return BackfillJobOut.model_validate(job, from_attributes=True)


def _datetime(value: str | datetime | None) -> datetime | None:
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


@router.get("/{camera_id}/backfill", response_model=BackfillConfigOut)
async def get_backfill(camera_id: int):
    return _config(await _camera(camera_id))


@router.post("/{camera_id}/backfill/probe", response_model=BackfillProbeOut)
async def probe_backfill(camera_id: int):
    camera = await _camera(camera_id)
    host, port = device_target(camera)
    node = await pick_node(camera_id=camera.id)
    body = {"host": host, "port": port, "username": camera.username or "", "password": camera.password or ""}
    try:
        result = await call_node(node, "/api/v1/onvif/profile-g/probe", body, timeout=60)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        await Camera.filter(id=camera.id).update(
            backfill_capability="unsupported" if detail.get("code") == "not_supported" else "degraded",
            backfill_checked_at=utcnow(), backfill_error=detail.get("message", "Profile G probe failed")[:512],
        )
        raise
    recordings = result.get("recordings") or []
    tokens = {r["token"] for r in recordings if r.get("replay_available")}
    selected = camera.backfill_recording_token if camera.backfill_recording_token in tokens else None
    if selected is None and len(tokens) == 1:
        selected = next(iter(tokens))
    supported = bool(result.get("supported"))
    await Camera.filter(id=camera.id).update(
        backfill_capability="supported" if supported else "unsupported",
        backfill_recording_token=selected,
        backfill_earliest=_datetime(result.get("earliest")), backfill_latest=_datetime(result.get("latest")),
        backfill_checked_at=utcnow(), backfill_error=None if supported else "No replayable camera recording found",
    )
    camera = await _camera(camera.id)
    return {**_config(camera), "recordings": recordings}


@router.patch("/{camera_id}/backfill", response_model=BackfillConfigOut)
async def update_backfill(camera_id: int, body: BackfillConfigUpdate):
    camera = await _camera(camera_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("mode") in ("manual", "automatic"):
        if camera.backfill_capability != "supported":
            raise HTTPException(409, {"code": "profile_g_unverified", "message": "Test camera storage first"})
        token = data.get("recording_token", camera.backfill_recording_token)
        if not token:
            raise HTTPException(409, {"code": "no_recording_match", "message": "Select a camera recording"})
    mapped = {f"backfill_{key}": value for key, value in data.items()}
    if mapped:
        await Camera.filter(id=camera.id).update(**mapped)
    return _config(await _camera(camera.id))


@router.post("/{camera_id}/backfill/jobs", response_model=BackfillJobOut, status_code=201)
async def create_backfill_job(camera_id: int, body: BackfillJobCreate):
    camera = await _camera(camera_id)
    if camera.backfill_mode == "off" or camera.backfill_capability != "supported":
        raise HTTPException(409, {"code": "backfill_disabled", "message": "Enable tested camera backfill first"})
    if not camera.backfill_recording_token:
        raise HTTPException(409, {"code": "no_recording_match", "message": "No camera recording is selected"})
    start, end = body.start_time, body.end_time
    if end <= start or end - start > MAX_JOB:
        raise HTTPException(422, f"Backfill interval must be positive and at most {MAX_JOB.seconds // 60} minutes")
    if end > utcnow() - RECENT_SAFETY:
        raise HTTPException(422, "Backfill interval must be at least 5 minutes old")
    profile = body.profile or camera.backfill_profile
    if not await CameraStream.exists(camera_id=camera.id, profile=profile, record=True):
        raise HTTPException(409, "Selected Shah-NVR profile is not recorded")
    segments = await find_segments(camera.id, profile, start, end)
    gaps = compute_gaps(segments, start, end)
    if not gaps:
        raise HTTPException(409, {"code": "no_gap", "message": "Shah-NVR already has this interval"})
    # Import only one genuine uncovered interval; the UI can queue other gaps separately.
    gap_start, gap_end = max(gaps, key=lambda pair: (pair[1] - pair[0]).total_seconds())
    duplicate = await BackfillJob.filter(
        camera_id=camera.id, profile=profile, state__in=ACTIVE,
        start_time__lt=gap_end, end_time__gt=gap_start,
    ).first()
    if duplicate:
        return _job(duplicate)
    assignment = await CameraAssignment.get_or_none(camera_id=camera.id)
    if assignment is None or assignment.node_id is None:
        raise HTTPException(409, "Camera is not assigned to a media node")
    job = await BackfillJob.create(
        id=uuid4(), camera_id=camera.id, node_id=assignment.node_id, profile=profile,
        recording_token=camera.backfill_recording_token, start_time=gap_start, end_time=gap_end,
        assignment_generation=assignment.generation,
    )
    return _job(job)


@router.get("/{camera_id}/backfill/jobs", response_model=list[BackfillJobOut])
async def list_backfill_jobs(camera_id: int, limit: int = Query(50, ge=1, le=500)):
    await _camera(camera_id)
    return [_job(j) for j in await BackfillJob.filter(camera_id=camera_id).limit(limit)]


@internal_router.post("/claim", response_model=ClaimedJobOut | None)
async def claim_job(body: ClaimIn):
    if not await MediaNode.exists(id=body.node_id):
        raise HTTPException(404, "Node not found")
    now = utcnow()
    await BackfillJob.filter(node_id=body.node_id, state__in=(BackfillState.CLAIMED, BackfillState.DOWNLOADING,
                              BackfillState.INDEXING), lease_expires_at__lt=now).update(state=BackfillState.QUEUED)
    job = await BackfillJob.filter(node_id=body.node_id, state=BackfillState.QUEUED).order_by("created_at").first()
    if job is None:
        return None
    assignment = await CameraAssignment.get_or_none(camera_id=job.camera_id)
    camera = await Camera.get(id=job.camera_id)
    if assignment is None or assignment.node_id != body.node_id or assignment.generation != job.assignment_generation:
        job.state, job.error_code, job.error_message = BackfillState.FAILED, "assignment_changed", "Camera assignment changed"
        job.finished_at = now
        await job.save()
        return None
    job.state, job.started_at, job.lease_expires_at = BackfillState.CLAIMED, job.started_at or now, now + LEASE
    job.attempt_count += 1
    await job.save()
    host, port = device_target(camera)
    return {
        "id": job.id, "camera_id": camera.id, "profile": job.profile,
        "recording_token": job.recording_token, "start_time": job.start_time, "end_time": job.end_time,
        "assignment_generation": job.assignment_generation, "host": host, "port": port,
        "username": camera.username or "", "password": camera.password or "",
    }


async def _leased(job_id: UUID, node_id: int) -> BackfillJob:
    job = await BackfillJob.get_or_none(id=job_id, node_id=node_id)
    if job is None or job.state not in ACTIVE:
        raise HTTPException(409, "Backfill lease is no longer active")
    return job


@internal_router.post("/{job_id}/progress", status_code=204)
async def job_progress(job_id: UUID, body: JobProgressIn):
    job = await _leased(job_id, body.node_id)
    job.state, job.progress_percent, job.lease_expires_at = BackfillState(body.state), body.progress_percent, utcnow() + LEASE
    await job.save()


@internal_router.post("/{job_id}/complete", status_code=204)
async def job_complete(job_id: UUID, body: JobCompleteIn):
    job = await _leased(job_id, body.node_id)
    job.state = BackfillState.PARTIAL if body.partial else BackfillState.COMPLETED
    job.progress_percent, job.imported_seconds, job.imported_bytes = 100, body.imported_seconds, body.imported_bytes
    job.finished_at, job.lease_expires_at = utcnow(), None
    await job.save()


@internal_router.post("/{job_id}/fail", status_code=204)
async def job_fail(job_id: UUID, body: JobFailIn):
    job = await _leased(job_id, body.node_id)
    job.state, job.error_code, job.error_message = BackfillState.FAILED, body.code, body.message
    job.finished_at, job.lease_expires_at = utcnow(), None
    await job.save()
