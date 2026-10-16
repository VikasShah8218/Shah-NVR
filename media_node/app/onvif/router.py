"""ONVIF on the node's LAN: discovery, probe, device state and the H1 device actions.

Central calls these (central -> node -> camera); credentials arrive per request. Errors come back as
{"detail": {"code": not_authorized | unreachable | not_supported | fault, "message": ...}}.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Response

from app.onvif.discovery import discover
from app.onvif.schemas import (ClockOut, DeviceIn, DeviceStateOut, DiscoveredDevice, DiscoverIn, NtpIn, ProbeOut,
                               RebootOut, SnapshotIn)
from app.onvif.services import OnvifDevice
from app.onvif.soap import OnvifError

router = APIRouter(prefix="/api/v1/onvif", tags=["ONVIF"])
logger = logging.getLogger("node.onvif")
_STATUS = {"not_authorized": 401, "unreachable": 504, "not_supported": 501, "fault": 502}


@asynccontextmanager
async def device(body: DeviceIn) -> AsyncIterator[OnvifDevice]:
    """Open the device; turn ONVIF errors into HTTP errors with a stable code."""
    try:
        async with OnvifDevice(body.host, body.port, body.username, body.password, xaddr=body.xaddr) as dev:
            yield dev
    except OnvifError as exc:
        logger.info("ONVIF %s %s: %s", body.host, exc.code, exc.message)
        raise HTTPException(_STATUS[exc.code], {"code": exc.code, "message": exc.message}) from None


@router.post("/discover", response_model=list[DiscoveredDevice], summary="WS-Discovery on this node's LAN")
async def onvif_discover(body: DiscoverIn | None = None):
    return await discover((body or DiscoverIn()).seconds)


@router.post("/probe", response_model=ProbeOut, summary="Identity, clock and stream profiles of one device")
async def onvif_probe(body: DeviceIn):
    async with device(body) as dev:
        return await dev.probe()


@router.post("/device", response_model=DeviceStateOut, summary="Live identity, clock and read-only settings")
async def onvif_device_state(body: DeviceIn):
    async with device(body) as dev:
        clock = await dev.clock()
        info = await dev.info()
        services = await dev.services()
        return {"clock": clock, "info": info, "services": sorted(services), **await dev.settings()}


@router.post("/device/clock", response_model=ClockOut, summary="Camera clock offset (no login needed on most cameras)")
async def onvif_clock(body: DeviceIn):
    async with device(body) as dev:
        return await dev.clock()


@router.post("/device/time-sync", response_model=ClockOut, summary="Set the camera clock to this node's UTC time")
async def onvif_time_sync(body: DeviceIn):
    async with device(body) as dev:
        await dev.clock()  # offset first, so the login token is accepted by a skewed camera
        return await dev.set_time_from_node()


@router.post("/device/ntp", summary="Point the camera at NTP servers (or DHCP-provided ones)")
async def onvif_ntp(body: NtpIn):
    if not body.from_dhcp and not body.servers:
        raise HTTPException(422, "give NTP servers or from_dhcp=true")
    async with device(body) as dev:
        await dev.clock()
        return await dev.set_ntp(body.from_dhcp, body.servers)


@router.post("/device/reboot", response_model=RebootOut, summary="Reboot the camera")
async def onvif_reboot(body: DeviceIn):
    async with device(body) as dev:
        await dev.clock()
        return {"message": await dev.reboot()}


@router.post("/snapshot", summary="JPEG snapshot through the node (for previews while adding cameras)",
             response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
async def onvif_snapshot(body: SnapshotIn):
    async with device(body) as dev:
        data, ctype = await dev.snapshot(body.uri)
    return Response(data, media_type=ctype, headers={"Cache-Control": "no-store"})
