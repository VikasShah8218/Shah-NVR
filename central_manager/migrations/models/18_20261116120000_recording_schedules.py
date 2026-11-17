from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True

# Recording schedules (docs/RECORDING_SCHEDULES_PLAN.md). Hand-written like 13-17.
# Additive: existing cameras get recording_mode 'always' = exactly today's behaviour.
# A schedule in use cannot be deleted (FK RESTRICT; the API answers 409 first).


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "recording_schedules" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "name" VARCHAR(64) NOT NULL UNIQUE,
    "description" TEXT,
    "blocks" JSONB NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
COMMENT ON TABLE "recording_schedules" IS 'A named weekly recording plan, shared by many cameras.';
ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "recording_mode" VARCHAR(16) NOT NULL DEFAULT 'always';
ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "recording_schedule_id" INT
    REFERENCES "recording_schedules" ("id") ON DELETE RESTRICT;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "recording_schedule_id";
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "recording_mode";
        UPDATE "camera_streams" SET "status" = 'UNKNOWN' WHERE "status" = 'SCHEDULED_OFF';
        DROP TABLE IF EXISTS "recording_schedules";"""


MODELS_STATE = ""
