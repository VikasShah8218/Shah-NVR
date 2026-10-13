"""Dashboard alerts derived from current state. Port of DashboardPage.tsx::buildAlerts (same rules)."""

from __future__ import annotations

from app.core.format import format_bytes, format_percent, time_ago
from app.core.status import tone_of
from app.features.nodes.resources import node_resources


def build_alerts(cameras: list[dict], nodes: list[dict]) -> list[dict]:
    alerts: list[dict] = []
    for n in nodes:
        r = node_resources(n)
        link = {"page": "node", "id": n["id"]}
        if n.get("state") == "UNREACHABLE":
            alerts.append({"level": "danger", "title": f"{n['name']} is unreachable",
                           "detail": f"last heartbeat {time_ago(n.get('last_heartbeat_at'))}", **link})
        if r["diskPercent"] is not None and r["diskPercent"] >= 85:
            alerts.append({"level": "danger" if r["diskPercent"] >= 95 else "warning",
                           "title": f"{n['name']}: disk {format_percent(r['diskPercent'])} full",
                           "detail": f"{format_bytes(r['diskFree'])} free", **link})
        if r["quota"] is not None and r["storagePercent"] is not None and r["storagePercent"] >= 85:
            alerts.append({"level": "warning",
                           "title": f"{n['name']}: {format_percent(r['storagePercent'])} of storage quota used",
                           "detail": f"{format_bytes(r['recordings'])} of {format_bytes(r['quota'])}; "
                                     "oldest recordings are removed above 95%", **link})
    for c in cameras:
        if not c.get("enabled"):
            continue
        link = {"page": "camera", "id": c["id"]}
        assignment = c.get("assignment") or {}
        if not assignment.get("node_id"):
            alerts.append({"level": "danger", "title": f"{c['name']} is not assigned to any node",
                           "detail": "No node with free capacity", **link})
            continue
        for s in c.get("streams", []):
            if s.get("record") and s.get("status") not in ("RECORDING", "ASSIGNED"):
                status = s.get("status") or "UNKNOWN"
                alerts.append({"level": "danger" if tone_of(status) == "danger" else "warning",
                               "title": f"{c['name']} ({s['profile']}) is {status.replace('_', ' ').lower()}",
                               "detail": s.get("status_detail") or "Recording is not running", **link})
    alerts.sort(key=lambda a: 0 if a["level"] == "danger" else 1)
    for i, a in enumerate(alerts):
        a["key"] = i
    return alerts
