"""AppContext: the shared services every store needs (preferences, central API client, toasts).

The central API client is rebuilt automatically when the user changes the central URL; stores
subscribe to `centralChanged` to refresh.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.core.api.central import CentralApi
from app.core.node_access import NodeAccessResolver
from app.core.preferences import Preferences
from app.core.toasts import ToastBus


class AppContext(QObject):
    centralChanged = Signal()

    def __init__(self, prefs: Preferences, toasts: ToastBus, parent=None):
        super().__init__(parent)
        self.prefs = prefs
        self.toasts = toasts
        self.central = CentralApi(prefs.centralUrl)
        self.node_access = NodeAccessResolver()
        prefs.centralUrlChanged.connect(self._rebuild_central)
        prefs.nodeAccessChanged.connect(self.node_access.clear)

    def _rebuild_central(self) -> None:
        old, self.central = self.central, CentralApi(self.prefs.centralUrl)
        old.close()
        self.node_access.clear()
        self.centralChanged.emit()
