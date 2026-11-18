from tortoise import fields
from tortoise.models import Model


class EventWindow(Model):
    """An event of one of this node's cameras (docs/EVENT_RECORDING_PLAN.md E3, §5.4).

    Held chunks (event mode) overlapping [start - pre, end + post] are kept. Events come from central (manual / API:
    pushed, or found by the catch-up poll; key "c<central id>") or are made here (video loss; ONVIF later), then
    uploaded to central. `end_time` None = still going on (counted up to now, at most `max` seconds);
    end == start = a moment.
    """

    id = fields.IntField(primary_key=True)
    key = fields.CharField(max_length=96, unique=True)
    camera_id = fields.IntField()
    type = fields.CharField(max_length=32)
    start_time = fields.DatetimeField()
    end_time = fields.DatetimeField(null=True)
    label = fields.CharField(max_length=128, null=True)
    data = fields.JSONField(null=True)
    central_id = fields.BigIntField(null=True)
    node_made = fields.BooleanField(default=False)
    uploaded = fields.BooleanField(default=True)  # node-made events with marking on start as False
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "event_windows"
        indexes = (("camera_id", "start_time"), ("uploaded",))
