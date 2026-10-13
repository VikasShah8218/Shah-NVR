"""Status -> colour tone and label. Port of nvr_client/src/components/StatusBadge.tsx (TONE map).

Tones map to Theme colours in QML: success (green), info (cyan), warning (amber), danger (red), muted.
"""

from PySide6.QtCore import QObject, Slot

TONE = {
    # camera streams
    "RECORDING": "success",
    "STREAMING": "info",
    "IDLE": "info",
    "CONNECTING": "warning",
    "ASSIGNED": "warning",
    "NOT_RECORDING": "danger",
    "UNKNOWN": "danger",
    "UNASSIGNED": "muted",
    "DISABLED": "muted",
    # media nodes
    "ACTIVE": "success",
    "READY": "info",
    "CORDONED": "warning",
    "DRAINING": "warning",
    "UNREACHABLE": "danger",
    "OFFLINE": "muted",
    # segments
    "AVAILABLE": "success",
    "DELETING": "warning",
}


def tone_of(status: str | None) -> str:
    return TONE.get(status or "", "muted")


def label_of(status: str | None) -> str:
    text = (status or "").replace("_", " ").lower()
    return text[:1].upper() + text[1:]


class StatusHelper(QObject):
    """QML singleton `Status`: Status.tone("RECORDING") -> "success", Status.label(...)."""

    @Slot(str, result=str)
    def tone(self, status: str) -> str:
        return tone_of(status)

    @Slot(str, result=str)
    def label(self, status: str) -> str:
        return label_of(status)
