import asyncio
import logging
import shutil
from datetime import timedelta

from app.node import metrics
from app.node.models import KeyValue
from app.node.utils import CentralError, central, runtime
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("node.agent")

KV_NODE_ID = "node_id"
KV_ASSIGNMENTS = "assignments"
VERSION = "0.1.0"


async def load_local_state() -> None:
    """Restore node id and last known assignments, so recording continues if central is down."""
    runtime.node_id = await KeyValue.get_value(KV_NODE_ID)
    cached = await KeyValue.get_value(KV_ASSIGNMENTS, {}) or {}
    runtime.assignments = {int(k): v for k, v in cached.items()}
    logger.info("Local state: node_id=%s, cached cameras=%s", runtime.node_id, len(runtime.assignments))


async def register() -> bool:
    payload = {
        "name": settings.NODE_NAME,
        "api_url": settings.api_url,
        "media_host": settings.PUBLIC_HOST,
        "rtsp_port": settings.RTSP_PORT,
        "hls_port": settings.HLS_PORT,
        "webrtc_port": settings.WEBRTC_PORT,
        "capacity_cameras": settings.CAPACITY_CAMERAS,
        "version": VERSION,
        "mediamtx_version": runtime.mediamtx_version,
    }
    try:
        data = await central.register(payload)
    except CentralError as exc:
        logger.warning("Registration failed: %s", exc)
        return False
    runtime.node_id = data["node_id"]
    await KeyValue.set_value(KV_NODE_ID, runtime.node_id)
    logger.info("Registered with central as node_id=%s (state=%s)", runtime.node_id, data["state"])
    return True


def disk_info() -> dict:
    """The disk of the node's default folder (RECORDINGS_DIR); per-volume figures are in `volumes`."""
    usage = shutil.disk_usage(settings.RECORDINGS_DIR)
    return {
        "path": str(settings.RECORDINGS_DIR),
        "total_bytes": usage.total,
        "free_bytes": usage.free,
        "used_percent": round(100 * usage.used / usage.total, 2),
    }


async def heartbeat_tick() -> None:
    from app.recordings.models import LocalSegment
    from app.recordings.services import recordings_used_bytes
    from app.storage.services import local_drives, storage

    if runtime.node_id is None and not await register():
        return
    payload = {
        **metrics.cpu_memory(),
        **metrics.network_rates(),
        "gpus": await metrics.gpus(),
        "disk": disk_info(),
        "recordings_bytes": await recordings_used_bytes(),
        "mediamtx_running": runtime.mediamtx_running,
        "paths_configured": sum(len(c["streams"]) for c in runtime.assignments.values()),
        "paths_ready": len(runtime.ready_since),
        "pending_uploads": await LocalSegment.filter(uploaded=False).count(),
        "default_recordings_dir": str(settings.RECORDINGS_DIR),
        "drives": await asyncio.to_thread(local_drives),
        "volumes": storage.reports(),
    }
    try:
        data = await central.heartbeat(runtime.node_id, payload)
        runtime.last_central_contact = utcnow()
        await storage.apply_config(data.get("volumes"), data.get("storage_quota_bytes"))
    except CentralError as exc:
        if exc.status_code == 404:  # central lost us (e.g. DB reset): register again
            logger.warning("Central does not know node_id=%s; re-registering", runtime.node_id)
            runtime.node_id = None
        else:
            logger.warning("Heartbeat failed: %s", exc)


async def refresh_assignments() -> None:
    """Fetch desired cameras from central. On failure keep the cached set (keep recording)."""
    if runtime.node_id is None:
        return
    try:
        data = await central.assignments(runtime.node_id)
    except CentralError as exc:
        logger.debug("Assignments fetch failed, using cached set: %s", exc)
        return
    new = {c["camera_id"]: c for c in data["cameras"]}
    if new != runtime.assignments:
        added = new.keys() - runtime.assignments.keys()
        removed = runtime.assignments.keys() - new.keys()
        logger.info("Assignments changed: +%s -%s (total %s)", sorted(added), sorted(removed), len(new))
        runtime.assignments = new
        await KeyValue.set_value(KV_ASSIGNMENTS, {str(k): v for k, v in new.items()})


async def stream_status_tick() -> None:
    """Report per-stream state: CONNECTING / STREAMING / RECORDING / NOT_RECORDING."""
    from app.mediamtx.utils import mtx

    if runtime.node_id is None or not runtime.assignments:
        return
    now = utcnow()
    try:
        live = await mtx.list_runtime_paths()
    except Exception:
        live = {}

    seg = timedelta(seconds=settings.SEGMENT_SECONDS)
    slack = timedelta(seconds=30)
    items = []
    for cam in runtime.assignments.values():
        for s in cam["streams"]:
            name = s["path_name"]
            info = live.get(name) or {}
            ready = bool(info.get("ready"))
            if ready:
                runtime.ready_since.setdefault(name, now)
            else:
                runtime.ready_since.pop(name, None)

            tracks = info.get("tracks") or []
            detail = ", ".join(t if isinstance(t, str) else str(t.get("codec", t)) for t in tracks) or None
            if not runtime.mediamtx_running:
                status, detail = "CONNECTING", "media engine down"
            elif not ready and not s["record"]:
                status, detail = "IDLE", "on-demand: connects when a viewer opens it"
            elif not ready:
                status, detail = "CONNECTING", "waiting for camera"
            elif not s["record"]:
                status = "STREAMING"
            else:
                last_end = runtime.last_segment_end.get((cam["camera_id"], s["profile"]))
                ready_for = now - runtime.ready_since[name]
                if (last_end and now - last_end < 2 * seg + slack) or ready_for < seg * 1.5 + slack:
                    status = "RECORDING"
                else:
                    status = "NOT_RECORDING"
                    detail = "stream is up but no chunks are being finalized (disk?)"
            items.append({
                "camera_id": cam["camera_id"],
                "profile": s["profile"],
                "status": status,
                "detail": detail,
                "bytes_received": int(info.get("bytesReceived") or 0),
            })
    try:
        await central.stream_status(runtime.node_id, items)
    except CentralError as exc:
        logger.debug("Stream status report failed: %s", exc)
