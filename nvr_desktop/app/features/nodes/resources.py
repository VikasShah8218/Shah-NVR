"""Node resource maths. Port of nvr_client/src/features/nodes/nodeUtils.ts::nodeResources.

Everything is derived from the node's last heartbeat (`MediaNode.metrics`, free JSON on the server).
"""

from __future__ import annotations

from app.core.format import ratio

HEALTHY_STATES = ("ACTIVE", "READY")
OFFLINE_VOLUME_STATES = ("UNAVAILABLE", "ERROR")


def volume_room(v: dict) -> int | None:
    """Room a storage volume still has for recordings: limited by its cap and by its disk's free space."""
    by_cap = max(0, v["quota_bytes"] - (v.get("recordings_bytes") or 0)) if v.get("quota_bytes") is not None else None
    by_disk = v.get("free_bytes")
    if by_cap is not None and by_disk is not None:
        return min(by_cap, by_disk)
    return by_cap if by_cap is not None else by_disk


def volume_usable(v: dict) -> bool:
    """Can receive new recordings right now."""
    return bool(v.get("accepting")) and v.get("state") in ("OK", "FULL")


def node_resources(node: dict) -> dict:
    m = node.get("metrics") or {}
    disk = m.get("disk") or None
    volumes = node.get("volumes") or []
    quota = node.get("storage_quota_bytes")
    disk_free = disk.get("free_bytes") if disk else None

    if volumes:
        # Several drives / shares: add up what each holds and how much room each still has.
        recordings = sum(v.get("recordings_bytes") or 0 for v in volumes)
        remaining = sum(volume_room(v) or 0 for v in volumes if volume_usable(v))
    else:
        # Node older than storage volumes: one folder, one disk.
        recordings = m.get("recordings_bytes")
        by_quota = max(0, quota - recordings) if quota is not None and recordings is not None else None
        if by_quota is not None and disk_free is not None:
            remaining = min(by_quota, disk_free)
        else:
            remaining = by_quota if by_quota is not None else disk_free
    usable = recordings + remaining if recordings is not None and remaining is not None else None
    accepting = [v for v in volumes if v.get("accepting")]

    mem_percent = m.get("memory_percent")
    if mem_percent is None:
        mem_percent = ratio(m.get("memory_used_bytes"), m.get("memory_total_bytes"))

    return {
        "cpuPercent": m.get("cpu_percent"),
        "cpuCount": m.get("cpu_count"),
        "gpus": m.get("gpus") or [],
        "memUsed": m.get("memory_used_bytes"),
        "memTotal": m.get("memory_total_bytes"),
        "memPercent": mem_percent,
        "diskTotal": disk.get("total_bytes") if disk else None,
        "diskFree": disk_free,
        "diskPercent": disk.get("used_percent") if disk else None,
        "recordings": recordings,
        "quota": quota,
        # recordings vs quota when a quota is set, otherwise disk usage
        "storagePercent": ratio(recordings, quota) if quota is not None else (disk.get("used_percent") if disk else None),
        "remaining": remaining,
        "usable": usable,
        "netRx": m.get("net_rx_mbps"),
        "netTx": m.get("net_tx_mbps"),
        "mediamtxRunning": m.get("mediamtx_running"),
        "pendingUploads": m.get("pending_uploads"),
        "camerasPercent": ratio(node.get("assigned_cameras"), node.get("capacity_cameras")),
        "volumes": volumes,
        "writingVolume": next((v for v in volumes if v.get("writing")), None),
        "volumesOffline": [v for v in volumes if v.get("state") in OFFLINE_VOLUME_STATES],
        # Every accepting volume is full: the node is overwriting its oldest recordings.
        "allFull": bool(accepting) and all(v.get("state") == "FULL" for v in accepting),
        # LAN addresses of the node PC other than the one clients use
        "otherAddresses": [a for a in (m.get("addresses") or [])
                           if a.get("usable") and a.get("ip") != node.get("media_host")],
    }


def is_healthy(node: dict) -> bool:
    return node.get("state") in HEALTHY_STATES


def cluster_totals(nodes: list[dict]) -> dict:
    """Totals tiles of the Media Nodes page (port of NodesPage.tsx::ClusterTotals)."""
    resources = [node_resources(n) for n in nodes]

    def total(key: str) -> float:
        return sum((r.get(key) or 0) for r in resources)

    cpu_values = [r["cpuPercent"] for r in resources if r["cpuPercent"] is not None]
    return {
        "nodes": len(nodes),
        "healthy": sum(1 for n in nodes if is_healthy(n)),
        "cpuAverage": sum(cpu_values) / len(cpu_values) if cpu_values else None,
        "cpuCores": total("cpuCount"),
        "memUsed": total("memUsed"),
        "memTotal": total("memTotal"),
        "recordings": total("recordings"),
        "quota": total("quota"),
        "diskFree": total("diskFree"),
        "netRx": total("netRx"),
        "cameras": sum(n.get("assigned_cameras", 0) for n in nodes),
        "capacity": sum(n.get("capacity_cameras", 0) for n in nodes),
    }
