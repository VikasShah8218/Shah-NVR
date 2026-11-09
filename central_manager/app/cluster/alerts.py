"""Camera alerts for the dashboard, built on the server so clients never download every camera
(docs/PAGINATION_PLAN.md, step P4).

Same rules and wording as the clients used to compute (nvr_client DashboardPage.buildAlerts,
nvr_desktop dashboard/alerts.py). Node alerts stay in the clients: there are only tens of nodes and their rules
need the live node metrics the dashboard already loads.

Each query asks the database only for cameras that have a problem, so the cost follows the number of alerts, not
the number of cameras.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from tortoise.expressions import Q, Subquery

from app.assignments.models import CameraAssignment
from app.cameras.models import Camera, CameraStream, StreamStatus

CLOCK_DRIFT_ALERT_SECONDS = 10  # same as nvr_client/src/lib/onvif.ts
# A recording stream in these states is not a problem (RECORDING) or is about to start (ASSIGNED).
_OK_STATES = (StreamStatus.RECORDING, StreamStatus.ASSIGNED)
_DANGER_STATES = (StreamStatus.NOT_RECORDING, StreamStatus.UNKNOWN)  # StatusBadge toneOf == "danger"

Level = Literal["danger", "warning"]
Kind = Literal["unassigned", "stream", "onvif", "clock"]


class AlertOut(BaseModel):
    level: Level
    kind: Kind
    title: str
    detail: str
    since: datetime | None = None  # e.g. the last ONVIF check; clients show it as "3 min ago"
    camera_id: int
    camera_name: str
    profile: str | None = None


class AlertCounts(BaseModel):
    danger: int
    warning: int


def format_offset(seconds: float) -> str:
    """Port of nvr_client lib/onvif.ts formatOffset."""
    sign = "+" if seconds > 0 else "−" if seconds < 0 else ""
    s = abs(seconds)
    if s < 1:
        return "in sync"
    if s < 60:
        return f"{sign}{round(s)} s"
    if s < 3600:
        return f"{sign}{int(s // 60)} min {round(s % 60)} s"
    if s < 86400:
        return f"{sign}{s / 3600:.1f} h"
    if s < 86400 * 365:
        return f"{sign}{round(s / 86400)} days"
    return f"{sign}{s / (86400 * 365.25):.1f} years"


async def camera_alerts() -> list[AlertOut]:
    """Every camera alert, danger first, then by camera name. Only enabled cameras."""
    alerts: list[AlertOut] = []
    assigned = Subquery(CameraAssignment.filter(node_id__isnull=False).values("camera_id"))

    for c in await Camera.filter(enabled=True).exclude(id__in=assigned):
        alerts.append(AlertOut(level="danger", kind="unassigned", title=f"{c.name} is not assigned to any node",
                               detail="No node with free capacity", camera_id=c.id, camera_name=c.name))

    streams = await (CameraStream.filter(record=True, camera__enabled=True, camera_id__in=assigned)
                     .exclude(status__in=_OK_STATES).prefetch_related("camera"))
    for s in streams:
        status = getattr(s.status, "value", s.status)
        alerts.append(AlertOut(
            level="danger" if s.status in _DANGER_STATES else "warning", kind="stream",
            title=f"{s.camera.name} ({s.profile}) is {status.replace('_', ' ').lower()}",
            detail=s.status_detail or "Recording is not running",
            camera_id=s.camera_id, camera_name=s.camera.name, profile=s.profile))

    drift = CLOCK_DRIFT_ALERT_SECONDS
    onvif = await Camera.filter(Q(onvif_reachable=False) | Q(clock_offset_seconds__gt=drift)
                                | Q(clock_offset_seconds__lt=-drift), enabled=True, id__in=assigned)
    for c in onvif:
        if c.onvif_reachable is False:
            alerts.append(AlertOut(level="warning", kind="onvif", title=f"{c.name}: ONVIF not answering",
                                   detail="last check", since=c.onvif_checked_at, camera_id=c.id, camera_name=c.name))
        elif c.clock_offset_seconds is not None and abs(c.clock_offset_seconds) > CLOCK_DRIFT_ALERT_SECONDS:
            alerts.append(AlertOut(level="warning", kind="clock",
                                   title=f"{c.name}: camera clock {format_offset(c.clock_offset_seconds)} off",
                                   detail="Open the Device tab to sync the time or set NTP",
                                   camera_id=c.id, camera_name=c.name))

    alerts.sort(key=lambda a: (a.level != "danger", a.camera_name.lower(), a.camera_id, a.kind, a.profile or ""))
    return alerts


def count_levels(alerts: list[AlertOut]) -> AlertCounts:
    danger = sum(1 for a in alerts if a.level == "danger")
    return AlertCounts(danger=danger, warning=len(alerts) - danger)
