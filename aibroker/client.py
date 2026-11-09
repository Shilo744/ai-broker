"""Tiny client for the broker's JSON-lines protocol (used by the CLI and the GUI)."""
import json
import socket
import subprocess
import sys
import time

from . import osutil, paths


class BrokerDown(Exception):
    pass


def call(req, timeout=10.0, start=False):
    try:
        return _call(req, timeout)
    except OSError as e:
        if not start:
            raise BrokerDown("broker is not running (try: aijob daemon start): %s" % e)
        start_daemon()
        return _call(req, timeout)


def _call(req, timeout):
    with socket.create_connection(("127.0.0.1", paths.PORT), timeout=timeout) as s:
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        s.settimeout(timeout)
        while not buf.endswith(b"\n"):
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.decode("utf-8"))


def is_up():
    try:
        return _call({"op": "ping"}, 2.0).get("ok", False)
    except (OSError, ValueError):
        return False


def start_daemon(wait_s=15.0):
    """Start the broker detached (no window, survives the caller). Returns when it answers."""
    if is_up():
        return True
    exe = str(paths.VENV_PYW if paths.VENV_PYW.exists() else sys.executable)
    flags = osutil.DETACHED | osutil.NEW_GROUP | osutil.NO_WINDOW
    for extra in (osutil.BREAKAWAY, 0):          # leave the caller's job object if it allows breakaway
        try:
            subprocess.Popen([exe, "-m", "aibroker.daemon"], cwd=str(paths.ROOT), creationflags=flags | extra, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **osutil.SESSION)
            break
        except OSError:
            continue
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if is_up():
            return True
        time.sleep(0.4)
    raise BrokerDown("broker did not start within %.0f s (see %s)" % (wait_s, paths.HOME / "broker.log"))
