"""Storage volume rules (pure functions, unit-tested).

Fill in order: recordings go to the first volume (lowest position) that is accepting, healthy and not
full. A volume is FULL at >= 95% of its cap (or when its disk is >= DISK_MAX_USED_PERCENT) and becomes
usable again below 90% (and DISK_TARGET_USED_PERCENT): the hysteresis stops recording from flapping
between two volumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

FULL_AT = 0.95  # of the volume's cap
FREE_BELOW = 0.90

OK, FULL, UNAVAILABLE, ERROR, PENDING = "OK", "FULL", "UNAVAILABLE", "ERROR", "PENDING"

# Windows error codes for network paths (see "System Error Codes").
_UNREACHABLE_WINERRORS = {53, 64, 67, 121, 1231, 1232, 1311}  # path/name not found, net gone, timeout...
_LOGON_WINERRORS = {5, 86, 1326, 1327, 1330, 1331, 1385, 1909}  # access denied, bad user/password...


@dataclass
class Volume:
    """One place this node may record. `key` is what LocalSegment.volume_id stores:
    None = the node's own RECORDINGS_DIR (the default volume), otherwise the central volume id."""

    key: int | None
    central_id: int | None
    path: Path
    position: int = 0
    quota_bytes: int | None = None
    accepting: bool = True
    is_default: bool = False
    # runtime (filled by the health check)
    state: str = PENDING
    detail: str | None = None
    total_bytes: int | None = None
    free_bytes: int | None = None
    disk_used_percent: float | None = None
    recordings_bytes: int = 0
    full: bool = False
    last_probe: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def is_network(self) -> bool:
        return str(self.path).startswith(("\\\\", "//"))

    @property
    def usable(self) -> bool:
        """Healthy: files on it can be read, written and deleted."""
        return self.state in (OK, FULL)


def update_full(volume: Volume, disk_max_percent: float, disk_target_percent: float) -> bool:
    """Recompute `volume.full` with hysteresis; returns the new value."""
    used, quota, disk = volume.recordings_bytes, volume.quota_bytes, volume.disk_used_percent or 0.0
    over_cap = bool(quota) and used >= quota * FULL_AT
    disk_full = disk >= disk_max_percent
    if volume.full:
        under_cap = not quota or used < quota * FREE_BELOW
        volume.full = not (under_cap and disk < disk_target_percent)
    else:
        volume.full = over_cap or disk_full
    return volume.full


def pick_target(volumes: list[Volume]) -> Volume | None:
    """Where new recordings go: the first accepting, healthy, not-full volume in fill order.

    If every accepting healthy volume is full, keep writing to the first of them (cleanup then
    overwrites the oldest recordings). If none is healthy, fall back to the default volume.
    """
    ordered = sorted(volumes, key=lambda v: (v.position, v.key is not None, v.key or 0))
    candidates = [v for v in ordered if v.accepting and v.usable]
    for v in candidates:
        if not v.full:
            return v
    if candidates:
        return candidates[0]
    return next((v for v in ordered if v.is_default), None)


def all_full(volumes: list[Volume]) -> bool:
    """True when every accepting healthy volume is full (time to overwrite the oldest recordings)."""
    candidates = [v for v in volumes if v.accepting and v.usable]
    return bool(candidates) and all(v.full for v in candidates)


def classify_error(exc: BaseException, path: str) -> tuple[str, str]:
    """(state, human detail) for an exception raised while checking a volume folder."""
    winerror = getattr(exc, "winerror", None)
    network = path.startswith(("\\\\", "//"))
    host = path.lstrip("\\/").replace("/", "\\").split("\\", 1)[0] if network else ""
    if isinstance(exc, PermissionError) or winerror in _LOGON_WINERRORS:
        if network:
            return ERROR, (f"Access denied. Save the share's login on the node PC (as the Windows user that runs "
                           f"the media node): cmdkey /add:{host} /user:<user> /pass:<password>")
        return ERROR, "Access denied: the media node's Windows user cannot write to this folder"
    if winerror in _UNREACHABLE_WINERRORS or (network and isinstance(exc, OSError)):
        return UNAVAILABLE, f"Network share not reachable ({host})" if network else "Path not reachable"
    if isinstance(exc, FileNotFoundError):
        return UNAVAILABLE, "Drive or folder not found"
    if isinstance(exc, TimeoutError):
        return UNAVAILABLE, "Storage not responding"
    return ERROR, f"{type(exc).__name__}: {exc}"[:250]
