from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "media_nodes" ADD "storage_quota_bytes" BIGINT;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "media_nodes" DROP COLUMN "storage_quota_bytes";"""


MODELS_STATE = (
    "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"
)
