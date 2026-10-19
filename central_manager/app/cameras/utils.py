from urllib.parse import quote, urlsplit, urlunsplit

from app.cameras.models import Camera, CameraStream
from app.cameras.schemas import AssignmentInfo, CameraOut, StreamOut


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
    from app.assignments.models import CameraAssignment

    await camera.fetch_related("streams")
    assignment = None
    a = await CameraAssignment.get_or_none(camera_id=camera.id).prefetch_related("node")
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
        retention_days=camera.retention_days,
        **{f: getattr(camera, f) for f in DEVICE_FIELDS},
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
            )
            for s in camera.streams
        ],
        assignment=assignment,
    )
