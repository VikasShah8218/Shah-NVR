"""Dashboard alerts. Node alerts are built here from the node list (port of DashboardPage.tsx::buildNodeAlerts);
camera alerts are built by central and paged (GET /api/v1/cluster/alerts), `camera_alert` turns one into a row."""

from __future__ import annotations

from app.core.format import format_bytes, format_percent, time_ago
from app.features.nodes.resources import node_resources


def build_node_alerts(nodes: list[dict]) -> list[dict]:
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
        for v in r["volumesOffline"]:
            alerts.append({"level": "danger",
                           "title": f"{n['name']}: storage {'error' if v['state'] == 'ERROR' else 'offline'}",
                           "detail": v["path"] + (f" · {v['state_detail']}" if v.get("state_detail") else ""), **link})
        if r["allFull"]:
            alerts.append({"level": "warning", "title": f"{n['name']}: all storage full",
                           "detail": "The oldest recordings are being overwritten. Add storage or raise a cap.", **link})
        elif r["quota"] is not None and r["storagePercent"] is not None and r["storagePercent"] >= 85:
            alerts.append({"level": "warning",
                           "title": f"{n['name']}: {format_percent(r['storagePercent'])} of storage caps used",
                           "detail": f"{format_bytes(r['recordings'])} of {format_bytes(r['quota'])}", **link})
    alerts.sort(key=lambda a: 0 if a["level"] == "danger" else 1)
    for i, a in enumerate(alerts):
        a["key"] = i
        a.setdefault("tab", "")
    return alerts


def camera_alert(a: dict, key: int) -> dict:
    """A central camera alert as a dashboard row; ONVIF and clock alerts open the camera's Device tab."""
    detail = f"{a['detail']} {time_ago(a['since'])}" if a.get("since") else a["detail"]
    return {"key": key, "level": a["level"], "title": a["title"], "detail": detail, "page": "camera",
            "id": a["camera_id"], "tab": "device" if a["kind"] in ("onvif", "clock") else ""}
