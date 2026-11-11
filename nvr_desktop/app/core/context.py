"""AppContext: the shared services every store needs (preferences, central API client, toasts, sign-in session).

The central API client is rebuilt automatically when the user changes the central URL; stores
subscribe to `centralChanged` to refresh. With a sign-in session (`auth`, app/core/auth/session.py)
`centralChanged` is also emitted whenever a session starts (sign-in, another user, auth off), so every
store reloads its data for the new user; stores fetch nothing while nobody is signed in.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.core.api.central import CentralApi
from app.core.auth.secure_store import server_key
from app.core.auth.session import AuthSession
from app.core.node_access import NodeAccessResolver
from app.core.preferences import Preferences
from app.core.toasts import ToastBus


class AppContext(QObject):
    centralChanged = Signal()

    def __init__(self, prefs: Preferences, toasts: ToastBus, auth: AuthSession | None = None, parent=None):
        super().__init__(parent)
        self.prefs = prefs
        self.toasts = toasts
        self.auth = auth  # None: no sign-in at all (unit tests); the app always has one
        self.central = CentralApi(prefs.centralUrl, auth)
        self.node_access = NodeAccessResolver()
        prefs.centralUrlChanged.connect(self._rebuild_central)
        prefs.nodeAccessChanged.connect(self.node_access.clear)
        if auth is not None:
            auth.sessionStarted.connect(self._session_started)

    @property
    def ready(self) -> bool:
        """May stores talk to central? (signed in, or auth is off)"""
        return self.auth is None or self.auth.ready

    def can(self, *perms: int) -> bool:
        return self.auth is None or self.auth.can(*perms)

    def _session_started(self) -> None:
        user = self.auth.user if self.auth.state == "signed_in" else None
        self.prefs.set_profile(f"{server_key(self.auth.base_url)}-{user['id']}" if user else "")
        self.node_access.clear()
        self.centralChanged.emit()

    def _rebuild_central(self) -> None:
        old, self.central = self.central, CentralApi(self.prefs.centralUrl, self.auth)
        old.close()
        self.node_access.clear()
        if self.auth is not None:
            self.auth.set_server(self.prefs.centralUrl)  # signs out of the old server; sessionStarted reloads
        else:
            self.centralChanged.emit()
