"""Shah-NVR Central Manager (control plane).

Run:  py main.py
Docs: http://localhost:8000/docs
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.access.router import router as access_router
from app.assignments.router import router as assignments_router
from app.assignments.services import scheduler_tick
from app.backfill.router import internal_router as backfill_internal_router
from app.backfill.router import router as backfill_router
from app.backfill.services import backfill_scheduler_tick
from app.bookmarks.router import router as bookmarks_router
from app.cameras.router import router as cameras_router
from app.cluster.router import router as cluster_router
from app.audit.router import router as audit_router
from app.audit.services import prune_audit
from app.auth.deps import AuditMiddleware, guard
from app.auth.provider import check_provider_setting, create_provider, set_provider
from app.auth.router import router as auth_router
from app.groups.router import router as groups_router
from app.nodes.router import internal_router as nodes_internal_router
from app.nodes.router import router as nodes_router
from app.nodes.services import node_health_tick
from app.onvif.router import router as onvif_router
from app.onvif.encoder_router import router as encoder_router
from app.onvif.ptz_router import router as ptz_router
from app.playback.router import router as playback_router
from app.exports.router import internal_router as exports_internal_router
from app.exports.router import router as exports_router
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
            asyncio.create_task(run_periodic("backfill", settings.BACKFILL_SCHEDULER_INTERVAL_SECONDS,
                                             backfill_scheduler_tick)),
            asyncio.create_task(run_periodic("audit-retention", 86400, prune_audit)),
        ]
        check_provider_setting()
        auth_provider = None
        if settings.AUTH_ENABLED:  # docs/AUTH_V2_PLAN.md: legacy (old server) or oidc (new server, auth_sdk)
            auth_provider = create_provider()
            await auth_provider.start()
            set_provider(auth_provider)
        logger.info("%s started (auth %s)", settings.APP_NAME,
                    f"ON, {settings.AUTH_PROVIDER} provider, app {settings.AUTH_APP_KEY}" if settings.AUTH_ENABLED
                    else "OFF: open API")
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if auth_provider is not None:
                set_provider(None)
                await auth_provider.stop()


# Every API route goes through the guard (app/auth/deps.py): permission rule, caller, camera scope, audit mark.
app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan, dependencies=[Depends(guard)])
app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Auth-Error"],
)

for r in (
    auth_router,
    access_router,
    audit_router,
    cameras_router,
    groups_router,
    recordings_router,
    playback_router,
    bookmarks_router,
    nodes_router,
    assignments_router,
    cluster_router,
    onvif_router,
    encoder_router,
    ptz_router,
    backfill_router,
    exports_router,
    nodes_internal_router,
    recordings_internal_router,
    backfill_internal_router,
    exports_internal_router,
):
    app.include_router(r)


@app.get("/", tags=["System"])
async def root():
    return {"service": settings.APP_NAME, "docs": "/docs"}


if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level=settings.LOG_LEVEL.lower())
