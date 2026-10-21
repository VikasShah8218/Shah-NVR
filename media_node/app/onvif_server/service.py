"""Lifecycle and status for the H5 discovery and authenticated RTSP listeners."""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.node.models import KeyValue
from app.node.utils import runtime
from app.onvif_server.auth import configured
from app.onvif_server.discovery import Protocol, multicast_socket
from app.onvif_server.rtsp_proxy import rtsp_proxy
from settings.settings import settings

logger = logging.getLogger("node.onvif-server")
KV_UUID = "onvif_server_uuid"


def _valid_uuid(value: object) -> str | None:
    """Read both the current JSON object and any early string-format value."""
    candidate = value.get("uuid") if isinstance(value, dict) else value
    if not isinstance(candidate, str):
        return None
    try:
        return str(uuid.UUID(candidate))
    except ValueError:
        return None


async def persistent_device_uuid() -> str:
    device_uuid = _valid_uuid(await KeyValue.get_value(KV_UUID))
    if device_uuid:
        return device_uuid
    device_uuid = str(uuid.uuid4())
    # KeyValue.value is a JSONField. Store an object rather than a bare
    # string, which Tortoise otherwise attempts to JSON-decode.
    await KeyValue.set_value(KV_UUID, {"uuid": device_uuid})
    return device_uuid


class OnvifServer:
    def __init__(self):
        self.discovery_transport = None
        self.device_uuid: str | None = None
        self.state = "disabled"
        self.last_error: str | None = None

    async def apply(self) -> None:
        enabled = bool(runtime.onvif_server_config.get("enabled"))
        if not enabled:
            await self.stop(); self.state = "disabled"; return
        if not configured():
            await self.stop(); self.state = "error"
            self.last_error = "Set ONVIF_SERVER_USERNAME and ONVIF_SERVER_PASSWORD on this node"
            return
        if self.discovery_transport and rtsp_proxy.server:
            self.state = "online"; self.last_error = None; return
        try:
            self.device_uuid = await persistent_device_uuid()
            await rtsp_proxy.start()
            loop = asyncio.get_running_loop()
            self.discovery_transport, _ = await loop.create_datagram_endpoint(
                lambda: Protocol(self.device_uuid), sock=multicast_socket()
            )
            self.state = "online"; self.last_error = None
            logger.info("Virtual ONVIF device enabled as %s (%s)", runtime.onvif_server_config.get("discovery_name"), self.device_uuid)
        except Exception as exc:
            await self.stop(); self.state = "error"; self.last_error = str(exc)
            logger.exception("Cannot start virtual ONVIF device")

    async def stop(self) -> None:
        if self.discovery_transport:
            self.discovery_transport.close(); self.discovery_transport = None
        await rtsp_proxy.stop()

    def status(self) -> dict:
        exposed = [a for a in runtime.assignments.values() if a.get("expose_via_onvif", True)]
        return {
            "status": self.state,
            "credentials_configured": configured(),
            "xaddr": f"http://{settings.public_host}:{settings.PORT}/onvif/device_service" if self.state == "online" else None,
            "rtsp_address": f"rtsp://{settings.public_host}:{settings.ONVIF_RTSP_PORT}" if self.state == "online" else None,
            "exposed_cameras": len(exposed),
            "exposed_profiles": sum(len(a.get("streams", [])) for a in exposed),
            "last_error": self.last_error,
        }


onvif_server = OnvifServer()
