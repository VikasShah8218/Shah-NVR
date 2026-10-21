from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "encoder_changes" (
    "id" VARCHAR(64) NOT NULL PRIMARY KEY,
    "camera_id" INT NOT NULL,
    "profile" VARCHAR(32) NOT NULL,
    "profile_token" VARCHAR(128) NOT NULL,
    "device_key" VARCHAR(300) NOT NULL,
    "active_key" VARCHAR(300) UNIQUE,
    "node_id" INT NOT NULL,
    "request" JSONB NOT NULL,
    "before" JSONB,
    "result" JSONB,
    "status" VARCHAR(32) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS "idx_encoder_cha_camera__7d8c49" ON "encoder_changes" ("camera_id");
COMMENT ON TABLE "encoder_changes" IS 'Durable H2 journal and cross-worker device mutex. Contains no credentials or raw XML.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "encoder_changes";"""


MODELS_STATE = (
    "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"
    "/wfi/ruh"
)
