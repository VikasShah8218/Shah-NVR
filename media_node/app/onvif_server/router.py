"""HTTP SOAP endpoints for the H5 virtual ONVIF device."""

import logging

from fastapi import APIRouter, Request, Response, status

from app.node.utils import runtime
from app.onvif_server.auth import digest_challenge, verify_digest, verify_username_token
from app.onvif_server.soap import SoapFault, action, dispatch, fault, parse

logger = logging.getLogger("node.onvif-server")
router = APIRouter(include_in_schema=False)
SOAP_TYPE = "application/soap+xml; charset=utf-8"


def _soap_error(subcode: str, message: str, code: int = 400) -> Response:
    return Response(fault(subcode, message), status_code=code, media_type=SOAP_TYPE)


async def _handle(request: Request, service: str) -> Response:
    if not runtime.onvif_server_config.get("enabled"):
        return _soap_error("ter:ActionNotSupported", "ONVIF server is disabled", status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        root = parse(await request.body())
        operation, _ = action(root)
    except SoapFault as exc:
        return _soap_error(exc.subcode, exc.reason)

    # Time is the unauthenticated bootstrap operation used to make UsernameToken clocks agree.
    if operation != "GetSystemDateAndTime":
        header = request.headers.get("authorization")
        digest_ok = verify_digest(header, request.method, request.url.path)
        wsse_ok = verify_username_token(root) if not header else False
        if not digest_ok and not wsse_ok:
            has_wsse = bool(root.xpath(".//*[local-name()='UsernameToken']"))
            if header or has_wsse:
                logger.warning("Rejected ONVIF authentication from %s for %s", request.client.host if request.client else "?", operation)
            if has_wsse and not header:
                return _soap_error("ter:NotAuthorized", "Sender not authorized", status.HTTP_400_BAD_REQUEST)
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": digest_challenge()},
            )
    try:
        return Response(dispatch(service, root), media_type=SOAP_TYPE)
    except SoapFault as exc:
        return _soap_error(exc.subcode, exc.reason)
    except Exception:
        logger.exception("Unhandled virtual ONVIF action %s", operation)
        return _soap_error("ter:Action", "Internal ONVIF service error", 500)


@router.post("/onvif/device_service")
async def device_service(request: Request):
    return await _handle(request, "device")


@router.post("/onvif/media_service")
async def media_service(request: Request):
    return await _handle(request, "media")
