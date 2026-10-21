from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "export_jobs" (
            "id" UUID NOT NULL PRIMARY KEY,
            "profile" VARCHAR(32) NOT NULL DEFAULT 'main',
            "start_time" TIMESTAMPTZ NOT NULL,
            "end_time" TIMESTAMPTZ NOT NULL,
            "mode" VARCHAR(16) NOT NULL,
            "state" VARCHAR(16) NOT NULL DEFAULT 'QUEUED',
            "options" JSONB NOT NULL DEFAULT '{}',
            "progress_percent" DOUBLE PRECISION NOT NULL DEFAULT 0,
            "attempt_count" INT NOT NULL DEFAULT 0,
            "lease_expires_at" TIMESTAMPTZ,
            "output_name" VARCHAR(256),
            "output_size_bytes" BIGINT NOT NULL DEFAULT 0,
            "output_sha256" VARCHAR(64),
            "encoder" VARCHAR(64),
            "recorded_seconds" DOUBLE PRECISION NOT NULL DEFAULT 0,
            "gap_seconds" DOUBLE PRECISION NOT NULL DEFAULT 0,
            "error_code" VARCHAR(64),
            "error_message" VARCHAR(512),
            "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "started_at" TIMESTAMPTZ,
            "finished_at" TIMESTAMPTZ,
            "expires_at" TIMESTAMPTZ,
            "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "camera_id" INT NOT NULL REFERENCES "cameras" ("id") ON DELETE CASCADE,
            "node_id" INT REFERENCES "media_nodes" ("id") ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS "idx_export_jobs_camera_created" ON "export_jobs" ("camera_id", "created_at");
        CREATE INDEX IF NOT EXISTS "idx_export_jobs_node_state_created" ON "export_jobs" ("node_id", "state", "created_at");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return 'DROP TABLE IF EXISTS "export_jobs";'


MODELS_STATE = ""
