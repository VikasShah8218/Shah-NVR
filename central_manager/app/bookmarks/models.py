from tortoise import fields
from tortoise.models import Model


class Bookmark(Model):
    """An operator's note on a moment (end_time None) or a range of a camera's recordings.

    Video is never stored here: a bookmark only points at a time. `author` is free text until users and
    roles exist (PRIORITY_TASKS section 1); it then becomes a user reference.
    """

    id = fields.IntField(primary_key=True)
    camera = fields.ForeignKeyField("models.Camera", related_name="bookmarks", on_delete=fields.CASCADE)
    profile = fields.CharField(max_length=32, null=True)  # None = the camera, not one stream
    start_time = fields.DatetimeField()
    end_time = fields.DatetimeField(null=True)  # None = a point in time
    note = fields.TextField()
    label = fields.CharField(max_length=64, null=True)
    color = fields.CharField(max_length=16, null=True)
    author = fields.CharField(max_length=128, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "bookmarks"
        indexes = (("camera_id", "start_time"),)
        ordering = ["start_time"]
