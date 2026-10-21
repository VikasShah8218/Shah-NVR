"""PTZ API, separate from encoder locks so encoder edits cannot queue Stop."""
from contextlib import asynccontextmanager
from fastapi import APIRouter, HTTPException
from pydantic import Field
from app.onvif.schemas import DeviceIn
from app.onvif.services import OnvifDevice
from app.onvif.soap import OnvifError
from app.onvif.ptz_schemas import PtzCommand, PtzState, PtzResult
from app.onvif import ptz

router = APIRouter(prefix="/api/v1/onvif/ptz", tags=["PTZ"])


class PtzOpenIn(DeviceIn):
    profile_token: str = Field(min_length=1, max_length=128)


class PtzCommandIn(PtzOpenIn):
    command: PtzCommand


@asynccontextmanager
async def device(body):
    try:
        async with OnvifDevice(body.host, body.port, body.username, body.password, timeout=2) as dev:
            yield dev
    except OnvifError as exc:
        # Camera fault text can echo request fields. Only return safe categories.
        code = exc.code
        message = {"not_authorized": "Camera rejected PTZ authentication; not retried automatically.",
                   "unreachable": "Camera PTZ request timed out or is unreachable.",
                   "not_supported": "Requested PTZ feature or mapped profile is unsupported.",
                   "fault": "Camera PTZ service rejected the request or is unavailable. Reload before retrying."}[code]
        raise HTTPException({"not_authorized": 401, "unreachable": 504, "not_supported": 501, "fault": 502}[code],
                            {"code": code, "message": message}) from None


@router.post("/open", response_model=PtzState)
async def open_ptz(body: PtzOpenIn):
    async with device(body) as dev:
        return await ptz.open_session(dev, body.profile_token)


@router.post("/command", response_model=PtzResult)
async def ptz_command(body: PtzCommandIn):
    async with device(body) as dev:
        return await ptz.command(dev, body.profile_token, body.command)
