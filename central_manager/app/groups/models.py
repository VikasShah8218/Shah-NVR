from tortoise import fields
from tortoise.models import Model


class CameraGroup(Model):
    """A folder in the camera tree (docs/GROUPING_PLAN.md). Groups nest; a camera sits in one group or none.

    `path` is the materialised path of ids from the top, ending with the group's own id: "/3/17/42/". Every subtree
    question is then one prefix query (`path__startswith`), because Tortoise has no recursive queries.
    In PostgreSQL the path index uses `varchar_pattern_ops` (migration 15) so `LIKE '/3/%'` can use it.
    """

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=128)
    description = fields.TextField(null=True)
    parent: fields.ForeignKeyNullableRelation["CameraGroup"] = fields.ForeignKeyField(
        "models.CameraGroup", related_name="children", null=True, on_delete=fields.RESTRICT
    )
    path = fields.CharField(max_length=255, default="")
    depth = fields.IntField(default=0)  # 0 = top level
    sort_order = fields.IntField(default=0)  # kept for drag ordering later; v1 orders by name
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    children: fields.ReverseRelation["CameraGroup"]

    class Meta:
        table = "camera_groups"
        indexes = (("parent_id", "name"),)  # children of a group, by name
        ordering = ["id"]

    def ancestor_ids(self) -> list[int]:
        """Ids from the top group down to the parent (not the group itself)."""
        return path_ids(self.path)[:-1]


def path_ids(path: str) -> list[int]:
    return [int(p) for p in path.strip("/").split("/") if p]
