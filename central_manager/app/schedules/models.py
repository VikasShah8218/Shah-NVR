from tortoise import fields
from tortoise.models import Model


class RecordingSchedule(Model):
    """A named weekly recording plan, shared by many cameras (docs/RECORDING_SCHEDULES_PLAN.md).

    `blocks`: [{"days": [0-6], "start": "HH:MM", "end": "HH:MM", "mode": "continuous" | "off"}], Mon=0, in the
    site's wall clock (settings.SITE_TIMEZONE). Evaluated by app/schedules/utils.py (also copied to the node).
    """

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=64, unique=True)
    description = fields.TextField(null=True)
    blocks = fields.JSONField(default=list)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "recording_schedules"
        ordering = ["name", "id"]
