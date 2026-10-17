"""Capability-gated encoder edits. Never retry a Set or fall back after sending it."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
import weakref

from fastapi import HTTPException
from lxml import etree

from app.onvif.services import OnvifDevice, _t
from app.onvif.soap import NS, Fault, NotAuthorized, NotSupported, OnvifError

_locks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()


def device_lock(host: str, port: int) -> asyncio.Lock:
    key = (host.lower().rstrip("."), port)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def fail(code: str, message: str, status: int = 422):
    raise HTTPException(status, {"code": code, "message": message})


def number(text):
    try:
        value = float(text)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def codec(text):
    return "H265" if text == "HEVC" else text


def request(ns, action, **fields):
    el = etree.Element(etree.QName(NS[ns], action), nsmap={ns: NS[ns], "tt": NS["tt"]})
    for key, value in fields.items():
        if value is not None:
            etree.SubElement(el, etree.QName(NS[ns], key)).text = str(value)
    return el


async def call(dev, url, el):
    return await dev.soap.call(url, etree.tostring(el, encoding="unicode"))


def current_number(text, field, warnings, *, integer=False, positive=False):
    """Normalize device-reported values, not user input or the original XML.

    Some devices (e.g. Illustra PTZ Media1) report BitrateLimit=0 and no
    bitrate options. This is not a usable limit, nor evidence of unlimited
    bitrate. Expose it as unknown instead of failing response validation.
    Keep write schemas strict and preserve the camera's XML for other edits.
    """
    value = number(text)
    if value is not None and (not positive or value > 0) and (not integer or value.is_integer()):
        return int(value) if integer else value
    if text is not None:
        warning = f"Camera reports an invalid {field}; this field is unavailable and read-only."
        if field == "bitrate limit":
            warning += " Storage estimate is unavailable."
        warnings.append(warning)
    return None


def values(conf, ns, warnings=None):
    warnings = warnings if warnings is not None else []
    rate = conf.find("tt:RateControl", NS)
    mode = rate.get("ConstantBitRate", "false") if rate is not None and ns == "tr2" else None
    # AverageBitRate overrides ConstantBitRate; do not mislabel it as CBR.
    if number(_t(rate, "tt:AverageBitRate")) not in (None, 0):
        mode = None
    return {
        "encoding": codec(_t(conf, "tt:Encoding")),
        "width": current_number(_t(conf, "tt:Resolution/tt:Width"), "width", warnings, integer=True, positive=True),
        "height": current_number(_t(conf, "tt:Resolution/tt:Height"), "height", warnings, integer=True, positive=True),
        "fps": current_number(_t(rate, "tt:FrameRateLimit"), "frame rate", warnings, positive=True),
        "bitrate_kbps": current_number(_t(rate, "tt:BitrateLimit"), "bitrate limit", warnings, integer=True, positive=True),
        "gop": current_number(conf.get("GovLength") if ns == "tr2" else _t(conf, "tt:H264/tt:GovLength"),
                              "GOP", warnings, integer=True, positive=True),
        "quality": current_number(_t(conf, "tt:Quality"), "quality", warnings),
        "codec_profile": conf.get("Profile") if ns == "tr2" else _t(conf, "tt:H264/tt:H264Profile"),
        "rate_control": ("CBR" if mode in ("true", "1") else "VBR") if mode is not None else None,
    }


def limits(el, path):
    lo, hi = number(_t(el, path + "/tt:Min")), number(_t(el, path + "/tt:Max"))
    return [lo, hi] if lo is not None and hi is not None and lo <= hi else None


def parse_options(body, ns):
    out = []
    for opt in body.findall(".//" + ns + ":Options", NS):
        entries = [(codec(_t(opt, "tt:Encoding")), opt)] if ns == "tr2" else [
            ("H264", opt.find("tt:H264", NS))]
        for encoding, detail in entries:
            if detail is None or encoding not in ("H264", "H265"):
                continue
            gop = [number(x) for x in detail.get("GovLengthRange", "").split()]
            bitrate = limits(detail, "tt:BitrateRange")
            if ns == "trt":
                bitrate = limits(opt, "tt:Extension/tt:H264/tt:BitrateRange")
            out.append({
                "encoding": encoding,
                "resolutions": [[int(_t(r, "tt:Width")), int(_t(r, "tt:Height"))]
                                for r in detail.findall("tt:ResolutionsAvailable", NS)],
                "fps_range": limits(detail, "tt:FrameRateRange") if ns == "trt" else None,
                "frame_rates": [float(x) for x in detail.get("FrameRatesSupported", "").split()],
                "bitrate_range": bitrate,
                "gop_range": gop if len(gop) == 2 and None not in gop else limits(detail, "tt:GovLengthRange"),
                "quality_range": limits(opt, "tt:QualityRange"),
                "codec_profiles": detail.get("ProfilesSupported", "").split() if ns == "tr2" else [
                    e.text for e in detail.findall("tt:H264ProfilesSupported", NS) if e.text],
                "rate_controls": ["VBR", "CBR"] if detail.get("ConstantBitRateSupported") in ("true", "1") else [],
            })
    return out


def semantic(el):
    """Namespace-prefix/whitespace-independent revision, including vendor fields."""
    return [el.tag, sorted(el.attrib.items()), (el.text or "").strip(), [semantic(c) for c in el]]


def media_failure_reason(exc):
    """Public diagnostic without echoing arbitrary camera fault text or credentials."""
    status = re.fullmatch(r"HTTP ([45]\d\d)(?:: not a SOAP reply)?", str(exc))
    if status:
        return f"HTTP {status[1]}"
    return "operation not supported" if isinstance(exc, NotSupported) else "camera SOAP fault"


def fallback_warning(stage, reason):
    return (f"Camera advertises Media2, but {stage} failed ({reason}). Using Media1 fallback; "
            "H265 and other encoder settings may be unavailable or differ from the camera's own UI. "
            "These are Media1-reported settings, not an independent measurement of the live stream. "
            "Check the camera's Media2 service and reload before changing settings if they disagree.")


async def read(dev: OnvifDevice, profile_token: str | None, api: str | None = None):
    services = await dev.services()
    candidates = [("tr2", services[NS["tr2"]])] if NS["tr2"] in services else []
    if NS["trt"] in services:
        candidates.append(("trt", services[NS["trt"]]))
    if not candidates:
        candidates = [("trt", dev.device_url)]
    if api:
        candidates = [(ns, url) for ns, url in candidates if ns == api]
    fallback_warnings = []
    for index, (ns, url) in enumerate(candidates):
        stage = "GetProfiles"
        try:
            profiles_body = await call(dev, url, request(ns, "GetProfiles", **({"Type": "All"} if ns == "tr2" else {})))
            profiles, configs = [], {}
            for p in profiles_body.findall(".//" + ns + ":Profiles", NS):
                conf = p.find("tr2:Configurations/tr2:VideoEncoder" if ns == "tr2" else "tt:VideoEncoderConfiguration", NS)
                token = p.get("token")
                profiles.append({"token": token, "name": _t(p, ns + ":Name") or _t(p, "tt:Name"),
                                 "encoder_token": conf.get("token") if conf is not None else None})
                if conf is not None:
                    configs[token] = conf
            state = {"api": ns, "profile_token": profile_token, "profiles": profiles, "options": [],
                     "shared_profiles": [], "warnings": list(fallback_warnings)}
            if not profile_token:
                return state, None, url
            if profile_token not in configs:
                if index + 1 < len(candidates):
                    fallback_warnings.append(fallback_warning("profile lookup", "mapped profile has no Media2 encoder"))
                    continue
                fail("profile_mapping_required", "Select an ONVIF profile that has a video encoder.")
            token = configs[profile_token].get("token")
            if not token:
                raise NotSupported("The profile has no encoder configuration token")
            action = "GetVideoEncoderConfigurations" if ns == "tr2" else "GetVideoEncoderConfiguration"
            stage = action
            reply = await call(dev, url, request(ns, action, ConfigurationToken=token))
            conf = next((e for e in reply.findall(".//" + ns + (":Configurations" if ns == "tr2" else ":Configuration"), NS)
                         if e.get("token") == token), None)
            if conf is None:
                raise NotSupported("The camera did not return the requested encoder configuration")
            current = values(conf, ns, state["warnings"])
            if current["encoding"] not in ("H264", "H265"):
                raise NotSupported("Only H264/H265 encoder configurations are editable")
            try:
                options = await call(dev, url, request(ns, "GetVideoEncoderConfigurationOptions",
                                                      ConfigurationToken=token, ProfileToken=profile_token))
                state["options"] = parse_options(options, ns)
            except (NotSupported, Fault) as exc:
                # A valid Media2 configuration is more authoritative than a legacy
                # Media1 fallback. Missing edit limits must not replace e.g. H265
                # current values with the legacy service's H264 representation.
                label = "Media2" if ns == "tr2" else "Media1"
                state["warnings"].append(
                    f"{label} GetVideoEncoderConfigurationOptions failed ({media_failure_reason(exc)}). "
                    f"Keeping {label}-reported settings; encoder options unavailable and settings are read-only.")
            shared = sorted(p["token"] for p in profiles if p["encoder_token"] == token)
            revision = hashlib.sha256(json.dumps([ns, semantic(conf), shared], sort_keys=True).encode()).hexdigest()
            state.update(encoder_token=token, current=current, revision=revision, shared_profiles=shared,
                         use_count=int(number(_t(conf, "tt:UseCount")) or 0))
            if len(shared) > 1 or state["use_count"] > 1:
                state["warnings"].append("This encoder is shared. All listed ONVIF profiles will change.")
            if current["bitrate_kbps"] and current["bitrate_kbps"] >= 1_000_000:
                state["warnings"].append("Camera reports an unlimited bitrate; storage estimate is unavailable.")
            if number(_t(conf, "tt:RateControl/tt:AverageBitRate")) not in (None, 0):
                for option in state["options"]:
                    option["rate_controls"] = []
                state["warnings"].append("Average bitrate overrides CBR/VBR on this camera; rate mode is read-only.")
            return state, conf, url
        except (NotSupported, Fault) as exc:
            if index + 1 == len(candidates):
                raise
            fallback_warnings.append(fallback_warning(stage, media_failure_reason(exc)))
    raise NotSupported("No compatible media service/profile")


def option_errors(option, target, changes, switched):
    """Check one whole alternative, including advertised limits on unchanged fields.

    Unknown limits can only be preserved on unchanged fields of the same codec.
    Never combine a resolution from one alternative with rates from another.
    """
    errors = []
    resolutions = option.get("resolutions") or []
    if resolutions or switched or {"width", "height"} & changes.keys():
        if [target.get("width"), target.get("height")] not in resolutions:
            errors.append("resolution is not supported")
    for key, bounds in (("fps", "fps_range"), ("bitrate_kbps", "bitrate_range"),
                        ("gop", "gop_range"), ("quality", "quality_range")):
        value = target.get(key)
        if value is None:
            continue
        span = option.get(bounds)
        rates = (option.get("frame_rates") or []) if key == "fps" else []
        if rates:
            valid = value in rates
        elif span:
            valid = span[0] <= value <= span[1]
        else:
            valid = key not in changes and not switched
        if not valid:
            errors.append(f"{key}={value:g} is outside advertised limits (or limits are unavailable)")
    for key, choices in (("codec_profile", "codec_profiles"), ("rate_control", "rate_controls")):
        value = target.get(key)
        allowed = option.get(choices) or []
        if value is not None and (allowed or key in changes or switched) and value not in allowed:
            errors.append(f"{key}={value} is not supported")
    return errors


def validate(state, proposed, acknowledge_shared=False):
    current = state.get("current")
    if not current:
        fail("profile_mapping_required", "Map this stream to an ONVIF profile first.")
    changes = {k: v for k, v in proposed.items() if v is not None and v != current.get(k)}
    if any(current.get(k) is None for k in changes):
        fail("unsupported", "Cannot safely edit a field absent from the current encoder configuration.")
    target = {**current, **changes}
    options = [o for o in state["options"] if o["encoding"] == target["encoding"]]
    if not options:
        fail("unsupported", f"The camera did not advertise encoder options for {target['encoding']}. Reload the encoder.")
    if (len(state["shared_profiles"]) > 1 or state.get("use_count", 0) > 1) and not acknowledge_shared:
        fail("shared_encoder", "Acknowledge the shared encoder before applying.", 409)
    switched = "encoding" in changes
    failures = [option_errors(option, target, changes, switched) for option in options]
    if all(failures):
        # Break ties in favour of the selected resolution, so the message points at
        # e.g. the unsupported frame rate rather than suggesting a resolution change.
        closest_index = min(range(len(options)), key=lambda i: (
            len(failures[i]),
            [target.get("width"), target.get("height")] not in (options[i].get("resolutions") or []),
        ))
        closest = failures[closest_index]
        fail("unsupported", f"No advertised {target['encoding']} option supports the complete settings combination. "
             "Closest option: " + "; ".join(closest) + ".")
    if state["api"] == "trt" and target["fps"] is not None and target["fps"] != int(target["fps"]):
        fail("unsupported", "Media1 requires an integer frame rate.")
    return changes, target


def updated_xml(conf, ns, changes):
    conf = copy.deepcopy(conf)
    paths = {"encoding": "tt:Encoding", "width": "tt:Resolution/tt:Width", "height": "tt:Resolution/tt:Height",
             "fps": "tt:RateControl/tt:FrameRateLimit", "bitrate_kbps": "tt:RateControl/tt:BitrateLimit",
             "quality": "tt:Quality", "gop": "tt:H264/tt:GovLength", "codec_profile": "tt:H264/tt:H264Profile"}
    for key, value in changes.items():
        if ns == "tr2" and key in ("gop", "codec_profile"):
            conf.set("GovLength" if key == "gop" else "Profile", str(value))
        elif key == "rate_control":
            rate = conf.find("tt:RateControl", NS)
            if rate is None:
                fail("unsupported", "RateControl is missing; refusing to invent a configuration.")
            rate.set("ConstantBitRate", str(value == "CBR").lower())
            average = rate.find("tt:AverageBitRate", NS)
            if average is not None:
                average.text = "0"  # otherwise this overrides the user's CBR/VBR selection
        else:
            el = conf.find(paths[key], NS)
            if el is None:
                fail("unsupported", f"{key} is absent from this configuration; cannot safely edit it.")
            el.text = str(int(value)) if isinstance(value, (int, float)) and float(value).is_integer() else str(value)
    conf.tag = etree.QName(NS[ns], "Configuration")
    body = request(ns, "SetVideoEncoderConfiguration")
    body.append(conf)
    if ns == "trt":
        etree.SubElement(body, etree.QName(NS[ns], "ForcePersistence")).text = "true"
    return body


async def apply(dev, profile_token, revision, proposed, acknowledge_shared):
    before, conf, url = await read(dev, profile_token)
    if revision != before.get("revision"):
        fail("stale_encoder", "Settings changed since you loaded them. Reload before applying.", 409)
    changes, target = validate(before, proposed, acknowledge_shared)
    if not changes:
        return {"outcome": "verified", "before": before, "after": before, "message": "Already configured; no write sent."}
    body = updated_xml(conf, before["api"], changes)
    error = None
    try:
        await call(dev, url, body)  # exactly one Set; never a blind retry or write fallback
    except NotAuthorized:
        raise
    except OnvifError as exc:
        error = exc.code
    try:
        after, _, _ = await read(dev, profile_token, api=before["api"])
    except (OnvifError, HTTPException):
        return {"outcome": "unknown", "before": before, "after": None,
                "message": "Write outcome unknown. Read the camera again before any further action; do not retry blindly."}
    matches = all(after["current"].get(k) == v for k, v in target.items() if v is not None)
    return {"outcome": "verified" if matches else ("unknown" if error else "mismatch"),
            "before": before, "after": after,
            "message": "Camera settings verified by readback." if matches else
                       "Readback differs from the request. Review actual values; no automatic retry or rollback was sent."}
