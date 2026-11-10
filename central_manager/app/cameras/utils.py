from collections.abc import Sequence
from urllib.parse import quote, urlsplit, urlunsplit

from app.cameras.models import Camera, CameraStream, StreamStatus
from app.cameras.schemas import AssignmentInfo, CameraOption, CameraOut, StreamOut
from app.groups.services import group_labels


DEVICE_FIELDS = ("onvif_host", "onvif_port", "manufacturer", "model", "firmware", "serial", "mac", "onvif_services",
                 "onvif_reachable", "clock_offset_seconds", "onvif_checked_at")


def build_source_url(stream: CameraStream, camera: Camera) -> str:
    """Inject camera credentials into the stream URL (unless the URL already has them)."""
    parts = urlsplit(stream.source_url)
    if not camera.username or parts.username:
        return stream.source_url
    userinfo = quote(camera.username, safe="")
    if camera.password:
        userinfo += ":" + quote(camera.password, safe="")
    netloc = f"{userinfo}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


async def camera_to_out(camera: Camera) -> CameraOut:
    return (await cameras_to_out([camera]))[0]


async def cameras_to_out(cameras: Sequence[Camera]) -> list[CameraOut]:
    """Convert a page of cameras with 2 queries in total (streams + assignments/nodes), not ~3 per camera."""
    from app.assignments.models import CameraAssignment

    if not cameras:
        return []
    ids = [c.id for c in cameras]
    streams: dict[int, list[CameraStream]] = {i: [] for i in ids}
    for s in await CameraStream.filter(camera_id__in=ids).order_by("id"):
        streams[s.camera_id].append(s)
    assignments = {a.camera_id: a for a in await CameraAssignment.filter(camera_id__in=ids).prefetch_related("node")}
    labels = await group_labels(c.group_id for c in cameras)
    return [_camera_out(c, streams[c.id], assignments.get(c.id), labels) for c in cameras]


async def camera_options_out(cameras: Sequence[Camera]) -> list[CameraOption]:
    """Picker rows for a page of cameras: 2 small queries (profiles + node ids)."""
    from app.assignments.models import CameraAssignment

    if not cameras:
        return []
    ids = [c.id for c in cameras]
    profiles: dict[int, list[str]] = {i: [] for i in ids}
    status: dict[int, StreamStatus] = {}
    recording: set[int] = set()  # cameras whose status already comes from a recording stream
    for camera_id, profile, record, stream_status in await CameraStream.filter(camera_id__in=ids).order_by(
            "id").values_list("camera_id", "profile", "record", "status"):
        profiles[camera_id].append(profile)
        if camera_id not in status or (record and camera_id not in recording):
            status[camera_id] = stream_status
        if record:
            recording.add(camera_id)
    nodes = dict(await CameraAssignment.filter(camera_id__in=ids).values_list("camera_id", "node_id"))
    labels = await group_labels(c.group_id for c in cameras)
    return [CameraOption(id=c.id, name=c.name, enabled=c.enabled, has_ptz=c.has_ptz, profiles=profiles[c.id],
                         status=status.get(c.id, StreamStatus.UNKNOWN) if c.enabled else StreamStatus.DISABLED,
                         node_id=nodes.get(c.id), group_id=c.group_id, group_path=labels.get(c.group_id))
            for c in cameras]


def _camera_out(camera: Camera, streams: list[CameraStream], a, labels: dict[int, str]) -> CameraOut:
    assignment = None
    if a is not None:
        node = a.node
        assignment = AssignmentInfo(
            node_id=node.id if node else None,
            node_name=node.name if node else None,
            generation=a.generation,
            lease_expires_at=a.lease_expires_at,
        )
    return CameraOut(
        id=camera.id,
        name=camera.name,
        description=camera.description,
        username=camera.username,
        has_password=bool(camera.password),
        enabled=camera.enabled,
        expose_via_onvif=camera.expose_via_onvif,
        has_ptz=camera.has_ptz,
        retention_days=camera.retention_days,
        **{f: getattr(camera, f) for f in DEVICE_FIELDS},
        group_id=camera.group_id,
        group_path=labels.get(camera.group_id),
        created_at=camera.created_at,
        updated_at=camera.updated_at,
        streams=[
            StreamOut(
                id=s.id,
                profile=s.profile,
                source_url=s.source_url,
                record=s.record,
                rtsp_transport=s.rtsp_transport,
                status=s.status,
                status_detail=s.status_detail,
                bytes_received=s.bytes_received,
                last_status_at=s.last_status_at,
                last_segment_at=s.last_segment_at,
                onvif_profile_token=s.onvif_profile_token,
                audio_state=s.audio_state,
                audio_advertised=s.audio_advertised,
                audio_observed=s.audio_observed,
                audio_codec=s.audio_codec,
                audio_codec_raw=s.audio_codec_raw,
                audio_sample_rate=s.audio_sample_rate,
                audio_channels=s.audio_channels,
                audio_bitrate_kbps=s.audio_bitrate_kbps,
                audio_last_observed_at=s.audio_last_observed_at,
            )
            for s in streams
        ],
        assignment=assignment,
    )
