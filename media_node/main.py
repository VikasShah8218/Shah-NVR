"""Shah-NVR Media Node (recorder + streamer).

Runs MediaMTX as a child process, pulls & records the cameras assigned by the central
manager, indexes finished chunks, reports them to central, and serves recorded video.

Run:  py main.py
Docs: http://localhost:7100/docs
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.mediamtx.services import reconcile_tick, supervisor
from app.mediamtx.utils import mtx
from app.node.router import router as node_router
from app.node.services import check_public_host, heartbeat_tick, load_local_state, register, stream_status_tick
from app.node.utils import central
from app.onvif.health import onvif_tick
from app.onvif.router import router as onvif_router
from app.onvif.ptz_router import router as ptz_router
from app.onvif_server.router import router as onvif_server_router
from app.onvif_server.service import onvif_server
from app.recordings.router import router as recordings_router
from app.recordings.services import deletion_tick, scan_tick, upload_tick
from app.storage.services import storage, storage_tick
from database.config import TORTOISE_ORM
from database.migrate import migrate
from settings.settings import settings
from utilities.common import run_periodic
from utilities.logbuffer import log_buffer

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
logging.basicConfig(level=settings.LOG_LEVEL, format=LOG_FORMAT)
log_buffer.setFormatter(logging.Formatter(LOG_FORMAT))
logging.getLogger().addHandler(log_buffer)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("node")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Local SQLite state; tables are created automatically.
    async with RegisterTortoise(app, config=TORTOISE_ORM, generate_schemas=True):
        await migrate()  # bring an older local database up to date
        logger.info("Clients reach this node at %s (PUBLIC_HOST=%s)", settings.public_host, settings.PUBLIC_HOST)
        await load_local_state()
        await storage.load()
        await storage.refresh()  # pick the recording target before MediaMTX gets its first paths
        await supervisor.start()
        await register()
        await onvif_server.apply()

        tasks = [
            asyncio.create_task(run_periodic(name, interval, func))
            for name, interval, func in (
                ("heartbeat", settings.HEARTBEAT_INTERVAL_SECONDS, heartbeat_tick),
                ("reconcile", settings.RECONCILE_INTERVAL_SECONDS, reconcile_tick),
                ("scanner", settings.SCAN_INTERVAL_SECONDS, scan_tick),
                ("uploader", settings.UPLOAD_INTERVAL_SECONDS, upload_tick),
                ("stream-status", settings.STATUS_INTERVAL_SECONDS, stream_status_tick),
                ("deletion", settings.DELETION_INTERVAL_SECONDS, deletion_tick),
                ("storage", settings.STORAGE_CHECK_INTERVAL_SECONDS, storage_tick),
                ("address", settings.ADDRESS_CHECK_INTERVAL_SECONDS, check_public_host),
                ("onvif-health", settings.ONVIF_CHECK_INTERVAL_SECONDS, onvif_tick),
            )
        ]
        logger.info("Media node '%s' started; API %s", settings.NODE_NAME, settings.api_url)
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await onvif_server.stop()
            await supervisor.stop()
            await mtx.close()
            await central.close()


app = FastAPI(title=f"Shah-NVR Media Node ({settings.NODE_NAME})", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
app.include_router(node_router)
app.include_router(recordings_router)
app.include_router(onvif_router)
app.include_router(ptz_router)
app.include_router(onvif_server_router)


@app.get("/", tags=["System"])
async def root():
    return {"service": "Shah-NVR Media Node", "node": settings.NODE_NAME, "docs": "/docs"}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level=settings.LOG_LEVEL.lower())
