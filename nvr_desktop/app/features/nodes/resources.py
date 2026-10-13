"""Node resource maths. Port of nvr_client/src/features/nodes/nodeUtils.ts::nodeResources.

Everything is derived from the node's last heartbeat (`MediaNode.metrics`, free JSON on the server).
"""

from __future__ import annotations

from app.core.format import ratio

HEALTHY_STATES = ("ACTIVE", "READY")


def node_resources(node: dict) -> dict:
    m = node.get("metrics") or {}
    disk = m.get("disk") or None
    recordings = m.get("recordings_bytes")
    quota = node.get("storage_quota_bytes")
    disk_free = disk.get("free_bytes") if disk else None

    # Space recordings may still grow into: limited by the quota and by what is free on the disk.
    remaining_by_quota = max(0, quota - recordings) if quota is not None and recordings is not None else None
    if remaining_by_quota is not None and disk_free is not None:
        remaining = min(remaining_by_quota, disk_free)
    else:
        remaining = remaining_by_quota if remaining_by_quota is not None else disk_free
    usable = recordings + remaining if recordings is not None and remaining is not None else None

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
