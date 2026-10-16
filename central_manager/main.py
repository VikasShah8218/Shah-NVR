"""Shah-NVR Central Manager (control plane).

Run:  py main.py
Docs: http://localhost:8000/docs
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.assignments.router import router as assignments_router
from app.assignments.services import scheduler_tick
from app.cameras.router import router as cameras_router
from app.cluster.router import router as cluster_router
from app.nodes.router import internal_router as nodes_internal_router
from app.nodes.router import router as nodes_router
from app.nodes.services import node_health_tick
from app.onvif.router import router as onvif_router
from app.playback.router import router as playback_router
from app.recordings.router import internal_router as recordings_internal_router
from app.recordings.router import router as recordings_router
from app.recordings.services import retention_tick
from database.config import TORTOISE_ORM
from settings.settings import settings
from utilities.common import run_periodic

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("central")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with RegisterTortoise(app, config=TORTOISE_ORM, generate_schemas=settings.db_url.startswith("sqlite")):
        tasks = [
            asyncio.create_task(run_periodic("node-health", settings.HEALTH_INTERVAL_SECONDS, node_health_tick)),
            asyncio.create_task(run_periodic("scheduler", settings.SCHEDULER_INTERVAL_SECONDS, scheduler_tick)),
            asyncio.create_task(run_periodic("retention", settings.RETENTION_INTERVAL_SECONDS, retention_tick)),
        ]
        logger.info("%s started", settings.APP_NAME)
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    cameras_router,
    recordings_router,
    playback_router,
    nodes_router,
    assignments_router,
    cluster_router,
    onvif_router,
    nodes_internal_router,
    recordings_internal_router,
):
    app.include_router(r)


@app.get("/", tags=["System"])
async def root():
    return {"service": settings.APP_NAME, "docs": "/docs"}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level=settings.LOG_LEVEL.lower())
