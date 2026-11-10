from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True

# Camera groups (docs/GROUPING_PLAN.md). Hand-written like 13/14.
# The path index uses varchar_pattern_ops: a plain btree index is NOT used for `LIKE '/3/%'` in PostgreSQL unless
# the column has C collation, and every subtree query is such a prefix match.


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "camera_groups" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "name" VARCHAR(128) NOT NULL,
    "description" TEXT,
    "path" VARCHAR(255) NOT NULL DEFAULT '',
    "depth" INT NOT NULL DEFAULT 0,
    "sort_order" INT NOT NULL DEFAULT 0,
    "created_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "parent_id" INT REFERENCES "camera_groups" ("id") ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS "idx_camera_groups_parent_name" ON "camera_groups" ("parent_id", "name");
CREATE INDEX IF NOT EXISTS "idx_camera_groups_path" ON "camera_groups" ("path" varchar_pattern_ops);
COMMENT ON TABLE "camera_groups" IS 'A folder in the camera tree. Groups nest; a camera sits in one group or none.';
ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "group_id" INT REFERENCES "camera_groups" ("id") ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS "idx_cameras_group_name_id" ON "cameras" ("group_id", "name", "id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_cameras_group_name_id";
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "group_id";
        DROP TABLE IF EXISTS "camera_groups";"""


MODELS_STATE = ""
