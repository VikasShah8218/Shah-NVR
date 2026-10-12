from enum import Enum

from tortoise import fields
from tortoise.models import Model


class NodeState(str, Enum):
    READY = "READY"  # healthy, no cameras yet
    ACTIVE = "ACTIVE"  # healthy, running cameras
    DRAINING = "DRAINING"  # admin: move all cameras away
    CORDONED = "CORDONED"  # admin: keep cameras, accept no new ones
    UNREACHABLE = "UNREACHABLE"  # missed heartbeats
    OFFLINE = "OFFLINE"  # admin: disabled


# Nodes in these states may receive new cameras.
SCHEDULABLE_STATES = (NodeState.READY, NodeState.ACTIVE)


class MediaNode(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=64, unique=True)
    api_url = fields.CharField(max_length=256)  # node HTTP API (recorded media is served from here)
    media_host = fields.CharField(max_length=256)  # host/IP clients use for RTSP/HLS/WebRTC
    rtsp_port = fields.IntField(default=8554)
    hls_port = fields.IntField(default=8888)
    webrtc_port = fields.IntField(default=8889)
    capacity_cameras = fields.IntField(default=100)
    # Max bytes this node may use for recordings (None = limited only by the disk). Enforced on the node.
    storage_quota_bytes = fields.BigIntField(null=True)
    version = fields.CharField(max_length=64, null=True)
    mediamtx_version = fields.CharField(max_length=64, null=True)
    state = fields.CharEnumField(NodeState, max_length=16, default=NodeState.READY)
    last_heartbeat_at = fields.DatetimeField(null=True)
    metrics = fields.JSONField(null=True)
    registered_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "media_nodes"
        ordering = ["id"]
