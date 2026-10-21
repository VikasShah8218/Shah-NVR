from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "cameras" ADD "backfill_mode" VARCHAR(16) NOT NULL DEFAULT 'off';
        ALTER TABLE "cameras" ADD "backfill_profile" VARCHAR(32) NOT NULL DEFAULT 'main';
        ALTER TABLE "cameras" ADD "backfill_recording_token" VARCHAR(256);
        ALTER TABLE "cameras" ADD "backfill_capability" VARCHAR(16) NOT NULL DEFAULT 'unknown';
        ALTER TABLE "cameras" ADD "backfill_earliest" TIMESTAMPTZ;
        ALTER TABLE "cameras" ADD "backfill_latest" TIMESTAMPTZ;
        ALTER TABLE "cameras" ADD "backfill_checked_at" TIMESTAMPTZ;
        ALTER TABLE "cameras" ADD "backfill_error" VARCHAR(512);
        CREATE TABLE IF NOT EXISTS "backfill_jobs" (
            "id" UUID NOT NULL PRIMARY KEY,
            "profile" VARCHAR(32) NOT NULL DEFAULT 'main',
            "recording_token" VARCHAR(256) NOT NULL,
            "start_time" TIMESTAMPTZ NOT NULL,
            "end_time" TIMESTAMPTZ NOT NULL,
            "state" VARCHAR(16) NOT NULL DEFAULT 'QUEUED',
            "requested_by" VARCHAR(16) NOT NULL DEFAULT 'manual',
            "assignment_generation" BIGINT NOT NULL DEFAULT 0,
            "lease_expires_at" TIMESTAMPTZ,
            "attempt_count" INT NOT NULL DEFAULT 0,
            "progress_percent" DOUBLE PRECISION NOT NULL DEFAULT 0,
            "imported_seconds" DOUBLE PRECISION NOT NULL DEFAULT 0,
            "imported_bytes" BIGINT NOT NULL DEFAULT 0,
            "error_code" VARCHAR(64),
            "error_message" VARCHAR(512),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "started_at" TIMESTAMPTZ,
            "finished_at" TIMESTAMPTZ,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "camera_id" INT NOT NULL REFERENCES "cameras" ("id") ON DELETE CASCADE,
            "node_id" INT REFERENCES "media_nodes" ("id") ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS "idx_backfill_jobs_camera_profile_start" ON "backfill_jobs" ("camera_id", "profile", "start_time");
        CREATE INDEX IF NOT EXISTS "idx_backfill_jobs_state_created" ON "backfill_jobs" ("state", "created_at");
        ALTER TABLE "recording_segments" ADD "origin" VARCHAR(16) NOT NULL DEFAULT 'NVR';
        ALTER TABLE "recording_segments" ADD "backfill_job_id" UUID;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "recording_segments" DROP COLUMN "backfill_job_id";
        ALTER TABLE "recording_segments" DROP COLUMN "origin";
        DROP TABLE IF EXISTS "backfill_jobs";
        ALTER TABLE "cameras" DROP COLUMN "backfill_error";
        ALTER TABLE "cameras" DROP COLUMN "backfill_checked_at";
        ALTER TABLE "cameras" DROP COLUMN "backfill_latest";
        ALTER TABLE "cameras" DROP COLUMN "backfill_earliest";
        ALTER TABLE "cameras" DROP COLUMN "backfill_capability";
        ALTER TABLE "cameras" DROP COLUMN "backfill_recording_token";
        ALTER TABLE "cameras" DROP COLUMN "backfill_profile";
        ALTER TABLE "cameras" DROP COLUMN "backfill_mode";"""


MODELS_STATE = ""
