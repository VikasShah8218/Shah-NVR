from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "media_nodes" ADD "onvif_server_enabled" BOOL NOT NULL DEFAULT FALSE;
        ALTER TABLE "media_nodes" ADD "onvif_server_name" VARCHAR(128) NOT NULL DEFAULT 'Shah-NVR';
        ALTER TABLE "media_nodes" ADD "onvif_server_location" VARCHAR(256);
        ALTER TABLE "cameras" ADD "expose_via_onvif" BOOL NOT NULL DEFAULT TRUE;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "cameras" DROP COLUMN "expose_via_onvif";
        ALTER TABLE "media_nodes" DROP COLUMN "onvif_server_location";
        ALTER TABLE "media_nodes" DROP COLUMN "onvif_server_name";
        ALTER TABLE "media_nodes" DROP COLUMN "onvif_server_enabled";"""


# Aerich applies the SQL above during upgrade. The next generated migration will
# refresh its complete model snapshot from the live models.
MODELS_STATE = ""
