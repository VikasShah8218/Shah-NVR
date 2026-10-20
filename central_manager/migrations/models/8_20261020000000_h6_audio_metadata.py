from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "camera_streams" ADD "audio_advertised" BOOL;
        ALTER TABLE "camera_streams" ADD "audio_observed" BOOL;
        ALTER TABLE "camera_streams" ADD "audio_codec" VARCHAR(32);
        ALTER TABLE "camera_streams" ADD "audio_codec_raw" VARCHAR(64);
        ALTER TABLE "camera_streams" ADD "audio_sample_rate" INT;
        ALTER TABLE "camera_streams" ADD "audio_channels" INT;
        ALTER TABLE "camera_streams" ADD "audio_bitrate_kbps" INT;
        ALTER TABLE "camera_streams" ADD "audio_last_observed_at" TIMESTAMPTZ;
        ALTER TABLE "recording_segments" ADD "audio_codec" VARCHAR(32);
        ALTER TABLE "recording_segments" ADD "audio_sample_rate" INT;
        ALTER TABLE "recording_segments" ADD "audio_channels" INT;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "recording_segments" DROP COLUMN "audio_channels";
        ALTER TABLE "recording_segments" DROP COLUMN "audio_sample_rate";
        ALTER TABLE "recording_segments" DROP COLUMN "audio_codec";
        ALTER TABLE "camera_streams" DROP COLUMN "audio_last_observed_at";
        ALTER TABLE "camera_streams" DROP COLUMN "audio_bitrate_kbps";
        ALTER TABLE "camera_streams" DROP COLUMN "audio_channels";
        ALTER TABLE "camera_streams" DROP COLUMN "audio_sample_rate";
        ALTER TABLE "camera_streams" DROP COLUMN "audio_codec_raw";
        ALTER TABLE "camera_streams" DROP COLUMN "audio_codec";
        ALTER TABLE "camera_streams" DROP COLUMN "audio_observed";
        ALTER TABLE "camera_streams" DROP COLUMN "audio_advertised";"""


# Hand-authored deployment migration; the next generated Aerich migration refreshes the model snapshot.
MODELS_STATE = ""
