"""Storage volumes on this node: where recordings may go, their health, and where to write now.

* The configuration (paths, fill order, caps, accepting) comes from central in every heartbeat response
  and is cached in KeyValue, so recording continues while central is down.
* The node's own RECORDINGS_DIR is always a volume (the default one, key None).
* `storage_tick` (its own loop) checks every volume in worker threads with a timeout: a dead network
  share can take tens of seconds to fail and must never block heartbeats or the event loop.
* Network share credentials are never sent by central: they are saved on this PC with
  `cmdkey /add:<host> /user:<user> /pass:<password>` for the Windows user that runs the media node.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

import psutil
from tortoise.functions import Sum

from app.node.models import KeyValue
from app.storage.utils import (
    ERROR,
    OK,
    PENDING,
    UNAVAILABLE,
    Volume,
    all_full,
    classify_error,
    pick_target,
    update_full,
)
from settings.settings import settings

logger = logging.getLogger("node.storage")

KV_VOLUMES = "volumes"
KV_LEGACY_QUOTA = "storage_quota_bytes"  # node-wide cap from centrals older than storage volumes
CHECK_TIMEOUT_SECONDS = 10
PROBE_EVERY_SECONDS = 60
PROBE_NAME = ".shahnvr-write-test"


def _check_folder(path: Path, probe: bool) -> dict:
    """Runs in a worker thread: create the folder if needed, measure the disk, optionally test a write."""
    path.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    if probe:
        test = path / PROBE_NAME
        test.write_bytes(b"ok")
        test.unlink()
    return {"total": usage.total, "free": usage.free, "used_percent": round(100 * usage.used / usage.total, 2)}


def local_drives() -> list[dict]:
    """Fixed local drives (for "Add storage" in central). Network/optical drives are left out."""
    drives = []
    for part in psutil.disk_partitions(all=False):
        opts = part.opts.lower()
        if "cdrom" in opts or "remote" in opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        drives.append({"root": part.mountpoint, "label": None, "fstype": part.fstype,
                       "total_bytes": usage.total, "free_bytes": usage.free})
    return drives


class Storage:
    def __init__(self) -> None:
        self.volumes: dict[int | None, Volume] = {None: self._default_volume()}
        self.target_key: int | None = None

    @staticmethod
    def _default_volume(central_id: int | None = None, quota: int | None = None, position: int = 0,
                        accepting: bool = True) -> Volume:
        return Volume(key=None, central_id=central_id, path=settings.RECORDINGS_DIR, position=position,
                      quota_bytes=quota, accepting=accepting, is_default=True)

    # ------------------------------------------------------------------ configuration
    async def load(self) -> None:
        config = await KeyValue.get_value(KV_VOLUMES)
        legacy = await KeyValue.get_value(KV_LEGACY_QUOTA)
        self._build(config, legacy)
        logger.info("Storage volumes: %s", ", ".join(f"{v.path} (cap {v.quota_bytes})" for v in self.ordered()))

    def _build(self, config: list[dict] | None, legacy_quota: int | None) -> None:
        previous = self.volumes
        volumes: dict[int | None, Volume] = {}
        default_cfg = next((c for c in config or [] if c.get("is_default")), None)
        if default_cfg:
            volumes[None] = self._default_volume(default_cfg["id"], default_cfg["quota_bytes"],
                                                 default_cfg["position"], default_cfg["accepting"])
        else:
            volumes[None] = self._default_volume(quota=legacy_quota)
        for c in config or []:
            if c.get("is_default"):
                continue
            volumes[c["id"]] = Volume(key=c["id"], central_id=c["id"], path=Path(c["path"]),
                                      position=c["position"], quota_bytes=c["quota_bytes"], accepting=c["accepting"])
        for key, v in volumes.items():  # keep health of volumes whose path did not change
            old = previous.get(key)
            if old is not None and old.path == v.path:
                v.state, v.detail, v.full, v.last_probe = old.state, old.detail, old.full, old.last_probe
                v.total_bytes, v.free_bytes, v.disk_used_percent = old.total_bytes, old.free_bytes, old.disk_used_percent
                v.recordings_bytes = old.recordings_bytes
        self.volumes = volumes

    async def apply_config(self, config: list[dict] | None, legacy_quota: int | None = None) -> None:
        """From the heartbeat response. `config` None/empty = central older than storage volumes."""
        config = config or None
        if config == await KeyValue.get_value(KV_VOLUMES) and legacy_quota == await KeyValue.get_value(KV_LEGACY_QUOTA):
            return
        removed = set(self.volumes) - {None} - {c["id"] for c in config or [] if not c.get("is_default")}
        self._build(config, legacy_quota)
        await KeyValue.set_value(KV_VOLUMES, config)
        await KeyValue.set_value(KV_LEGACY_QUOTA, legacy_quota)
        if removed:
            from app.recordings.models import LocalSegment, SkippedFile

            # Removed in central: forget its recordings here too (the files themselves are left alone).
            n = await LocalSegment.filter(volume_id__in=list(removed)).delete()
            await SkippedFile.filter(volume_id__in=list(removed)).delete()
            logger.warning("Storage volume(s) %s removed by central; forgot %s local chunk record(s)", sorted(removed), n)
        logger.info("Storage configuration updated: %s",
                    "; ".join(f"#{v.position} {v.path} cap={v.quota_bytes} accepting={v.accepting}" for v in self.ordered()))
        await self.refresh()

    # ------------------------------------------------------------------ health
    async def _check(self, v: Volume) -> None:
        probe = time.monotonic() - v.last_probe > PROBE_EVERY_SECONDS or v.state != OK
        try:
            info = await asyncio.wait_for(asyncio.to_thread(_check_folder, v.path, probe), CHECK_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a reported state
            state, detail = classify_error(exc if not isinstance(exc, asyncio.TimeoutError) else TimeoutError(),
                                           str(v.path))
            if (state, detail) != (v.state, v.detail):
                logger.warning("Storage %s: %s (%s)", v.path, state, detail)
            v.state, v.detail = state, detail
            return
        if probe:
            v.last_probe = time.monotonic()
        if v.state not in (OK,):
            logger.info("Storage %s: OK", v.path)
        v.state, v.detail = OK, None
        v.total_bytes, v.free_bytes, v.disk_used_percent = info["total"], info["free"], info["used_percent"]

    async def refresh(self) -> None:
        """Health of every volume, recordings size per volume, FULL flags and the write target."""
        from app.recordings.models import LocalSegment

        await asyncio.gather(*(self._check(v) for v in self.volumes.values()))
        rows = await LocalSegment.all().group_by("volume_id").annotate(total=Sum("size_bytes")).values("volume_id", "total")
        sizes = {r["volume_id"]: int(r["total"] or 0) for r in rows}
        for key, v in self.volumes.items():
            v.recordings_bytes = sizes.get(key, 0)
            if v.usable:
                was = v.full
                update_full(v, settings.DISK_MAX_USED_PERCENT, settings.DISK_TARGET_USED_PERCENT)
                if v.full != was:
                    logger.warning("Storage %s is %s", v.path, "FULL" if v.full else "no longer full")
        self._choose_target()

    def _choose_target(self) -> None:
        target = pick_target(list(self.volumes.values()))
        key = target.key if target else None
        if key != self.target_key:
            logger.warning("Recording target: %s -> %s", self.root_of(self.target_key), self.root_of(key))
        self.target_key = key

    # ------------------------------------------------------------------ lookups
    def ordered(self) -> list[Volume]:
        return sorted(self.volumes.values(), key=lambda v: (v.position, v.key is not None, v.key or 0))

    def get(self, key: int | None) -> Volume | None:
        return self.volumes.get(key)

    def root_of(self, key: int | None) -> Path | None:
        v = self.volumes.get(key)
        return v.path if v else None

    def central_id(self, key: int | None) -> int | None:
        v = self.volumes.get(key)
        return v.central_id if v else None

    def key_for_central(self, central_id: int | None) -> int | None:
        """Central volume id -> local key (the default volume's central id maps to None)."""
        if central_id is None:
            return None
        default = self.volumes[None]
        return None if central_id == default.central_id else central_id

    def target(self) -> Volume:
        return self.volumes.get(self.target_key) or self.volumes[None]

    def scan_roots(self) -> list[tuple[int | None, Path]]:
        """Roots worth scanning now (healthy ones; a dead share would block the scanner)."""
        return [(v.key, v.path) for v in self.ordered() if v.usable or v.state == PENDING]

    def all_full(self) -> bool:
        return all_full(list(self.volumes.values()))

    def total_recordings_bytes(self) -> int:
        return sum(v.recordings_bytes for v in self.volumes.values())

    def reports(self) -> list[dict]:
        """For the heartbeat: one entry per volume central knows about."""
        out = []
        for v in self.ordered():
            if v.central_id is None:
                continue
            state = "FULL" if v.usable and v.full else (v.state if v.state in (OK, UNAVAILABLE, ERROR) else "PENDING")
            out.append({
                "id": v.central_id, "state": state, "state_detail": v.detail,
                "total_bytes": v.total_bytes, "free_bytes": v.free_bytes,
                "recordings_bytes": v.recordings_bytes, "writing": v.key == self.target_key,
            })
        return out

    def status(self) -> list[dict]:
        """For the node's own /status endpoint."""
        return [
            {"key": v.key, "central_id": v.central_id, "path": str(v.path), "position": v.position,
             "quota_bytes": v.quota_bytes, "accepting": v.accepting, "state": v.state, "detail": v.detail,
             "full": v.full, "total_bytes": v.total_bytes, "free_bytes": v.free_bytes,
             "recordings_bytes": v.recordings_bytes, "writing": v.key == self.target_key}
            for v in self.ordered()
        ]


storage = Storage()


async def storage_tick() -> None:
    await storage.refresh()
