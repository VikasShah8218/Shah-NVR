from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True

# Camera access grants + audit log (docs/AUTH_INTEGRATION_PLAN.md §6, §7.7). Hand-written like 13-15.


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "access_grants" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "subject_type" VARCHAR(8) NOT NULL,
    "subject" VARCHAR(128) NOT NULL,
    "all_cameras" BOOL NOT NULL DEFAULT False,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "group_id" INT REFERENCES "camera_groups" ("id") ON DELETE CASCADE,
    "camera_id" INT REFERENCES "cameras" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_access_grants_subject" ON "access_grants" ("subject_type", "subject");
COMMENT ON TABLE "access_grants" IS 'Which cameras a role or a user may see (group subtree, camera, or all).';
CREATE TABLE IF NOT EXISTS "audit_events" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "user_id" INT,
    "username" VARCHAR(128) NOT NULL,
    "action" VARCHAR(64) NOT NULL,
    "method" VARCHAR(8),
    "path" VARCHAR(512) NOT NULL,
    "camera_id" INT,
    "status" VARCHAR(16) NOT NULL DEFAULT 'ok',
    "detail" JSONB,
    "ip" VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS "idx_audit_events_at" ON "audit_events" ("at");
CREATE INDEX IF NOT EXISTS "idx_audit_events_action" ON "audit_events" ("action");
CREATE INDEX IF NOT EXISTS "idx_audit_events_camera" ON "audit_events" ("camera_id");
COMMENT ON TABLE "audit_events" IS 'Who did what, when: sign-ins, live / playback opens, exports and every change.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "audit_events";
        DROP TABLE IF EXISTS "access_grants";"""


MODELS_STATE = ""
