from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "cameras" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "name" VARCHAR(128) NOT NULL,
    "description" TEXT,
    "username" VARCHAR(128),
    "password" VARCHAR(256),
    "enabled" BOOL NOT NULL,
    "retention_days" INT NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS "camera_streams" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "profile" VARCHAR(32) NOT NULL,
    "source_url" VARCHAR(1024) NOT NULL,
    "record" BOOL NOT NULL,
    "rtsp_transport" VARCHAR(16) NOT NULL,
    "status" VARCHAR(32) NOT NULL,
    "status_detail" VARCHAR(512),
    "bytes_received" BIGINT NOT NULL,
    "last_status_at" TIMESTAMPTZ,
    "last_segment_at" TIMESTAMPTZ,
    "camera_id" INT NOT NULL REFERENCES "cameras" ("id") ON DELETE CASCADE,
    CONSTRAINT "uid_camera_stre_camera__9a07f2" UNIQUE ("camera_id", "profile")
);
COMMENT ON COLUMN "camera_streams"."status" IS 'UNKNOWN: UNKNOWN\nUNASSIGNED: UNASSIGNED\nASSIGNED: ASSIGNED\nCONNECTING: CONNECTING\nIDLE: IDLE\nSTREAMING: STREAMING\nRECORDING: RECORDING\nNOT_RECORDING: NOT_RECORDING\nDISABLED: DISABLED';
COMMENT ON TABLE "camera_streams" IS 'One video profile of a camera (main / sub / ...), pulled by MediaMTX as one path.';
CREATE TABLE IF NOT EXISTS "media_nodes" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "name" VARCHAR(64) NOT NULL UNIQUE,
    "api_url" VARCHAR(256) NOT NULL,
    "media_host" VARCHAR(256) NOT NULL,
    "rtsp_port" INT NOT NULL,
    "hls_port" INT NOT NULL,
    "webrtc_port" INT NOT NULL,
    "capacity_cameras" INT NOT NULL,
    "version" VARCHAR(64),
    "mediamtx_version" VARCHAR(64),
    "state" VARCHAR(16) NOT NULL,
    "last_heartbeat_at" TIMESTAMPTZ,
    "metrics" JSONB,
    "registered_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL
);
COMMENT ON COLUMN "media_nodes"."state" IS 'READY: READY\nACTIVE: ACTIVE\nDRAINING: DRAINING\nCORDONED: CORDONED\nUNREACHABLE: UNREACHABLE\nOFFLINE: OFFLINE';
CREATE TABLE IF NOT EXISTS "assignment_history" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "generation" BIGINT NOT NULL,
    "reason" VARCHAR(64) NOT NULL,
    "started_at" TIMESTAMPTZ NOT NULL,
    "ended_at" TIMESTAMPTZ,
    "camera_id" INT NOT NULL REFERENCES "cameras" ("id") ON DELETE CASCADE,
    "node_id" INT REFERENCES "media_nodes" ("id") ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS "camera_assignments" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "generation" BIGINT NOT NULL,
    "lease_expires_at" TIMESTAMPTZ,
    "reason" VARCHAR(64),
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "node_id" INT REFERENCES "media_nodes" ("id") ON DELETE SET NULL,
    "camera_id" INT NOT NULL UNIQUE REFERENCES "cameras" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "camera_assignments" IS 'Which media node owns (pulls + records) a camera. One row per camera, kept forever';
CREATE TABLE IF NOT EXISTS "recording_segments" (
    "id" UUID NOT NULL PRIMARY KEY,
    "profile" VARCHAR(32) NOT NULL,
    "generation" BIGINT NOT NULL,
    "start_time" TIMESTAMPTZ NOT NULL,
    "end_time" TIMESTAMPTZ NOT NULL,
    "duration_ms" INT NOT NULL,
    "size_bytes" BIGINT NOT NULL,
    "codec" VARCHAR(32),
    "file_path" VARCHAR(512) NOT NULL,
    "parts" JSONB NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "camera_id" INT NOT NULL REFERENCES "cameras" ("id") ON DELETE CASCADE,
    "node_id" INT NOT NULL REFERENCES "media_nodes" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_recording_s_camera__ec7678" ON "recording_segments" ("camera_id", "profile", "start_time");
CREATE INDEX IF NOT EXISTS "idx_recording_s_status_4d0655" ON "recording_segments" ("status", "end_time");
COMMENT ON COLUMN "recording_segments"."status" IS 'AVAILABLE: AVAILABLE\nDELETING: DELETING';
COMMENT ON TABLE "recording_segments" IS 'Index of one recorded chunk (fMP4 file) stored on a media node. Video bytes are never stored here.';
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
    "kXLPnnDPnuAKlMMvZu//B/Scv8A="
)
