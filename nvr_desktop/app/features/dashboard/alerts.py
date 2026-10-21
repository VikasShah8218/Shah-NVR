"""Dashboard alerts derived from current state. Port of DashboardPage.tsx::buildAlerts (same rules)."""

from __future__ import annotations

from app.core.format import format_bytes, format_percent, time_ago
from app.core.status import tone_of
from app.features.nodes.resources import node_resources
from app.features.onvif.helpers import CLOCK_DRIFT_ALERT_SECONDS, format_offset


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
    for c in cameras:
        if not c.get("enabled"):
            continue
        link = {"page": "camera", "id": c["id"]}
        assignment = c.get("assignment") or {}
        if not assignment.get("node_id"):
            alerts.append({"level": "danger", "title": f"{c['name']} is not assigned to any node",
                           "detail": "No node with free capacity", **link})
            continue
        if c.get("onvif_reachable") is False:
            alerts.append({"level": "danger", "title": f"{c['name']}: ONVIF is not answering",
                           "detail": "Open Device to check the camera address and connection.",
                           "page": "camera", "id": c["id"], "tab": "device"})
        offset = c.get("clock_offset_seconds")
        if offset is not None and abs(offset) > CLOCK_DRIFT_ALERT_SECONDS:
            alerts.append({"level": "warning", "title": f"{c['name']}: camera clock is off",
                           "detail": f"Offset from its media node: {format_offset(offset)}",
                           "page": "camera", "id": c["id"], "tab": "device"})
        for s in c.get("streams", []):
            if s.get("record") and s.get("status") not in ("RECORDING", "ASSIGNED"):
                status = s.get("status") or "UNKNOWN"
                alerts.append({"level": "danger" if tone_of(status) == "danger" else "warning",
                               "title": f"{c['name']} ({s['profile']}) is {status.replace('_', ' ').lower()}",
                               "detail": s.get("status_detail") or "Recording is not running", **link})
    alerts.sort(key=lambda a: 0 if a["level"] == "danger" else 1)
    for i, a in enumerate(alerts):
        a["key"] = i
        a.setdefault("tab", "")
    return alerts
