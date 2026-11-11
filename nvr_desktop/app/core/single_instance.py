"""One desktop app per Windows user (docs/DESKTOP_AUTH_PLAN.md DD2).

Two processes would share one stored refresh token; refresh tokens rotate and the Auth Server signs the user out
when an old one is reused, so a second copy would end sessions at random. A second launch asks the running copy
to show its window and exits.
"""

from __future__ import annotations

import getpass
import re

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _name() -> str:
    return "ShahNVR-Desktop-" + re.sub(r"[^A-Za-z0-9_-]", "_", getpass.getuser())


class SingleInstance(QObject):
    activated = Signal()  # another launch wants this window in front

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server: QLocalServer | None = None

    @staticmethod
    def notify_running() -> bool:
        """Before the UI loads: True when another copy runs (it was asked to show its window)."""
        socket = QLocalSocket()
        socket.connectToServer(_name())
        if not socket.waitForConnected(500):
            return False
        socket.write(b"show")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return True

    def listen(self) -> None:
        """This is the only copy: answer later launches."""
        QLocalServer.removeServer(_name())  # a stale name after a crash
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(_name())

    def _on_connection(self) -> None:
        while self._server and self._server.hasPendingConnections():
            self._server.nextPendingConnection().deleteLater()
            self.activated.emit()
