from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "bookmarks" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "profile" VARCHAR(32),
    "start_time" TIMESTAMPTZ NOT NULL,
    "end_time" TIMESTAMPTZ,
    "note" TEXT NOT NULL,
    "label" VARCHAR(64),
    "color" VARCHAR(16),
    "author" VARCHAR(128),
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "camera_id" INT NOT NULL REFERENCES "cameras" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_bookmarks_camera__1f18a4" ON "bookmarks" ("camera_id", "start_time");
COMMENT ON TABLE "bookmarks" IS 'An operator''s note on a moment (end_time None) or a range of a camera''s recordings.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "bookmarks";"""


MODELS_STATE = (
    "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"
    "BeZw=="
)
