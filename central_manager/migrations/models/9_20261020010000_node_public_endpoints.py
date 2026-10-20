from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "media_nodes" ADD "public_enabled" BOOL NOT NULL DEFAULT FALSE;
        ALTER TABLE "media_nodes" ADD "public_api_url" VARCHAR(256);
        ALTER TABLE "media_nodes" ADD "public_media_host" VARCHAR(256);
        ALTER TABLE "media_nodes" ADD "public_rtsp_port" INT;
        ALTER TABLE "media_nodes" ADD "public_hls_port" INT;
        ALTER TABLE "media_nodes" ADD "public_webrtc_port" INT;
        ALTER TABLE "media_nodes" ADD "public_media_tls" BOOL NOT NULL DEFAULT FALSE;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "media_nodes" DROP COLUMN "public_media_tls";
        ALTER TABLE "media_nodes" DROP COLUMN "public_webrtc_port";
        ALTER TABLE "media_nodes" DROP COLUMN "public_hls_port";
        ALTER TABLE "media_nodes" DROP COLUMN "public_rtsp_port";
        ALTER TABLE "media_nodes" DROP COLUMN "public_media_host";
        ALTER TABLE "media_nodes" DROP COLUMN "public_api_url";
        ALTER TABLE "media_nodes" DROP COLUMN "public_enabled";"""


MODELS_STATE = ""
