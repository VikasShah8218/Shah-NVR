from fastapi import APIRouter, HTTPException, status
from tortoise.transactions import in_transaction

from app.assignments.models import CameraAssignment
from app.cameras.models import Camera, CameraStream, StreamStatus
from app.cameras.schemas import (
    CameraCreate,
    CameraOut,
    CameraUpdate,
    LiveOut,
    LiveStreamUrls,
    StreamIn,
    StreamOut,
    StreamUpdate,
)
from app.cameras.utils import camera_to_out
from app.recordings.models import RecordingSegment
from settings.settings import settings

router = APIRouter(prefix="/api/v1/cameras", tags=["Cameras"])


async def _get_camera(camera_id: int) -> Camera:
    camera = await Camera.get_or_none(id=camera_id)
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    return camera


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
async def create_camera(body: CameraCreate):
    async with in_transaction():
        camera = await Camera.create(
            name=body.name,
            description=body.description,
            username=body.username,
            password=body.password,
            enabled=body.enabled,
            # omitted -> default; explicit null -> keep until storage is full
            retention_days=body.retention_days if "retention_days" in body.model_fields_set
            else settings.DEFAULT_RETENTION_DAYS,
        )
        for s in body.streams:
            await CameraStream.create(camera=camera, **s.model_dump())
    return await camera_to_out(camera)


@router.get("", response_model=list[CameraOut])
async def list_cameras(enabled: bool | None = None):
    qs = Camera.all()
    if enabled is not None:
        qs = qs.filter(enabled=enabled)
    return [await camera_to_out(c) for c in await qs]


@router.get("/{camera_id}", response_model=CameraOut)
async def get_camera(camera_id: int):
    return await camera_to_out(await _get_camera(camera_id))


@router.patch("/{camera_id}", response_model=CameraOut)
async def update_camera(camera_id: int, body: CameraUpdate):
    camera = await _get_camera(camera_id)
    data = body.model_dump(exclude_unset=True)
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
async def get_live(camera_id: int, profile: str | None = None):
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
                rtsp=f"rtsp://{node.media_host}:{node.rtsp_port}/{s.path_name()}",
                hls=f"http://{node.media_host}:{node.hls_port}/{s.path_name()}/index.m3u8",
                webrtc=f"http://{node.media_host}:{node.webrtc_port}/{s.path_name()}",
            )
            for s in streams
        ],
    )
