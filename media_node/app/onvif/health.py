"""Background ONVIF health of this node's cameras: reachable + clock offset, sent to central in the heartbeat.

Only the unauthenticated GetSystemDateAndTime is used: a background loop must never send logins (a wrong saved
password would lock the camera account). Devices that demand a login even for the time count as reachable with an
unknown offset.
"""

from __future__ import annotations

import asyncio
import logging

from app.node.utils import runtime
from app.onvif.services import OnvifDevice
from app.onvif.soap import NotAuthorized, OnvifError, Unreachable
from utilities.common import utcnow

logger = logging.getLogger("node.onvif")
CONCURRENCY = 20

# camera_id -> {camera_id, reachable, clock_offset_seconds, checked_at}; drained by the heartbeat
pending: dict[int, dict] = {}


async def check_camera(camera_id: int, host: str, port: int) -> dict:
    result = {"camera_id": camera_id, "reachable": True, "clock_offset_seconds": None}
    try:
        async with OnvifDevice(host, port) as dev:
            result["clock_offset_seconds"] = (await dev.clock())["offset_seconds"]
    except NotAuthorized:
        pass  # answered, but wants a login even for the time
    except Unreachable:
        result["reachable"] = False
    except OnvifError as exc:
        logger.debug("ONVIF health %s: %s", host, exc.message)
    result["checked_at"] = utcnow().isoformat()
    return result


async def onvif_tick() -> None:
    targets = [(cid, a["onvif_host"], a.get("onvif_port") or 80)
               for cid, a in list(runtime.assignments.items()) if a.get("onvif_host")]
    if not targets:
        return
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(t):
        async with sem:
            return await check_camera(*t)

    for r in await asyncio.gather(*(one(t) for t in targets)):
        pending[r["camera_id"]] = r


def take_reports() -> list[dict]:
    """Reports for the next heartbeat (removed only after central accepted them: see `ack_reports`)."""
    return list(pending.values())


def ack_reports(sent: list[dict]) -> None:
    for r in sent:
        if pending.get(r["camera_id"]) is r:
            del pending[r["camera_id"]]
