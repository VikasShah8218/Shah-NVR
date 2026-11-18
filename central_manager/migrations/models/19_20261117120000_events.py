from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True

# Event recording + event marks (docs/EVENT_RECORDING_PLAN.md). Hand-written like 13-18.
# Additive: existing cameras keep recording as before (mode unchanged) and get event marks on.


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "events" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "type" VARCHAR(32) NOT NULL,
    "source" VARCHAR(128) NOT NULL,
    "start_time" TIMESTAMPTZ NOT NULL,
    "end_time" TIMESTAMPTZ,
    "label" VARCHAR(128),
    "data" JSONB,
    "node_key" VARCHAR(96) UNIQUE,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "camera_id" INT NOT NULL REFERENCES "cameras" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_events_camera__start" ON "events" ("camera_id", "start_time");
CREATE INDEX IF NOT EXISTS "idx_events_start" ON "events" ("start_time");
CREATE INDEX IF NOT EXISTS "idx_events_updated" ON "events" ("updated_at");
COMMENT ON TABLE "events" IS 'Something that happened at a camera: a timeline mark and the trigger of event recording.';
ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "event_pre_seconds" INT NOT NULL DEFAULT 10;
ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "event_post_seconds" INT NOT NULL DEFAULT 30;
ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "event_marking" BOOL NOT NULL DEFAULT True;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "event_marking";
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "event_post_seconds";
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "event_pre_seconds";
        UPDATE "cameras" SET "recording_mode" = 'always' WHERE "recording_mode" = 'event';
        UPDATE "camera_streams" SET "status" = 'UNKNOWN' WHERE "status" = 'EVENT_STANDBY';
        DROP TABLE IF EXISTS "events";"""


MODELS_STATE = ""
