"""Pure editor rules matching nvr_client/src/lib/encoder.ts and node validation.

Alternative option blocks are deliberately never merged: a complete proposal must
fit one advertised block. Unadvertised values can only be preserved unchanged.
"""
import json
import math

BOUNDS = {"fps": "fps_range", "bitrate_kbps": "bitrate_range", "gop": "gop_range", "quality": "quality_range"}
LABELS = {"encoding": "Codec", "resolution": "Resolution", "fps": "Frame rate (fps)",
          "bitrate_kbps": "Bitrate limit (kbps)", "gop": "GOP (frames)", "quality": "Quality",
          "rate_control": "Rate control", "codec_profile": "Codec profile"}


def changed_values(current, draft):
    return {k: v for k, v in draft.items() if v is not None and v != current.get(k)}


def option_errors(option, current, target):
    changes = changed_values(current, target)
    switched = "encoding" in changes
    errors = []
    resolutions = option.get("resolutions") or []
    if (resolutions or switched or {"width", "height"} & changes.keys()) and [target.get("width"), target.get("height")] not in resolutions:
        errors.append("Resolution is not supported by this option")
    for key, bounds in BOUNDS.items():
        value = target.get(key)
        if value is None:
            continue
        limits = option.get(bounds)
        rates = (option.get("frame_rates") or []) if key == "fps" else []
        valid = isinstance(value, (int, float)) and math.isfinite(value) and (value in rates if rates else limits[0] <= value <= limits[1] if limits else key not in changes and not switched)
        if not valid:
            errors.append(f"{LABELS[key]} is outside this option's advertised limits (or limits are unavailable)")
    for key, choices in (("codec_profile", "codec_profiles"), ("rate_control", "rate_controls")):
        value, allowed = target.get(key), option.get(choices) or []
        if value is not None and (allowed or key in changes or switched) and value not in allowed:
            errors.append(f"{LABELS[key]} is not supported by this option")
    return errors


def alternatives(options, encoding):
    seen, result = set(), []
    for option in options:
        key = json.dumps(option, sort_keys=True)
        if option.get("encoding") == encoding and key not in seen:
            seen.add(key)
            result.append(option)
    return result


def preferred_option(options, current, draft):
    return min(range(len(options)), key=lambda i: (len(option_errors(options[i], current, draft)),
               [draft.get("width"), draft.get("height")] not in (options[i].get("resolutions") or [])), default=0)


def validation(state, draft):
    current = state.get("current") or {}
    changes = changed_values(current, draft)
    errors = []
    for key, value in changes.items():
        if current.get(key) is None:
            errors.append(f"{key} is not exposed by this camera")
        if key in (*BOUNDS, "width", "height"):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or (key != "quality" and value <= 0):
                errors.append(f"{key} must be a valid number")
            elif (key in ("width", "height", "bitrate_kbps", "gop") or (key == "fps" and state.get("api") == "trt")) and value != int(value):
                errors.append(f"{key} must be an integer")
    options = alternatives(state.get("options", []), draft.get("encoding"))
    if not options:
        errors.append("The camera does not advertise supported options for this codec.")
    elif not errors:
        errors.extend(option_errors(options[preferred_option(options, current, draft)], current, draft))
    return errors


def preset_values(current, option, preset):
    out = dict(current)
    best, low = preset == "Best quality", preset == "Low-bandwidth substream"
    limits, bitrate = option.get("bitrate_range"), current.get("bitrate_kbps")
    if limits and bitrate is not None and bitrate < 1_000_000:
        out["bitrate_kbps"] = math.floor(max(limits[0], min(limits[1], bitrate * (1.5 if best else .25 if low else .6))) + .5)
    fps = current.get("fps")
    if fps is not None:
        desired = fps if best else 10 if low else 15
        rates, limits = option.get("frame_rates") or [], option.get("fps_range")
        if rates:
            out["fps"] = max((f for f in rates if f <= desired), default=min(rates))
        elif limits:
            out["fps"] = max(limits[0], min(limits[1], desired))
    if low and option.get("resolutions"):
        out["width"], out["height"] = min(option["resolutions"], key=lambda r: r[0] * r[1])
    if best and option.get("quality_range") and current.get("quality") is not None:
        out["quality"] = option["quality_range"][1]
    return out


def storage_text(kbps):
    return f"{kbps / 1000 * 10.8:.1f} GB/day" if isinstance(kbps, (int, float)) and math.isfinite(kbps) and 0 < kbps < 1_000_000 else "unknown"


def fields(state, draft, option):
    current = state.get("current") or {}
    result = []
    for key, label in LABELS.items():
        value = draft.get(key)
        choices, hint = [], ""
        exposed = current.get(key) is not None
        if key == "encoding":
            choices = list(dict.fromkeys(o["encoding"] for o in state.get("options", []) if o["encoding"] in ("H264", "H265")))
        elif key == "resolution":
            value = f'{draft.get("width")}x{draft.get("height")}' if draft.get("width") else ""
            exposed = current.get("width") is not None and current.get("height") is not None
            choices = [f"{w}x{h}" for w, h in option.get("resolutions", [])]
        elif key in BOUNDS:
            limits = option.get(BOUNDS[key])
            if key == "fps" and option.get("frame_rates"):
                choices = option["frame_rates"]
                hint = "Advertised frame rates only"
            elif limits:
                hint = f"{limits[0]:g} – {limits[1]:g}"
            else:
                exposed = False
                hint = "Limits not exposed; current value is preserved"
        else:
            choices = option.get("rate_controls" if key == "rate_control" else "codec_profiles") or []
        is_select = key not in BOUNDS or bool(choices)
        allowed = bool(choices) if is_select else bool(option.get(BOUNDS.get(key)))
        # Keep the current value visible even when it is unsupported by this alternative.
        displayed = list(choices)
        if value is not None and value != "" and value not in displayed:
            displayed.insert(0, value)
        result.append({"key": key, "label": label, "value": "" if value is None else str(value),
                       "select": is_select, "enabled": exposed and allowed, "hint": hint,
                       "choices": [{"value": str(v), "label": str(v)} for v in displayed]})
    return result
