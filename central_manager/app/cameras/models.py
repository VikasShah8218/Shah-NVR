from enum import Enum

from tortoise import fields
from tortoise.models import Model


class StreamStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    CONNECTING = "CONNECTING"
    IDLE = "IDLE"  # live-only stream, connects on demand when someone watches
    STREAMING = "STREAMING"
    RECORDING = "RECORDING"
    NOT_RECORDING = "NOT_RECORDING"
    DISABLED = "DISABLED"


class Camera(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=128)
    description = fields.TextField(null=True)
    username = fields.CharField(max_length=128, null=True)
    password = fields.CharField(max_length=256, null=True)
    enabled = fields.BooleanField(default=True)
    # Whether the owning media node may expose this camera through its H5 virtual ONVIF NVR.
    expose_via_onvif = fields.BooleanField(default=True)
    # Max days of recordings, counted back from the camera's latest recording (app/recordings/services.py).
    # None = keep until storage is full (only space-based cleanup on the node removes recordings).
    retention_days = fields.IntField(default=7, null=True)

    # ONVIF device (H1). Filled when added through discovery or on the first Device-page refresh; all optional,
    # so manually added cameras keep working. Credentials are the camera's username/password above.
    onvif_host = fields.CharField(max_length=255, null=True)
    onvif_port = fields.IntField(null=True)
    manufacturer = fields.CharField(max_length=128, null=True)
    model = fields.CharField(max_length=128, null=True)
    firmware = fields.CharField(max_length=128, null=True)
    serial = fields.CharField(max_length=128, null=True)
    mac = fields.CharField(max_length=32, null=True)
    onvif_services = fields.JSONField(null=True)  # ONVIF service namespaces the device offers
    onvif_reachable = fields.BooleanField(null=True)  # last ONVIF check (no login) answered
    clock_offset_seconds = fields.FloatField(null=True)  # camera clock minus node clock
    onvif_checked_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    streams: fields.ReverseRelation["CameraStream"]

    class Meta:
        table = "cameras"
        ordering = ["id"]


class CameraStream(Model):
    """One video profile of a camera (main / sub / ...), pulled by MediaMTX as one path."""

    id = fields.IntField(primary_key=True)
    camera: fields.ForeignKeyRelation[Camera] = fields.ForeignKeyField(
        "models.Camera", related_name="streams", on_delete=fields.CASCADE
    )
    profile = fields.CharField(max_length=32)
    source_url = fields.CharField(max_length=1024)
    record = fields.BooleanField(default=True)
    rtsp_transport = fields.CharField(max_length=16, default="tcp")
    onvif_profile_token = fields.CharField(max_length=128, null=True)  # ONVIF media profile behind source_url

    # Runtime state reported by the owning media node.
    status = fields.CharEnumField(StreamStatus, max_length=32, default=StreamStatus.UNASSIGNED)
    status_detail = fields.CharField(max_length=512, null=True)
    bytes_received = fields.BigIntField(default=0)
    last_status_at = fields.DatetimeField(null=True)
    last_segment_at = fields.DatetimeField(null=True)

    class Meta:
        table = "camera_streams"
        unique_together = (("camera", "profile"),)
        ordering = ["id"]

    def path_name(self) -> str:
        """MediaMTX path name, shared by live URLs and recording folders."""
        return f"cam-{self.camera_id}/{self.profile}"  # type: ignore[attr-defined]


class EncoderChange(Model):
    """Durable H2 journal and cross-worker device mutex. Contains no credentials or raw XML."""
    id = fields.CharField(max_length=64, primary_key=True)
    camera_id = fields.IntField(db_index=True)
    profile = fields.CharField(max_length=32)
    profile_token = fields.CharField(max_length=128)
    device_key = fields.CharField(max_length=300)
    active_key = fields.CharField(max_length=300, null=True, unique=True)
    node_id = fields.IntField()
    request = fields.JSONField()
    before = fields.JSONField(null=True)
    result = fields.JSONField(null=True)
    status = fields.CharField(max_length=32, default="pending")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "encoder_changes"
        ordering = ["-created_at"]
