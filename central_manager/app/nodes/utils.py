"""Storage volume helpers (pure functions, unit-tested)."""

from __future__ import annotations

import re

GIB = 1024**3

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")  # D:\... or D:/...
_UNC = re.compile(r"^\\\\[^\\/]+\\[^\\/]+")  # \\host\share[\...]


def normalize_volume_path(value: str) -> str:
    r"""Validate and tidy a storage folder path as the node will use it.

    Accepted: a Windows folder on a drive (D:\ShahNVR\recordings), a network share given by its UNC path
    (\\192.168.1.9\nvr\recordings) or an absolute POSIX path (/mnt/nvr, for Linux nodes).
    Mapped drive letters of network shares are accepted as paths, but the node only sees them if they
    are mapped in its own Windows session; UNC paths always work.
    """
    path = value.strip().strip('"')
    if path.startswith("//"):  # //host/share -> \\host\share
        path = path.replace("/", "\\")
    if _WINDOWS_DRIVE.match(path) or _UNC.match(path):
        path = path.replace("/", "\\")
        path = re.sub(r"(?<!^)\\{2,}", r"\\", path)  # collapse doubled separators (keep the leading \\)
        if len(path) > 3:  # keep "D:\" as is
            path = path.rstrip("\\")
        return path
    if path.startswith("/"):
        return path.rstrip("/") or "/"
    raise ValueError(r"Use a full folder path: D:\ShahNVR\recordings, \\server\share\folder or /mnt/nvr")


def is_network_path(path: str) -> bool:
    return path.startswith(("\\\\", "//"))


def gb_to_bytes(gb: float | None) -> int | None:
    return int(gb * GIB) if gb is not None else None


def total_quota(quotas: list[int | None]) -> int | None:
    """Sum of the volume caps, or None when any volume may use its whole disk (or there are none)."""
    if not quotas or any(q is None for q in quotas):
        return None
    return sum(quotas)
