from tortoise import fields
from tortoise.models import Model


class AuditEvent(Model):
    """Who did what, when (docs/AUTH_INTEGRATION_PLAN.md §7.7): sign-ins, live / playback opens, exports, PTZ,
    and every change. Written by the request guard (app/auth/deps.py) and the auth router."""

    id = fields.BigIntField(primary_key=True)
    at = fields.DatetimeField(auto_now_add=True, db_index=True)
    # text: "12" from the old Auth Server, a UUID from the new one; auth_source says which (legacy | oidc)
    user_id = fields.CharField(max_length=64, null=True)
    auth_source = fields.CharField(max_length=8, null=True)
    username = fields.CharField(max_length=128)
    action = fields.CharField(max_length=64, db_index=True)  # e.g. live.open, camera.update, auth.login
    method = fields.CharField(max_length=8, null=True)
    path = fields.CharField(max_length=512)
    camera_id = fields.IntField(null=True, db_index=True)
    status = fields.CharField(max_length=16, default="ok")  # ok | denied | failed
    detail = fields.JSONField(null=True)
    ip = fields.CharField(max_length=64, null=True)

    class Meta:
        table = "audit_events"
        ordering = ["-at", "-id"]
