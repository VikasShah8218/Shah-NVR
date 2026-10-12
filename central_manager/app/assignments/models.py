from tortoise import fields
from tortoise.models import Model


class CameraAssignment(Model):
    """Which media node owns (pulls + records) a camera. One row per camera, kept forever
    so `generation` keeps increasing across moves."""

    id = fields.IntField(primary_key=True)
    camera = fields.OneToOneField("models.Camera", related_name="assignment", on_delete=fields.CASCADE)
    node = fields.ForeignKeyField(
        "models.MediaNode", related_name="assignments", null=True, on_delete=fields.SET_NULL
    )
    generation = fields.BigIntField(default=0)
    lease_expires_at = fields.DatetimeField(null=True)
    reason = fields.CharField(max_length=64, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "camera_assignments"


class AssignmentHistory(Model):
    id = fields.IntField(primary_key=True)
    camera = fields.ForeignKeyField("models.Camera", related_name="assignment_history", on_delete=fields.CASCADE)
    node = fields.ForeignKeyField(
        "models.MediaNode", related_name="assignment_history", null=True, on_delete=fields.SET_NULL
    )
    generation = fields.BigIntField()
    reason = fields.CharField(max_length=64)
    started_at = fields.DatetimeField()
    ended_at = fields.DatetimeField(null=True)

    class Meta:
        table = "assignment_history"
        ordering = ["-started_at"]
