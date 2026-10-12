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
from app.node.services import heartbeat_tick, load_local_state, register, stream_status_tick
from app.node.utils import central
from app.recordings.router import router as recordings_router
from app.recordings.services import deletion_tick, scan_tick, upload_tick
from database.config import TORTOISE_ORM
from settings.settings import settings
from utilities.common import run_periodic

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("node")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Local SQLite state; tables are created automatically.
    async with RegisterTortoise(app, config=TORTOISE_ORM, generate_schemas=True):
        await load_local_state()
        await supervisor.start()
        await register()

        tasks = [
            asyncio.create_task(run_periodic(name, interval, func))
            for name, interval, func in (
                ("heartbeat", settings.HEARTBEAT_INTERVAL_SECONDS, heartbeat_tick),
                ("reconcile", settings.RECONCILE_INTERVAL_SECONDS, reconcile_tick),
                ("scanner", settings.SCAN_INTERVAL_SECONDS, scan_tick),
                ("uploader", settings.UPLOAD_INTERVAL_SECONDS, upload_tick),
                ("stream-status", settings.STATUS_INTERVAL_SECONDS, stream_status_tick),
                ("deletion", settings.DELETION_INTERVAL_SECONDS, deletion_tick),
            )
        ]
        logger.info("Media node '%s' started; API %s", settings.NODE_NAME, settings.api_url)
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await supervisor.stop()
            await mtx.close()
            await central.close()


app = FastAPI(title=f"Shah-NVR Media Node ({settings.NODE_NAME})", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
app.include_router(node_router)
app.include_router(recordings_router)


@app.get("/", tags=["System"])
async def root():
    return {"service": "Shah-NVR Media Node", "node": settings.NODE_NAME, "docs": "/docs"}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level=settings.LOG_LEVEL.lower())
