"""Import this FIRST in every test that opens the window (before `aibroker`).

A test must never touch the owner's real data. This points the program's data folder (chat history with Claude, pasted images) and the Qt settings
(window size, splitters, last page, zoom) at a throw-away folder that is deleted when the test ends. The running broker service is only READ.
"""
import atexit
import os
import shutil
import sys
import tempfile

DIR = tempfile.mkdtemp(prefix="aibroker_ui_test_")
os.environ["AIBROKER_HOME"] = DIR                 # read by aibroker.paths at import time
atexit.register(shutil.rmtree, DIR, True)

from PySide6 import QtCore                        # noqa: E402  (after the environment is set)

QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, DIR)


def lenient_limits():
    """Budgets that never block a tiny test job (a CI machine can have only 7 GB, a little of it free): for the tests that start their own throw-away broker."""
    import json
    with open(os.path.join(DIR, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"limits": {"ram_gb": 100.0, "vram_gb": 100.0, "max_jobs": 4, "reserve_ram_gb": 0.2, "min_commit_free_gb": 0.0, "hard_free_ram_gb": 0.1,
                              "hard_commit_free_gb": 0.0, "disk_busy_pct": 100.0}}, f)


def require_running_broker():
    """The tests read the real service. If it is down, stop: never start a service with the throw-away folder on the real port."""
    from aibroker import client
    if not client.is_up():
        sys.exit("The broker service is not running. Start it first (bin\\aijob.bat daemon start); the tests only read from it.")
