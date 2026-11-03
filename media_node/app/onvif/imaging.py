"""ONVIF Imaging service: continuous manual focus for PTZ cameras.

Used for the PTZ overlay's focus controls. This is deliberately separate from PTZ: on the
Illustra Pro4 the ONVIF *PTZ* service is down (HTTP 503) while its *Imaging* service is
healthy, and a continuous Imaging focus Move auto-switches the camera to manual focus (per
the ONVIF spec), so it works the same way across cameras regardless of the PTZ backend.
"""
from app.onvif.soap import NS, OnvifError

IMG = "http://www.onvif.org/ver20/imaging/wsdl"


async def discover(dev) -> tuple[str | None, str | None]:
    """(imaging_xaddr, video_source_token) if the camera advertises Imaging, else (None, None)."""
    services = await dev.services()
    xaddr = services.get(IMG)
    if not xaddr:
        return None, None
    media1 = services.get(NS["trt"]) or dev.device_url
    try:
        reply = await dev.soap.call(media1, "<trt:GetVideoSources/>")
    except OnvifError:
        return None, None
    source = reply.find(".//trt:VideoSources", NS)
    token = source.get("token") if source is not None else None
    return (xaddr, token) if token else (None, None)


async def focus_move(dev, xaddr: str, token: str, speed: float) -> None:
    """Continuous manual focus; speed in [-1, 1] (positive = near). Runs until focus_stop()."""
    await dev.soap.call(
        xaddr,
        f'<timg:Move xmlns:timg="{IMG}"><timg:VideoSourceToken>{token}</timg:VideoSourceToken>'
        f"<timg:Focus><tt:Continuous><tt:Speed>{speed:.3f}</tt:Speed></tt:Continuous></timg:Focus></timg:Move>",
    )


async def focus_stop(dev, xaddr: str, token: str) -> None:
    await dev.soap.call(
        xaddr, f'<timg:Stop xmlns:timg="{IMG}"><timg:VideoSourceToken>{token}</timg:VideoSourceToken></timg:Stop>'
    )
