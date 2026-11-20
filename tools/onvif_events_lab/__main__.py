"""ONVIF events lab: find out what event support real cameras have before Shah-NVR uses it.

    python -m onvif_events_lab export  --central C:\\Shah-NVR\\Shah-NVR\\central_manager
    python -m onvif_events_lab probe   [--only 3,7] [--concurrency 6]
    python -m onvif_events_lab listen  --minutes 30 [--only ...]
    python -m onvif_events_lab limits  --only 7 [--max 6]
    python -m onvif_events_lab diagnose --only 6         (Renew / Unsubscribe variants)
    python -m onvif_events_lab ptz-nudge --only 9        (controlled trigger; the camera returns to its position)
    python -m onvif_events_lab filters --only 9          (does the camera honour topic filters?)
    python -m onvif_events_lab axis-vinput --only 241    (AXIS virtual input on/off x3: an input-type trigger)
    python -m onvif_events_lab imaging-flash --only 222  (brightness far off 6 s x2, then restored: scene change)
    python -m onvif_events_lab report  [--out report.md]

Run from the folder that holds the `onvif_events_lab` package (or from the repo root as `tools.onvif_events_lab`).
Files: `cameras.json` (has credentials; stays on the machine) and `results/` (no credentials).
See docs/ONVIF_EVENTS_LAB.md.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import warnings
from pathlib import Path

from . import inventory, report, runner


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="onvif_events_lab", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["export", "probe", "listen", "limits", "diagnose", "ptz-nudge",
                                                   "filters", "axis-vinput", "imaging-flash", "report"])
    ap.add_argument("--cameras", type=Path, default=Path("cameras.json"))
    ap.add_argument("--results", type=Path, default=Path("results"))
    ap.add_argument("--central", type=Path, help="central_manager folder (export)")
    ap.add_argument("--only", help="camera ids, comma separated")
    ap.add_argument("--include-disabled", action="store_true", help="also cameras disabled in Shah-NVR")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=8.0, help="seconds per SOAP request")
    ap.add_argument("--pull-seconds", type=int, default=8, help="probe: seconds to pull after subscribing")
    ap.add_argument("--minutes", type=float, default=10, help="listen: how long")
    ap.add_argument("--max", type=int, default=6, help="limits: most subscriptions to try")
    ap.add_argument("--out", type=Path, help="report: write here instead of stdout")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    warnings.filterwarnings("ignore")
    only = [int(x) for x in a.only.split(",")] if a.only else None
    a.results.mkdir(parents=True, exist_ok=True)

    if a.command == "export":
        if not a.central:
            ap.error("--central is required for export")
        cams = asyncio.run(inventory.export(a.central, a.cameras))
        print(f"{len(cams)} cameras -> {a.cameras} ({sum(c['onvif_known'] for c in cams)} with a known ONVIF address)")
        for c in cams:
            print(f"  {c['id']:>4} {c['name'][:32]:<32} {c['host']}:{c['port']}  {c['manufacturer'] or ''} "
                  f"{c['model'] or ''}{'  PTZ' if c['has_ptz'] else ''}{'' if c['enabled'] else '  (disabled)'}")
        return 0
    if a.command == "report":
        md = report.build(a.results)
        if a.out:
            a.out.write_text(md, encoding="utf-8")
            print(f"report -> {a.out}")
        else:
            sys.stdout.write(md)
        return 0

    cams = inventory.load(a.cameras, only, enabled_only=not a.include_disabled)
    if not cams:
        print("no cameras selected", file=sys.stderr)
        return 2
    if a.command == "probe":
        path = asyncio.run(runner.probe(cams, a.results, a.concurrency, a.timeout, a.pull_seconds))
    elif a.command == "listen":
        path, events = asyncio.run(runner.listen(cams, a.results, a.minutes, a.timeout))
        print(f"events -> {events}")
    elif a.command == "ptz-nudge":
        import json
        from datetime import datetime

        from . import diagnose
        from .runner import _cam

        async def nudge(c):
            async with _cam(c, a.timeout) as cam:
                return await diagnose.ptz_nudge(cam)

        result = {c["id"]: {"camera": c["name"], **asyncio.run(nudge(c))} for c in cams}
        path = a.results / f"ptz-nudge-{datetime.now():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(json.dumps(result, indent=1))
    elif a.command == "imaging-flash":
        import json
        from datetime import datetime

        from . import diagnose
        from .runner import _cam

        async def flash(c):
            async with _cam(c, a.timeout) as cam:
                return await diagnose.imaging_flash(cam)

        result = {c["id"]: {"camera": c["name"], **asyncio.run(flash(c))} for c in cams}
        path = a.results / f"ptz-nudge-flash-{datetime.now():%Y%m%d-%H%M%S}.json"  # same shape: matched by report
        path.write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(json.dumps(result, indent=1))
    elif a.command == "axis-vinput":
        import json
        from datetime import datetime

        from . import diagnose
        from .runner import _cam

        async def vinput(c):
            async with _cam(c, a.timeout) as cam:
                return await diagnose.axis_virtual_input(cam)

        result = {c["id"]: {"camera": c["name"], **asyncio.run(vinput(c))} for c in cams}
        path = a.results / f"ptz-nudge-vinput-{datetime.now():%Y%m%d-%H%M%S}.json"  # same shape: matched by report
        path.write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(json.dumps(result, indent=1))
    elif a.command == "filters":
        import json

        from . import diagnose
        from .runner import _cam

        async def run_filters():
            out = {}
            for c in cams:
                async with _cam(c, a.timeout) as cam:
                    out[c["id"]] = {"camera": c["name"], **await diagnose.topic_filters(cam, a.pull_seconds)}
            return out

        result = asyncio.run(run_filters())
        path = a.results / f"filters-{'-'.join(str(c['id']) for c in cams)}.json"
        path.write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(json.dumps(result, indent=1))
    elif a.command == "diagnose":
        import json

        from . import diagnose
        from .runner import _cam

        async def run_all():
            out = {}
            for c in cams:
                async with _cam(c, a.timeout) as cam:
                    out[c["id"]] = {"camera": c["name"], **await diagnose.renew_unsubscribe_variants(cam)}
            return out

        result = asyncio.run(run_all())
        path = a.results / f"diagnose-{'-'.join(str(c['id']) for c in cams)}.json"
        path.write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(json.dumps(result, indent=1))
    else:
        path = None
        for c in cams:
            path = asyncio.run(runner.limits(c, a.results, a.max, a.timeout))
            print(path.read_text(encoding="utf-8"))
    print(f"results -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
