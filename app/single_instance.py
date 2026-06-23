from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# A fixed, app-specific name. A second launch connects to this; if the connect
# succeeds another copy is already running, so the new one bows out (and asks
# the running copy to surface itself). Single-instance avoids two processes
# fighting over the same Bluetooth controller.
_SERVER_NAME = "LumaBLE-single-instance"


class SingleInstance(QObject):
    def __init__(self, name: str = _SERVER_NAME) -> None:
        super().__init__()
        self._name = name
        self._server: QLocalServer | None = None
        self._activate: Callable[[], None] | None = None

    def is_already_running(self) -> bool:
        """True if another instance owns the lock (and was nudged to surface)."""
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if socket.waitForConnected(250):
            socket.write(b"show\n")
            socket.flush()
            socket.waitForBytesWritten(250)
            socket.disconnectFromServer()
            return True

        # No live instance — clean up any stale endpoint (left by a crash) and
        # become the owner.
        QLocalServer.removeServer(self._name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._server.listen(self._name)
        return False

    def set_activate_callback(self, callback: Callable[[], None]) -> None:
        """Called when another launch is attempted, to bring this window forward."""
        self._activate = callback

    def _on_new_connection(self) -> None:
        if self._server is not None:
            connection = self._server.nextPendingConnection()
            if connection is not None:
                connection.disconnectFromServer()
        if self._activate is not None:
            self._activate()
