from tortoise import fields
from tortoise.models import Model


class LocalSegment(Model):
    """A finished recording chunk on this node's disk, with its byte-level index.

    `parts` = [{"o": byte offset, "s": byte size, "d": duration ms, "k": starts on keyframe}, ...];
    each part is served as one HLS media segment.
    """

    id = fields.UUIDField(primary_key=True)
    camera_id = fields.IntField()
    profile = fields.CharField(max_length=32)
    generation = fields.BigIntField(default=0)
    # Storage volume holding the file: None = this node's RECORDINGS_DIR, otherwise the central volume id.
    # rel_path stays globally unique: it contains the camera and a microsecond timestamp.
    volume_id = fields.IntField(null=True)
    rel_path = fields.CharField(max_length=512, unique=True)  # relative to the volume's folder
    start_time = fields.DatetimeField()
    end_time = fields.DatetimeField()
    duration_ms = fields.IntField()
    size_bytes = fields.BigIntField()
    init_size = fields.IntField()
    codec = fields.CharField(max_length=32, null=True)
    parts = fields.JSONField()
    tracks = fields.JSONField(default=dict)  # {track_id: {"ts": timescale, "t0": first decode time}}
    uploaded = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "local_segments"
        indexes = (("uploaded", "created_at"), ("start_time",))


class SkippedFile(Model):
    """Files that could not be indexed (corrupt/empty), so the scanner does not retry them forever."""

    rel_path = fields.CharField(max_length=512, primary_key=True)
    volume_id = fields.IntField(null=True)
    reason = fields.CharField(max_length=256)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "skipped_files"
