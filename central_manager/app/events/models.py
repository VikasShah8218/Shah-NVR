from tortoise import fields
from tortoise.models import Model


class Event(Model):
    """Something that happened at a camera (docs/EVENT_RECORDING_PLAN.md): a timeline mark, and in event recording
    mode the reason the node keeps video around it.

    `end_time` None = still going on (closed by an end call, the node, or after EVENT_MAX_SECONDS);
    `end_time == start_time` = a moment. Video is never stored here.
    """

    id = fields.BigIntField(primary_key=True)
    camera = fields.ForeignKeyField("models.Camera", related_name="events", on_delete=fields.CASCADE)
    type = fields.CharField(max_length=32)  # manual | api | video_loss | video_restored | (later) motion, onvif...
    source = fields.CharField(max_length=128)  # user:<name> | api:<name> | node:<name>
    start_time = fields.DatetimeField()
    end_time = fields.DatetimeField(null=True)
    label = fields.CharField(max_length=128, null=True)
    data = fields.JSONField(null=True)
    node_key = fields.CharField(max_length=96, null=True, unique=True)  # node-made events: idempotent re-upload
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "events"
        indexes = (("camera_id", "start_time"), ("start_time",), ("updated_at",))
        ordering = ["start_time"]
