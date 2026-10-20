from enum import Enum

from tortoise import fields
from tortoise.models import Model

from app.nodes.utils import is_network_path


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
    # Optional browser-facing endpoints.  The node continues to use api_url/media_host for
    # central-to-node traffic; these are only used in URLs returned to remote clients.
    public_enabled = fields.BooleanField(default=False)
    public_api_url = fields.CharField(max_length=256, null=True)
    public_media_host = fields.CharField(max_length=256, null=True)
    public_rtsp_port = fields.IntField(null=True)
    public_hls_port = fields.IntField(null=True)
    public_webrtc_port = fields.IntField(null=True)
    public_media_tls = fields.BooleanField(default=False)
    capacity_cameras = fields.IntField(default=100)
    # Deprecated: the cap now lives on each StorageVolume. Kept only to seed the node's default volume
    # (first heartbeat after the upgrade) and for old clients; drop in a later migration.
    storage_quota_bytes = fields.BigIntField(null=True)
    version = fields.CharField(max_length=64, null=True)
    mediamtx_version = fields.CharField(max_length=64, null=True)
    # H5 desired state. Credentials remain node-local and are never stored in central.
    onvif_server_enabled = fields.BooleanField(default=False)
    onvif_server_name = fields.CharField(max_length=128, default="Shah-NVR")
    onvif_server_location = fields.CharField(max_length=256, null=True)
    state = fields.CharEnumField(NodeState, max_length=16, default=NodeState.READY)
    last_heartbeat_at = fields.DatetimeField(null=True)
    metrics = fields.JSONField(null=True)
    registered_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "media_nodes"
        ordering = ["id"]

    @property
    def client_api_url(self) -> str:
        return self.public_api_url if self.public_enabled and self.public_api_url else self.api_url

    @property
    def client_media_host(self) -> str:
        return self.public_media_host if self.public_enabled and self.public_media_host else self.media_host

    @property
    def client_rtsp_port(self) -> int:
        return self.public_rtsp_port if self.public_enabled and self.public_rtsp_port else self.rtsp_port

    @property
    def client_hls_port(self) -> int:
        return self.public_hls_port if self.public_enabled and self.public_hls_port else self.hls_port

    @property
    def client_webrtc_port(self) -> int:
        return self.public_webrtc_port if self.public_enabled and self.public_webrtc_port else self.webrtc_port

    @property
    def client_media_scheme(self) -> str:
        return "https" if self.public_enabled and self.public_media_tls else "http"


class VolumeState(str, Enum):
    PENDING = "PENDING"  # added in central; the node has not reported on it yet
    OK = "OK"  # reachable and writable
    FULL = "FULL"  # reached its cap (or its disk is nearly full): recording moved to the next volume
    UNAVAILABLE = "UNAVAILABLE"  # path missing / network share offline
    ERROR = "ERROR"  # reachable but unusable (e.g. access denied); see state_detail


class StorageVolume(Model):
    """A place where a media node may store recordings: a folder on a local drive or a network share.

    Fill in order: the node records to the first volume (lowest `position`) that is accepting, OK and
    not FULL, and only overwrites the oldest recordings once every volume is full. Network share
    credentials are never stored here; they are saved on the node PC (Windows Credential Manager).
    """

    id = fields.IntField(primary_key=True)
    node = fields.ForeignKeyField("models.MediaNode", related_name="volumes", on_delete=fields.CASCADE)
    path = fields.CharField(max_length=400)  # e.g. D:\ShahNVR\recordings or \\192.168.1.9\nvr
    position = fields.IntField(default=0)  # fill order, lowest first
    quota_bytes = fields.BigIntField(null=True)  # max bytes of recordings here (None = whole disk)
    accepting = fields.BooleanField(default=True)  # False = no new recordings; existing stay playable
    is_default = fields.BooleanField(default=False)  # the node's own RECORDINGS_DIR (cannot be removed)
    # reported by the node (heartbeat)
    state = fields.CharEnumField(VolumeState, max_length=16, default=VolumeState.PENDING)
    state_detail = fields.CharField(max_length=256, null=True)
    total_bytes = fields.BigIntField(null=True)
    free_bytes = fields.BigIntField(null=True)
    recordings_bytes = fields.BigIntField(null=True)
    writing = fields.BooleanField(default=False)  # the node records new chunks here right now
    last_report_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "storage_volumes"
        unique_together = (("node", "path"),)
        ordering = ["node_id", "position", "id"]

    @property
    def kind(self) -> str:
        return "network" if is_network_path(self.path) else "local"
