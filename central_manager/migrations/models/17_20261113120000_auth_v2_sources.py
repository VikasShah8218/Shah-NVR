from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True

# Two Auth Servers side by side (docs/AUTH_V2_PLAN.md). Additive, works for both AUTH_PROVIDER values:
# * audit_events.user_id becomes text: "12" from the old server, a UUID from the new one; existing rows keep their
#   numbers as text and are marked auth_source = 'legacy'.
# * access_grants gets auth_source: a grant counts only while its server is the active provider (ids never match).
# Hand-written like 13-16.


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "audit_events" ALTER COLUMN "user_id" TYPE VARCHAR(64) USING "user_id"::VARCHAR(64);
        ALTER TABLE "audit_events" ADD COLUMN IF NOT EXISTS "auth_source" VARCHAR(8);
        UPDATE "audit_events" SET "auth_source" = 'legacy' WHERE "user_id" IS NOT NULL;
        ALTER TABLE "access_grants" ADD COLUMN IF NOT EXISTS "auth_source" VARCHAR(8) NOT NULL DEFAULT 'legacy';
        DROP INDEX IF EXISTS "idx_access_grants_subject";
        CREATE INDEX IF NOT EXISTS "idx_access_grants_source_subject"
            ON "access_grants" ("auth_source", "subject_type", "subject");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_access_grants_source_subject";
        DELETE FROM "access_grants" WHERE "auth_source" <> 'legacy';
        ALTER TABLE "access_grants" DROP COLUMN IF EXISTS "auth_source";
        CREATE INDEX IF NOT EXISTS "idx_access_grants_subject" ON "access_grants" ("subject_type", "subject");
        ALTER TABLE "audit_events" DROP COLUMN IF EXISTS "auth_source";
        ALTER TABLE "audit_events" ALTER COLUMN "user_id" TYPE INT
            USING CASE WHEN "user_id" ~ '^[0-9]+$' THEN "user_id"::INT END;"""


MODELS_STATE = ""
