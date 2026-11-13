from tortoise import fields
from tortoise.models import Model


class AccessGrant(Model):
    """Which cameras a role or a user may see (docs/AUTH_INTEGRATION_PLAN.md §6).

    The Auth Server says *what* a user may do (permission numbers in the token); Shah-NVR says *which cameras*:
    a grant gives a whole camera group (with every sub-group), one camera, or all cameras. A user sees the union
    of their own grants and their roles' grants. Admins (`*`) see everything without grants.
    """

    id = fields.IntField(primary_key=True)
    subject_type = fields.CharField(max_length=8)  # "role" | "user"
    subject = fields.CharField(max_length=128)  # legacy: role name / user id; oidc: role id / user sub (UUIDs)
    # which Auth Server the subject belongs to (legacy | oidc): ids of the two never match, so a grant only
    # counts while its server is the active AUTH_PROVIDER (docs/AUTH_V2_PLAN.md)
    auth_source = fields.CharField(max_length=8, default="legacy")
    all_cameras = fields.BooleanField(default=False)
    group = fields.ForeignKeyField("models.CameraGroup", related_name="grants", null=True, on_delete=fields.CASCADE)
    camera = fields.ForeignKeyField("models.Camera", related_name="grants", null=True, on_delete=fields.CASCADE)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "access_grants"
        indexes = (("auth_source", "subject_type", "subject"),)
        ordering = ["id"]
