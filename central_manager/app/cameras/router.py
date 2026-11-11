from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from tortoise.expressions import Q, Subquery

from app.assignments.models import CameraAssignment
from app.cameras.models import Camera, CameraStream, StreamStatus
from app.cameras.schemas import (
    CameraCreate,
    CameraOption,
    CameraOut,
    CameraUpdate,
    LiveOut,
    LiveStreamUrls,
    StreamIn,
    StreamOut,
    StreamUpdate,
)
from app.cameras.services import create_camera_with_streams
from app.cameras.utils import camera_options_out, camera_to_out, cameras_to_out
from app.auth import scope as access
from app.groups.services import camera_scope, check_group_id
from app.recordings.models import RecordingSegment
from settings.settings import settings
from utilities.pagination import MAX_LIMIT, Page, PageParams, paginate

router = APIRouter(prefix="/api/v1/cameras", tags=["Cameras"])


async def _get_camera(camera_id: int) -> Camera:
    camera = await Camera.get_or_none(id=camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    return camera


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
async def create_camera(body: CameraCreate):
    await check_group_id(body.group_id)
    camera = await create_camera_with_streams(
        {
            "name": body.name,
            "description": body.description,
            "username": body.username,
            "password": body.password,
            "enabled": body.enabled,
            "has_ptz": body.has_ptz,
            "group_id": body.group_id,
            # omitted -> default; explicit null -> keep until storage is full
            "retention_days": body.retention_days if "retention_days" in body.model_fields_set
            else settings.DEFAULT_RETENTION_DAYS,
        },
        [s.model_dump() for s in body.streams],
    )
    return await camera_to_out(camera)


def _parse_ids(ids: str | None) -> list[int] | None:
    if ids is None:
        return None
    try:
        out = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "ids must be a comma-separated list of numbers")
    if len(out) > MAX_LIMIT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"At most {MAX_LIMIT} ids")
    return out


def _camera_query(q: str | None, enabled: bool | None, node_id: int | None, stream_status: StreamStatus | None,
                  ids: list[int] | None, sort: str, scope: Q | None = None):
    """Shared filters of the camera list and the picker list. Ordered on a unique key so pages are stable."""
    qs = Camera.all() if scope is None else Camera.filter(scope)
    if ids is not None:
        qs = qs.filter(id__in=ids)
    if enabled is not None:
        qs = qs.filter(enabled=enabled)
    if q and q.strip():
        term = q.strip()
        qs = qs.filter(Q(name__icontains=term) | Q(id=int(term))) if term.isdigit() else qs.filter(name__icontains=term)
    if node_id is not None:
        qs = qs.filter(id__in=Subquery(CameraAssignment.filter(node_id=node_id).values("camera_id")))
    if stream_status is not None:
        qs = qs.filter(id__in=Subquery(CameraStream.filter(status=stream_status).values("camera_id")))
    return qs.order_by(*(("id",) if sort == "id" else ("name", "id")))


@router.get("", response_model=Page[CameraOut], summary="List / search cameras (paged)")
async def list_cameras(
    page: PageParams = Depends(),
    q: str | None = Query(default=None, max_length=128, description="Name contains, or the exact camera id"),
    enabled: bool | None = None,
    node_id: int | None = Query(default=None, description="Cameras assigned to this media node"),
    stream_status: StreamStatus | None = Query(default=None, alias="status", description="Any stream in this state"),
    ids: str | None = Query(default=None, description="Only these ids, comma-separated (max 200)"),
    sort: Literal["name", "id"] = "name",
    group_id: int | None = Query(default=None, description="Cameras directly in this group"),
    ungrouped: bool = Query(default=False, description="Only cameras in no group"),
    recursive: bool = Query(default=False, description="With group_id: also every sub-group's cameras"),
):
    scope = await camera_scope(group_id, ungrouped, recursive)
    qs = _camera_query(q, enabled, node_id, stream_status, _parse_ids(ids), sort, scope)
    if (visible := await access.camera_q()) is not None:
        qs = qs.filter(visible)
    return await paginate(qs, page, cameras_to_out)


