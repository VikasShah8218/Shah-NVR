from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE INDEX IF NOT EXISTS "idx_cameras_name_id" ON "cameras" ("name", "id");
        CREATE INDEX IF NOT EXISTS "idx_camera_streams_status" ON "camera_streams" ("status");
        CREATE INDEX IF NOT EXISTS "idx_camera_assignments_node" ON "camera_assignments" ("node_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_camera_assignments_node";
        DROP INDEX IF EXISTS "idx_camera_streams_status";
        DROP INDEX IF EXISTS "idx_cameras_name_id";"""


MODELS_STATE = ""
