from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True

# Camera events from ONVIF (docs/ONVIF_EVENTS_PLAN.md). Hand-written like 13-19. Additive: off for every camera.


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "onvif_events_enabled" BOOL NOT NULL DEFAULT False;
ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "onvif_event_kinds" JSONB;
ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "onvif_events_store_other" BOOL NOT NULL DEFAULT False;
ALTER TABLE "cameras" ADD COLUMN IF NOT EXISTS "onvif_events_status" JSONB;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "onvif_events_status";
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "onvif_events_store_other";
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "onvif_event_kinds";
        ALTER TABLE "cameras" DROP COLUMN IF EXISTS "onvif_events_enabled";"""


MODELS_STATE = ""
