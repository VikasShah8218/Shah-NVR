"""Storage volumes of a media node: where it may record, in which order, and with which caps.

The central manager owns the configuration (path, order, cap, accepting); the node reports how each
volume is doing (state, space, recordings size) in its heartbeat and receives the configuration back in
the heartbeat response. The node itself decides where to write (fill in order), see
media_node/app/storage/services.py.
"""

from __future__ import annotations

import logging

from app.nodes.models import MediaNode, StorageVolume, VolumeState
from app.nodes.schemas import VolumeConfig, VolumeOut, VolumeReport
from app.nodes.utils import normalize_volume_path
from utilities.common import utcnow

logger = logging.getLogger("central.storage")


def volume_out(v: StorageVolume) -> VolumeOut:
    return VolumeOut(
        id=v.id, path=v.path, kind=v.kind, position=v.position, quota_bytes=v.quota_bytes,
        accepting=v.accepting, is_default=v.is_default, state=v.state, state_detail=v.state_detail,
        total_bytes=v.total_bytes, free_bytes=v.free_bytes, recordings_bytes=v.recordings_bytes,
        writing=v.writing, last_report_at=v.last_report_at,
    )


def volume_config(v: StorageVolume) -> VolumeConfig:
    return VolumeConfig(id=v.id, path=v.path, position=v.position, quota_bytes=v.quota_bytes,
                        accepting=v.accepting, is_default=v.is_default)


async def node_volumes(node_id: int) -> list[StorageVolume]:
    return await StorageVolume.filter(node_id=node_id).order_by("position", "id")


async def ensure_default_volume(node: MediaNode, recordings_dir: str | None) -> None:
    """The node's own RECORDINGS_DIR is always a volume (created on the first heartbeat after the upgrade).

    Its cap is seeded from the old node-wide quota (MediaNode.storage_quota_bytes), so nothing changes for
    existing installations. If the node's RECORDINGS_DIR setting changes, the default volume follows it.
    """
    if not recordings_dir:
        return
    try:
        path = normalize_volume_path(recordings_dir)
    except ValueError:
        path = recordings_dir
    default = await StorageVolume.get_or_none(node_id=node.id, is_default=True)
    if default is None:
        first = await StorageVolume.filter(node_id=node.id).order_by("position").first()
        await StorageVolume.create(
            node_id=node.id, path=path, position=(first.position - 1) if first else 0,
            quota_bytes=node.storage_quota_bytes, accepting=True, is_default=True,
        )
        logger.info("Node %s: default storage volume %s (cap %s)", node.name, path, node.storage_quota_bytes)
    elif default.path != path:
        logger.info("Node %s: default storage volume moved %s -> %s", node.name, default.path, path)
        default.path = path
        default.state = VolumeState.PENDING
        await default.save(update_fields=["path", "state", "updated_at"])


async def apply_reports(node_id: int, reports: list[VolumeReport]) -> None:
    if not reports:
        return
    now = utcnow()
    by_id = {v.id: v for v in await StorageVolume.filter(node_id=node_id, id__in=[r.id for r in reports])}
    for r in reports:
        v = by_id.get(r.id)
        if v is None:
            continue
        if v.state != r.state:
            log = logger.warning if r.state in (VolumeState.UNAVAILABLE, VolumeState.ERROR) else logger.info
            log("Node %s volume %s: %s -> %s %s", node_id, v.path, v.state.value, r.state.value, r.state_detail or "")
        v.state, v.state_detail = r.state, r.state_detail
        v.total_bytes, v.free_bytes, v.recordings_bytes = r.total_bytes, r.free_bytes, r.recordings_bytes
        v.writing, v.last_report_at = r.writing, now
        await v.save(update_fields=["state", "state_detail", "total_bytes", "free_bytes", "recordings_bytes",
                                    "writing", "last_report_at", "updated_at"])


async def renumber(node_id: int, ordered_ids: list[int]) -> None:
    """Positions 0..n-1 in the given order."""
    for position, vid in enumerate(ordered_ids):
        await StorageVolume.filter(node_id=node_id, id=vid).update(position=position)