@router.get("/options", response_model=Page[CameraOption], summary="Small camera list for pickers (paged)")
async def camera_options(
    page: PageParams = Depends(),
    q: str | None = Query(default=None, max_length=128),
    enabled: bool | None = None,
    node_id: int | None = None,
    ids: str | None = None,
    group_id: int | None = Query(default=None, description="Cameras directly in this group"),
    ungrouped: bool = Query(default=False, description="Only cameras in no group"),
    recursive: bool = Query(default=False, description="With group_id: also every sub-group's cameras"),
):
    """`id`, `name` and what a picker or a live tile needs, without the full camera (streams, ONVIF details)."""
    scope = await camera_scope(group_id, ungrouped, recursive)
    qs = _camera_query(q, enabled, node_id, None, _parse_ids(ids), "name", scope)
    if (visible := await access.camera_q()) is not None:
        qs = qs.filter(visible)
    return await paginate(qs, page, camera_options_out)


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(camera_id: int):
    return await camera_to_out(await _get_camera(camera_id))


@router.patch("/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: int, body: CameraUpdate):
    camera = await _get_camera(camera_id)
    data = body.model_dump(exclude_unset=True)
    if "group_id" in data:
        await check_group_id(data["group_id"])
    if data:
        await camera.update_from_dict(data).save()
        if data.get("enabled") is False:
            await CameraStream.filter(camera_id=camera.id).update(status=StreamStatus.DISABLED)
    return await camera_to_out(camera)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(camera_id: int):
    camera = await _get_camera(camera_id)
    if await RecordingSegment.filter(camera_id=camera.id).exists():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Camera has recordings. Disable it instead (PATCH enabled=false); its recordings stay until "
            "their retention or storage space removes them.",
        )
    await camera.delete()


# ---------------------------------------------------------------- streams


@router.post("/{camera_id}/streams", response_model=StreamOut, status_code=status.HTTP_201_CREATED)
async def add_stream(camera_id: int, body: StreamIn):
    camera = await _get_camera(camera_id)
    if await CameraStream.filter(camera_id=camera.id, profile=body.profile).exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "Profile already exists for this camera")
    stream = await CameraStream.create(camera=camera, **body.model_dump())
    return StreamOut.model_validate(stream, from_attributes=True)


@router.patch("/{camera_id}/streams/{profile}", response_model=StreamOut)
async def update_stream(camera_id: int, profile: str, body: StreamUpdate):
    stream = await CameraStream.get_or_none(camera_id=camera_id, profile=profile)
    if stream is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stream not found")
    data = body.model_dump(exclude_unset=True)
    if data:
        await stream.update_from_dict(data).save()
    return StreamOut.model_validate(stream, from_attributes=True)


@router.delete("/{camera_id}/streams/{profile}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stream(camera_id: int, profile: str):
    stream = await CameraStream.get_or_none(camera_id=camera_id, profile=profile)
    if stream is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stream not found")
    if await CameraStream.filter(camera_id=camera_id).count() <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A camera must keep at least one stream")
    await stream.delete()


# ---------------------------------------------------------------- live


@router.get("/{camera_id}/live", response_model=LiveOut)
async def get_live(
    camera_id: int,
    profile: str | None = None,
    access: Literal["lan", "public"] = "lan",
):
    """Where to watch this camera live. Video comes from the media node, never from here."""
    camera = await _get_camera(camera_id)
    if not camera.enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Camera is disabled")
    assignment = await CameraAssignment.get_or_none(camera_id=camera.id).prefetch_related("node")
    if assignment is None or assignment.node is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Camera is not assigned to any media node yet")
    node = assignment.node

    streams = await CameraStream.filter(camera_id=camera.id)
    if profile:
        streams = [s for s in streams if s.profile == profile]
        if not streams:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Stream profile not found")

    return LiveOut(
        camera_id=camera.id,
        node_id=node.id,
        node_name=node.name,
        generation=assignment.generation,
        streams=[
            LiveStreamUrls(
                profile=s.profile,
                rtsp=f"rtsp://{node.media_host_for(access)}:{node.rtsp_port_for(access)}/{s.path_name()}",
                hls=(f"{node.media_scheme_for(access)}://{node.media_host_for(access)}:"
                     f"{node.hls_port_for(access)}/{s.path_name()}/index.m3u8"),
                webrtc=(f"{node.media_scheme_for(access)}://{node.media_host_for(access)}:"
                        f"{node.webrtc_port_for(access)}/{s.path_name()}"),
                audio_state=s.audio_state,
                audio_codec=s.audio_codec,
                audio_sample_rate=s.audio_sample_rate,
                audio_channels=s.audio_channels,
            )
            for s in streams
        ],
    )
