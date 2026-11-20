"""Diagnose subscription-manager quirks on one camera: which Renew / Unsubscribe forms it accepts.

Variants tried (each on a fresh subscription, always cleaned up):
  renew-duration   <TerminationTime>PT60S</TerminationTime>            (relative, xs:duration)
  renew-absolute   <TerminationTime>{camera now + 60 s}</TerminationTime> (absolute, camera clock)
  unsub-wsa        Unsubscribe with WS-Addressing headers + ReferenceParameters (what the lab normally sends)
  unsub-plain      Unsubscribe without WS-Addressing headers
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .camera import A_SM, Camera
from .soap import SoapError


async def renew_unsubscribe_variants(cam: Camera) -> dict:
    await cam.clock()
    await cam.services()
    out = {}

    async def attempt(name, fn):
        try:
            r = await fn()
            out[name] = {"ok": True, "result": r}
        except SoapError as exc:
            out[name] = {"ok": False, "kind": exc.kind, "message": exc.message[:160]}

    sub = await cam.subscribe(60)
    await attempt("renew-duration", lambda: cam.renew(sub, 60))
    cam_now = datetime.now(timezone.utc) + timedelta(seconds=cam.client.offset)
    absolute = (cam_now + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    await attempt("renew-absolute", lambda: cam.client.call(
        sub.address, f"<wsnt:Renew><wsnt:TerminationTime>{absolute}</wsnt:TerminationTime></wsnt:Renew>",
        f"{A_SM}/RenewRequest", wsa=True, extra_headers=sub.ref_params))
    await attempt("unsub-plain", lambda: cam.client.call(sub.address, "<wsnt:Unsubscribe/>",
                                                         f"{A_SM}/UnsubscribeRequest"))
    if not out["unsub-plain"]["ok"]:
        await attempt("unsub-wsa", lambda: cam.unsubscribe(sub))
    # is it really gone? a pull on a removed subscription must fail
    try:
        await cam.pull(sub, 1)
        out["gone_after_unsubscribe"] = False
    except SoapError as exc:
        out["gone_after_unsubscribe"] = exc.kind
    for k, v in out.items():
        if isinstance(v, dict) and v.get("ok") and not isinstance(v.get("result"), (str, type(None))):
            v["result"] = "ok"
    return out


TPTZ = "http://www.onvif.org/ver20/ptz/wsdl"


async def ptz_nudge(cam: Camera, pan: float = 0.04, hold_s: float = 10.0) -> dict:
    """A controlled trigger: read the PTZ position, nudge the pan a little (RelativeMove), wait, then AbsoluteMove back
    to the exact saved position. Times are logged (our clock, UTC) so `listen` results can be matched to them.
    Used to measure motion / PTZ event latency on a real camera. The camera ends where it started."""
    import asyncio

    from .soap import NS as _NS
    from .soap import text

    await cam.clock()
    svcs = await cam.services()
    ptz = next((s["xaddr"] for ns, s in svcs.items() if ns == TPTZ), None)
    if not ptz:  # some firmware (Illustra Pro4 SS010.26) leaves PTZ out of GetServices: ask GetCapabilities
        b = await cam.client.call(cam.device_url, "<tds:GetCapabilities><tds:Category>PTZ</tds:Category>"
                                                  "</tds:GetCapabilities>",
                                  "http://www.onvif.org/ver10/device/wsdl/GetCapabilities")
        ptz = cam.fix_addr(text(b, ".//tt:PTZ/tt:XAddr"))
    if not ptz:
        return {"error": "no PTZ service address"}
    body = await cam.call("media", "<trt:GetProfiles/>", "http://www.onvif.org/ver10/media/wsdl/GetProfiles")
    token = next((p.get("token") for p in body.iterfind(".//trt:Profiles", _NS)
                  if p.find("tt:PTZConfiguration", _NS) is not None), None)
    if not token:
        return {"error": "no media profile with a PTZ configuration"}
    tptz = f'xmlns:tptz="{TPTZ}"'

    async def status():
        b = await cam.client.call(ptz, f"<tptz:GetStatus {tptz}><tptz:ProfileToken>{token}</tptz:ProfileToken>"
                                       f"</tptz:GetStatus>", f"{TPTZ}/GetStatus")
        pt, z = b.find(".//tt:Position/tt:PanTilt", _NS), b.find(".//tt:Position/tt:Zoom", _NS)
        return ({"x": float(pt.get("x")), "y": float(pt.get("y"))} if pt is not None else None,
                {"x": float(z.get("x"))} if z is not None else None, text(b, ".//tt:MoveStatus/tt:PanTilt"))

    log = {"profile": token, "events": []}

    def mark(what):
        log["events"].append({"at": datetime.now(timezone.utc).isoformat(), "what": what})

    pt0, z0, _ = await status()
    log["start_position"] = {"pan_tilt": pt0, "zoom": z0}
    mark("nudge")
    await cam.client.call(ptz, f'<tptz:RelativeMove {tptz}><tptz:ProfileToken>{token}</tptz:ProfileToken>'
                               f'<tptz:Translation><tt:PanTilt x="{pan}" y="0"/></tptz:Translation></tptz:RelativeMove>',
                          f"{TPTZ}/RelativeMove")
    await asyncio.sleep(hold_s)
    pt1, _, _ = await status()
    log["moved_position"] = pt1
    mark("return")
    zoom = f'<tt:Zoom x="{z0["x"]}"/>' if z0 else ""
    await cam.client.call(ptz, f'<tptz:AbsoluteMove {tptz}><tptz:ProfileToken>{token}</tptz:ProfileToken>'
                               f'<tptz:Position><tt:PanTilt x="{pt0["x"]}" y="{pt0["y"]}"/>{zoom}</tptz:Position>'
                               f'</tptz:AbsoluteMove>', f"{TPTZ}/AbsoluteMove")
    await asyncio.sleep(hold_s)
    pt2, z2, _ = await status()
    log["end_position"] = {"pan_tilt": pt2, "zoom": z2}
    log["back_to_start"] = bool(pt2 and abs(pt2["x"] - pt0["x"]) < 0.01 and abs(pt2["y"] - pt0["y"]) < 0.01)
    mark("done")
    return log


FILTERS = {
    "motion-only": "tns1:VideoSource/MotionAlarm",
    "motion|input|tamper": "tns1:VideoSource/MotionAlarm|tns1:Device/Trigger/DigitalInput|tns1:VideoSource/GlobalSceneChange//.",
    "ruleengine-subtree": "tns1:RuleEngine//.",
}


async def topic_filters(cam: Camera, seconds: int = 20) -> dict:
    """Does the camera honour a TopicExpression filter (ConcreteSet)? For each filter: subscribe with it, ask for the
    current states, pull for `seconds`, list the topics that arrived. A camera that ignores the filter sends
    everything (the integration must then filter itself); one that refuses it answers a fault."""
    import time
    from collections import Counter

    await cam.clock()
    await cam.services()
    out = {}
    for name, expr in [("none", None), *FILTERS.items()]:
        try:
            sub = await cam.subscribe(60, topic_filter=expr)
        except SoapError as exc:
            out[name] = {"filter": expr, "subscribe": f"{exc.kind}: {exc.message[:120]}"}
            continue
        topics = Counter()
        try:
            try:
                await cam.sync_point(sub)
            except SoapError:
                pass
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                notes, _ = await cam.pull(sub, 5)
                topics.update(n.topic for n in notes)
        finally:
            try:
                await cam.unsubscribe(sub)
            except SoapError:
                pass
        out[name] = {"filter": expr, "messages": sum(topics.values()), "topics": dict(topics.most_common())}
    return out


async def axis_virtual_input(cam: Camera, port: int = 1, times: int = 3, hold_s: float = 3.0, gap_s: float = 6.0) -> dict:
    """A controlled input-type trigger on AXIS (VAPIX, not ONVIF): activate / deactivate a virtual input. The camera
    publishes tns1:Device/IO/VirtualInput (active 1 / 0), the same shape as a real door contact on a digital input.
    Nothing physical changes (unlike a relay). Times are logged (our clock, UTC) for `listen` matching."""
    import asyncio

    import httpx

    auth = httpx.DigestAuth(cam.username or "", cam.password or "")
    base = f"http://{cam.host}:{cam.port}/axis-cgi/virtualinput"
    log = {"port": port, "events": []}
    async with httpx.AsyncClient(timeout=8) as http:
        for _ in range(times):
            for action in ("activate", "deactivate"):
                at = datetime.now(timezone.utc).isoformat()
                r = await http.get(f"{base}/{action}.cgi", params={"schemaversion": 1, "port": port}, auth=auth)
                log["events"].append({"at": at, "what": action, "http": r.status_code, "body": r.text.strip()[:120]})
                await asyncio.sleep(hold_s if action == "activate" else gap_s)
    log["events"].append({"at": datetime.now(timezone.utc).isoformat(), "what": "done"})
    return log


TIMG = "http://www.onvif.org/ver20/imaging/wsdl"


async def imaging_flash(cam: Camera, times: int = 2, hold_s: float = 6.0, gap_s: float = 20.0) -> dict:
    """A controlled scene-change trigger for cameras without PTZ: read the image Brightness, set it far away for
    `hold_s`, then restore the exact value read. A sudden whole-image change should fire motion and/or scene-change
    (tamper) events. Times logged for `listen` matching; the camera ends with its original brightness."""
    import asyncio

    from .soap import NS as _NS
    from .soap import text

    await cam.clock()
    svcs = await cam.services()
    img = next((s["xaddr"] for ns, s in svcs.items() if ns == TIMG), None)
    if not img:
        b = await cam.client.call(cam.device_url, "<tds:GetCapabilities><tds:Category>Imaging</tds:Category>"
                                                  "</tds:GetCapabilities>",
                                  "http://www.onvif.org/ver10/device/wsdl/GetCapabilities")
        img = cam.fix_addr(text(b, ".//tt:Imaging/tt:XAddr"))
    # the video source token from the first profile (Illustra Pro4 SS010.26 refuses GetVideoSources)
    b = await cam.call("media", "<trt:GetProfiles/>", "http://www.onvif.org/ver10/media/wsdl/GetProfiles")
    vs = text(b, ".//tt:VideoSourceConfiguration/tt:SourceToken")
    ns = f'xmlns:timg="{TIMG}"'
    opts = await cam.client.call(img, f"<timg:GetOptions {ns}><timg:VideoSourceToken>{vs}</timg:VideoSourceToken>"
                                      f"</timg:GetOptions>", f"{TIMG}/GetOptions")
    lo, hi = float(text(opts, ".//tt:Brightness/tt:Min", "0")), float(text(opts, ".//tt:Brightness/tt:Max", "100"))
    cur = await cam.client.call(img, f"<timg:GetImagingSettings {ns}><timg:VideoSourceToken>{vs}"
                                     f"</timg:VideoSourceToken></timg:GetImagingSettings>", f"{TIMG}/GetImagingSettings")
    original = text(cur, ".//tt:Brightness")
    if original is None:
        return {"error": "camera reports no Brightness"}
    far = lo if float(original) - lo > hi - float(original) else hi
    log = {"video_source": vs, "brightness": {"original": original, "flash": far, "range": [lo, hi]}, "events": []}

    async def set_brightness(value):
        await cam.client.call(img, f"<timg:SetImagingSettings {ns}><timg:VideoSourceToken>{vs}</timg:VideoSourceToken>"
                                   f"<timg:ImagingSettings><tt:Brightness>{value}</tt:Brightness></timg:ImagingSettings>"
                                   f"<timg:ForcePersistence>false</timg:ForcePersistence></timg:SetImagingSettings>",
                              f"{TIMG}/SetImagingSettings")

    try:
        for _ in range(times):
            log["events"].append({"at": datetime.now(timezone.utc).isoformat(), "what": "flash"})
            await set_brightness(far)
            await asyncio.sleep(hold_s)
            log["events"].append({"at": datetime.now(timezone.utc).isoformat(), "what": "restore"})
            await set_brightness(original)
            await asyncio.sleep(gap_s)
    finally:
        await set_brightness(original)
        after = await cam.client.call(img, f"<timg:GetImagingSettings {ns}><timg:VideoSourceToken>{vs}"
                                           f"</timg:VideoSourceToken></timg:GetImagingSettings>",
                                      f"{TIMG}/GetImagingSettings")
        log["restored"] = text(after, ".//tt:Brightness") == original
        log["events"].append({"at": datetime.now(timezone.utc).isoformat(), "what": "done"})
    return log
