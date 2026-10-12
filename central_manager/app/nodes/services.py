import logging
from datetime import timedelta

from app.cameras.models import CameraStream, StreamStatus
from app.nodes.models import MediaNode, NodeState
from settings.settings import settings
from utilities.common import utcnow

logger = logging.getLogger("central.health")


async def node_health_tick() -> None:
    """Mark nodes UNREACHABLE when heartbeats stop; mark stale stream states UNKNOWN."""
    now = utcnow()
    cutoff = now - timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS)

    stale_nodes = await MediaNode.filter(
        state__in=[NodeState.READY, NodeState.ACTIVE, NodeState.DRAINING, NodeState.CORDONED],
        last_heartbeat_at__lt=cutoff,
    )
    for node in stale_nodes:
        logger.warning("Node %s (%s) missed heartbeats -> UNREACHABLE", node.id, node.name)
        node.state = NodeState.UNREACHABLE
        await node.save(update_fields=["state", "updated_at"])

    status_cutoff = now - timedelta(seconds=settings.STREAM_STATUS_STALE_SECONDS)
    await CameraStream.filter(
        last_status_at__lt=status_cutoff,
        status__in=[StreamStatus.CONNECTING, StreamStatus.STREAMING, StreamStatus.RECORDING, StreamStatus.NOT_RECORDING],
    ).update(status=StreamStatus.UNKNOWN, status_detail="No status report from the owning node")
