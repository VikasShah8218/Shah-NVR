from tortoise import fields
from tortoise.models import Model


class KeyValue(Model):
    """Small local key/value store (node id, cached assignments...)."""

    key = fields.CharField(max_length=64, primary_key=True)
    value = fields.JSONField(null=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "key_value"

    @classmethod
    async def get_value(cls, key: str, default=None):
        row = await cls.get_or_none(key=key)
        return row.value if row else default

    @classmethod
    async def set_value(cls, key: str, value) -> None:
        await cls.update_or_create(key=key, defaults={"value": value})
