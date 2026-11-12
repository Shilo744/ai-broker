"""One window at a time. The first AI Broker window listens on a local socket; a second launch (the desktop icon, the Start menu, autostart) asks it to come to the front and exits
instead of opening another window. If the running window was started from OLDER code than this launch sees on disk (an update), the old one is asked to quit and the new one takes over,
so a launch always ends up with the current version. Uses Qt's local socket (no extra package)."""
import time

from PySide6 import QtCore
from PySide6.QtNetwork import QLocalServer, QLocalSocket

import os


def name():
    return os.environ.get("AIBROKER_SINGLE_NAME") or "AIBroker.Window.single"          # the tests use their own name, so a real window is never disturbed


def code_stamp(root=None):
    from . import paths
    return paths.code_stamp()


def ask_running(stamp, wait_old_gone=False):
    """Returns "same" (a window with this code is running: it was told to show itself), "replaced" (an older one was told to quit; continue to start), or "none"."""
    deadline = time.time() + (6.0 if wait_old_gone else 0.0)
    while True:
        s = QLocalSocket()
        s.connectToServer(name())
        if not s.waitForConnected(400):
            return "none"
        if wait_old_gone:                                   # a restart on purpose (language change): the old window is closing, wait until it is gone
            s.disconnectFromServer()
            if time.time() > deadline:
                return "none"
            time.sleep(0.2)
            continue
        s.write(("HELLO %s" % stamp + chr(10)).encode())
        s.flush()
        answer = b""
        if s.waitForReadyRead(1500):
            answer = bytes(s.readAll()).strip()
        s.disconnectFromServer()
        if answer == b"SAME":
            return "same"
        if answer == b"QUIT":
            ask_running(stamp, wait_old_gone=True)          # wait until the old window has really closed and let go of the socket
            return "replaced"
        return "none"                                       # an old window from before this feature does not answer: it cannot be told, start anyway


class Listener(QtCore.QObject):
    """The running window's side: on HELLO <stamp> it shows itself (same code) or quits (different code)."""

    def __init__(self, stamp, on_show, on_quit, parent=None):
        super().__init__(parent)
        self.stamp, self.on_show, self.on_quit = stamp, on_show, on_quit
        QLocalServer.removeServer(name())                     # a leftover from a crashed run
        self.server = QLocalServer(self)
        self.ok = self.server.listen(name())
        self.server.newConnection.connect(self._conn)

    def _conn(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        sock.waitForReadyRead(500)
        line = bytes(sock.readAll()).decode("utf-8", "replace").strip()
        if line.startswith("HELLO"):
            same = line.split(" ", 1)[-1].strip() == self.stamp
            sock.write(b"SAME" if same else b"QUIT")
            sock.flush()
            sock.disconnectFromServer()
            (self.on_show if same else self.on_quit)()
        else:
            sock.disconnectFromServer()

    def close(self):
        self.server.close()
