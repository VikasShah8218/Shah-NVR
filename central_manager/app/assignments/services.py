"""Camera scheduler: places every enabled camera on a healthy media node and moves cameras
away from failed, draining or offline nodes. Runs as a background loop in the central manager.

NOTE: run a single central manager instance for now. With several instances this loop needs
leader election (e.g. a PostgreSQL advisory lock) so only one instance schedules at a time.
"""

import asyncio
import logging
from datetime import timedelta

from tortoise.transactions import in_transaction

from app.assignments.models import AssignmentHistory, CameraAssignment
from app.cameras.models import Camera, CameraStream, StreamStatus
from app.nodes.models import SCHEDULABLE_STATES, MediaNode, NodeState
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("central.scheduler")

_lock = asyncio.Lock()
MAX_DISK_USED_PERCENT = 97.0


def _is_eligible(node: MediaNode, load: dict[int, int], now) -> bool:
    if node.state not in SCHEDULABLE_STATES or node.last_heartbeat_at is None:
        return False
    if node.last_heartbeat_at < now - timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS):
        return False
    if load.get(node.id, 0) >= node.capacity_cameras:
        return False
    disk = (node.metrics or {}).get("disk") or {}
    if disk.get("used_percent", 0) >= MAX_DISK_USED_PERCENT:
        return False
    return True


def pick_node(nodes: list[MediaNode], load: dict[int, int], now, exclude: int | None = None) -> MediaNode | None:
    """Least-loaded eligible node (by assigned cameras / capacity)."""
    candidates = [n for n in nodes if n.id != exclude and _is_eligible(n, load, now)]
    if not candidates:
        return None
    return min(candidates, key=lambda n: (load.get(n.id, 0) / n.capacity_cameras, load.get(n.id, 0), n.id))


async def assign_camera(camera_id: int, node: MediaNode | None, reason: str) -> CameraAssignment:
    """Move a camera to `node` (or release it when node is None), bumping the generation."""
    now = utcnow()
    async with in_transaction():
        assignment = await CameraAssignment.filter(camera_id=camera_id).select_for_update().first()
        if assignment is None:
            assignment = await CameraAssignment.create(camera_id=camera_id, generation=0)

        await AssignmentHistory.filter(camera_id=camera_id, ended_at=None).update(ended_at=now)

        assignment.generation += 1
        assignment.node_id = node.id if node else None
        assignment.lease_expires_at = now + timedelta(seconds=settings.LEASE_TTL_SECONDS) if node else None
        assignment.reason = reason
        await assignment.save()

        if node is not None:
            await AssignmentHistory.create(
                camera_id=camera_id, node_id=node.id, generation=assignment.generation, reason=reason, started_at=now
            )
        await CameraStream.filter(camera_id=camera_id).update(
            status=StreamStatus.ASSIGNED if node else StreamStatus.UNASSIGNED,
            status_detail=f"{reason} -> {node.name}" if node else reason,
        )

    logger.info(
        "Camera %s -> %s (generation %s, reason=%s)",
        camera_id, node.name if node else "unassigned", assignment.generation, reason,
    )
    return assignment


async def scheduler_tick() -> None:
    async with _lock:
        now = utcnow()
        grace = timedelta(seconds=settings.FAILOVER_GRACE_SECONDS)
        nodes = await MediaNode.all()
        nodes_by_id = {n.id: n for n in nodes}
        assignments = {a.camera_id: a for a in await CameraAssignment.all()}

        load: dict[int, int] = {}
        for a in assignments.values():
            if a.node_id is not None:
                load[a.node_id] = load.get(a.node_id, 0) + 1

        moves = 0
        no_capacity = 0
        for camera in await Camera.all():
            a = assignments.get(camera.id)
            current = nodes_by_id.get(a.node_id) if a and a.node_id else None

            if not camera.enabled:
                if current is not None:
                    await assign_camera(camera.id, None, "camera_disabled")
                    load[current.id] -= 1
                continue

            reason = None
            if current is None:
                reason = "initial"
            elif current.state in (NodeState.DRAINING, NodeState.OFFLINE):
                reason = f"node_{current.state.value.lower()}"
            elif current.state == NodeState.UNREACHABLE and (
                a.lease_expires_at is None or a.lease_expires_at + grace < now
            ):
                reason = "failover"
            if reason is None:
                continue

            if moves >= settings.MAX_MOVES_PER_CYCLE:
                break
            target = pick_node(nodes, load, now, exclude=current.id if current else None)
            if target is None:
                no_capacity += 1
                continue

            await assign_camera(camera.id, target, reason)
            moves += 1
            load[target.id] = load.get(target.id, 0) + 1
            if current is not None:
                load[current.id] -= 1

        if no_capacity:
            logger.warning("%s camera(s) need a node but no eligible media node has capacity", no_capacity)
