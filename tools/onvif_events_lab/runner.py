"""Lab runs: probe (what each camera offers), listen (real events over time), limits (subscription slots).

Each run writes machine-readable results (JSON / JSONL) under `results/`; `report.py` turns them into Markdown.
Failures never stop a run: every stage of every camera records its own error.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .camera import Camera, Subscription, termination_seconds
from .inventory import public
from .soap import NS, SoapError, parse_time

log = logging.getLogger("lab")


def _cam(c: dict, timeout: float) -> Camera:
    return Camera(id=c["id"], name=c["name"], host=c["host"], port=c.get("port") or 80, username=c.get("username"),
                  password=c.get("password"), timeout=timeout)


def _err(exc: Exception) -> dict:
    if isinstance(exc, SoapError):
        return {"kind": exc.kind, "message": exc.message, "fault": exc.fault_code}
    return {"kind": type(exc).__name__, "message": str(exc)[:300]}


async def _stage(result: dict, name: str, coro):
    t = time.perf_counter()
    try:
        value = await coro
        result["stages"][name] = {"ok": True, "ms": round((time.perf_counter() - t) * 1000)}
        return value
    except Exception as exc:  # noqa: BLE001 - every failure is a finding
        result["stages"][name] = {"ok": False, "ms": round((time.perf_counter() - t) * 1000), **_err(exc)}
        return None


# ---------------------------------------------------------------- probe


async def probe_one(c: dict, raw_dir: Path, timeout: float, pull_seconds: int) -> dict:
    res = {"camera": public(c), "stages": {}, "started": datetime.now(timezone.utc).isoformat()}
    async with _cam(c, timeout) as cam:
        res["clock"] = await _stage(res, "clock", cam.clock())
        res["identity"] = await _stage(res, "identity", cam.identity())
        if res["identity"] is None and res["clock"] is None:
            res["reachable"] = False
            return res
        res["reachable"] = True
        svcs = await _stage(res, "services", cam.services())
        res["services"] = {ns: {k: v for k, v in s.items() if k != "caps"} | {"caps": s.get("caps")}
                           for ns, s in (svcs or {}).items()}
        res["has_events_service"] = "events" in cam.xaddrs
        ep = await _stage(res, "event_properties", cam.event_properties())
        if ep:
            topics, meta, raw = ep
            res["event_meta"] = meta
            res["topics"] = [t.as_dict() for t in topics]
            (raw_dir / f"{c['id']}-topicset.xml").write_text(raw, encoding="utf-8")
        res["pullpoint"] = await _pullpoint_check(cam, res, pull_seconds)
        res["analytics"] = await _stage(res, "analytics", cam.analytics())
        res["io"] = await _stage(res, "io", cam.io_ports())
        res["soap"] = {k: v for k, v in cam.client.stats.items() if k != "ms"} | {
            "median_ms": statistics.median(cam.client.stats["ms"]) if cam.client.stats["ms"] else None}
    return res


async def _pullpoint_check(cam: Camera, res: dict, pull_seconds: int) -> dict | None:
    """Subscribe, ask for the current states (SetSynchronizationPoint), pull for a few seconds, renew, unsubscribe."""
    sub = await _stage(res, "subscribe", cam.subscribe(60))
    if sub is None:
        return None
    out = {"granted_s": termination_seconds(sub), "ref_params": bool(sub.ref_params), "messages": [],
           "sync_point": None, "renew": None, "unsubscribe": None}
    try:
        first = await _stage(res, "pull_first", cam.pull(sub, 2))
        if first:
            out["messages"] += [n.as_dict() for n in first[0]]
        out["sync_point"] = (await _stage(res, "sync_point", cam.sync_point(sub))) is None and \
            res["stages"]["sync_point"]["ok"]
        deadline = time.monotonic() + pull_seconds
        while time.monotonic() < deadline:
            got = await _stage(res, "pull", cam.pull(sub, min(5, max(1, int(deadline - time.monotonic())))))
            if got is None:
                break
            out["messages"] += [n.as_dict() for n in got[0]]
        out["renew"] = (await _stage(res, "renew", cam.renew(sub, 60))) is not None
    finally:
        await _stage(res, "unsubscribe", cam.unsubscribe(sub))
        out["unsubscribe"] = res["stages"]["unsubscribe"]["ok"]
    return out


async def probe(cams: list[dict], out_dir: Path, concurrency: int = 6, timeout: float = 8.0,
                pull_seconds: int = 8) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_dir = out_dir / f"probe-{stamp}-raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)

    async def one(c):
        async with sem:
            t = time.perf_counter()
            r = await probe_one(c, raw_dir, timeout, pull_seconds)
            r["seconds"] = round(time.perf_counter() - t, 1)
            ok = r.get("reachable") and r["stages"].get("event_properties", {}).get("ok")
            log.info("probe %-4s %-28s %s (%s topics, %.0f s)", c["id"], c["name"][:28], "OK " if ok else "--",
                     len(r.get("topics") or []), r["seconds"])
            return r

    results = await asyncio.gather(*(one(c) for c in cams))
    path = out_dir / f"probe-{stamp}.json"
    path.write_text(json.dumps({"kind": "probe", "at": stamp, "cameras": results}, indent=1), encoding="utf-8")
    return path


# ---------------------------------------------------------------- listen


async def listen_one(c: dict, deadline: float, sink, timeout: float, renew_every: int = 30) -> dict:
    """Keep one PullPoint subscription alive until `deadline`; reconnect with back-off on any failure."""
    stats = {"camera": public(c), "messages": 0, "subscriptions": 0, "reconnects": 0, "renewals": 0,
             "renew_failures": 0, "errors": Counter(), "latency_s": [], "first_error": None}
    backoff = 5
    async with _cam(c, timeout) as cam:
        try:
            await cam.clock()
            await cam.services()
        except Exception as exc:  # noqa: BLE001
            stats["first_error"] = _err(exc)
            if "events" not in cam.xaddrs:
                return stats
        while time.monotonic() < deadline:
            sub: Subscription | None = None
            try:
                sub = await cam.subscribe(60)
                stats["subscriptions"] += 1
                if stats["subscriptions"] > 1:
                    stats["reconnects"] += 1
                try:
                    await cam.sync_point(sub)
                except SoapError as exc:
                    stats["errors"][f"sync_point:{exc.kind}"] += 1
                last_renew = time.monotonic()
                backoff = 5
                while time.monotonic() < deadline:
                    wait = int(max(1, min(10, deadline - time.monotonic())))
                    notes, _meta = await cam.pull(sub, wait)
                    recv = datetime.now(timezone.utc)
                    for n in notes:
                        cam_t = parse_time(n.utc_time)
                        lat = None
                        if cam_t:
                            lat = round((recv - cam_t).total_seconds() + cam.client.offset, 2)
                            if n.operation != "Initialized":
                                stats["latency_s"].append(lat)
                        stats["messages"] += 1
                        sink({"camera_id": c["id"], "camera": c["name"], "recv": recv.isoformat(), "latency_s": lat,
                              "offset_s": round(cam.client.offset, 1), **n.as_dict()})
                    if time.monotonic() - last_renew >= renew_every:
                        try:
                            await cam.renew(sub, 60)
                            stats["renewals"] += 1
                        except SoapError as exc:
                            stats["renew_failures"] += 1
                            stats["errors"][f"renew:{exc.kind}"] += 1
                            raise
                        last_renew = time.monotonic()
            except Exception as exc:  # noqa: BLE001
                e = _err(exc)
                stats["errors"][f"{e['kind']}"] += 1
                stats["first_error"] = stats["first_error"] or e
                await asyncio.sleep(min(backoff, max(0, deadline - time.monotonic())))
                backoff = min(backoff * 2, 60)
            finally:
                if sub is not None:
                    try:
                        await cam.unsubscribe(sub)
                    except Exception:  # noqa: BLE001
                        stats["errors"]["unsubscribe"] += 1
    stats["errors"] = dict(stats["errors"])
    return stats


async def listen(cams: list[dict], out_dir: Path, minutes: float, timeout: float = 8.0) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / f"listen-{stamp}.jsonl"
    deadline = time.monotonic() + minutes * 60
    f = events_path.open("w", encoding="utf-8")
    counts = Counter()

    def sink(row):
        f.write(json.dumps(row) + "\n")
        f.flush()
        counts[row["camera_id"]] += 1

    async def progress():
        while time.monotonic() < deadline:
            await asyncio.sleep(60)
            log.info("listen: %d messages so far from %d cameras, %.0f min left", sum(counts.values()), len(counts),
                     max(0, deadline - time.monotonic()) / 60)

    prog = asyncio.create_task(progress())
    try:
        stats = await asyncio.gather(*(listen_one(c, deadline, sink, timeout) for c in cams))
    finally:
        prog.cancel()
        f.close()
    summary = summarize_listen(stats, events_path, minutes)
    sum_path = out_dir / f"listen-{stamp}.json"
    sum_path.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return sum_path, events_path


def summarize_listen(stats: list[dict], events_path: Path, minutes: float) -> dict:
    by_cam = defaultdict(lambda: {"topics": Counter(), "kinds": Counter(), "changes": Counter(), "on": Counter()})
    for line in events_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        b = by_cam[row["camera_id"]]
        b["topics"][row["topic"]] += 1
        b["kinds"][row["kind"]] += 1
        if row.get("operation") != "Initialized":
            b["changes"][row["kind"]] += 1
            if row.get("state") is True:
                b["on"][row["kind"]] += 1
    out = []
    for s in stats:
        cid = s["camera"]["id"]
        lat = s.pop("latency_s")
        b = by_cam.get(cid)
        out.append({**s, "latency": _pct(lat), "topics": dict(b["topics"]) if b else {},
                    "kinds": dict(b["kinds"]) if b else {}, "changes": dict(b["changes"]) if b else {},
                    "activations": dict(b["on"]) if b else {}})
    return {"kind": "listen", "minutes": minutes, "events_file": events_path.name, "cameras": out}


def _pct(values: list[float]) -> dict | None:
    if not values:
        return None
    v = sorted(values)
    return {"n": len(v), "p50": v[len(v) // 2], "p95": v[min(len(v) - 1, int(len(v) * 0.95))], "max": v[-1],
            "min": v[0]}


# ---------------------------------------------------------------- limits


async def limits(c: dict, out_dir: Path, maximum: int = 6, timeout: float = 8.0) -> Path:
    """How many PullPoint subscriptions the camera accepts at once (at most `maximum`; all are removed after).
    Other systems already subscribed (e.g. another VMS) use slots too, so this is 'free slots now'."""
    subs, result = [], {"camera": public(c), "maximum_tried": maximum, "accepted": 0, "refused": None}
    async with _cam(c, timeout) as cam:
        await cam.clock()
        await cam.services()
        try:
            for _ in range(maximum):
                try:
                    subs.append(await cam.subscribe(30))
                    result["accepted"] += 1
                except SoapError as exc:
                    result["refused"] = _err(exc)
                    break
            # are all still usable?
            alive = 0
            for s in subs:
                try:
                    await cam.pull(s, 1)
                    alive += 1
                except SoapError:
                    pass
            result["usable_after"] = alive
        finally:
            removed = 0
            for s in subs:
                try:
                    await cam.unsubscribe(s)
                    removed += 1
                except SoapError:
                    pass
            result["unsubscribed"] = removed
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"limits-{c['id']}-{stamp}.json"
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return path
