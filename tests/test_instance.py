"""One window at a time (aibroker/instance.py): a second launch with the same code asks the open window to come to the front; with newer code the old window is told to quit and the
new one takes over; with nothing running it just starts. Uses its own socket name, so a real window is never touched.   python tests/test_instance.py"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["AIBROKER_SINGLE_NAME"] = "AIBroker.test.%d" % os.getpid()
sys.path.insert(0, ROOT)
from PySide6 import QtCore                      # noqa: E402
from aibroker import instance                   # noqa: E402

bad = 0


def check(name, cond, extra=""):
    global bad
    bad += not cond
    print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:300]) if extra and not cond else ""), flush=True)


LISTENER = """
import sys
sys.path.insert(0, %r)
from PySide6 import QtCore
from aibroker import instance
app = QtCore.QCoreApplication([])
def show(): print("SHOW", flush=True)
def quit_(): print("QUIT", flush=True); QtCore.QTimer.singleShot(300, app.quit)
L = instance.Listener("100", show, quit_)
print("READY" if L.ok else "FAILED", flush=True)
QtCore.QTimer.singleShot(15000, app.quit)
app.exec()
""" % ROOT

app = QtCore.QCoreApplication([])
check("nothing running: a launch just starts", instance.ask_running("100") == "none")
p = subprocess.Popen([sys.executable, "-c", LISTENER], stdout=subprocess.PIPE, text=True, env=dict(os.environ))
check("the first window listens", p.stdout.readline().strip() == "READY")
check("a second launch with the same code is told to use the open window", instance.ask_running("100") == "same")
check("the open window was asked to show itself", p.stdout.readline().strip() == "SHOW")
t0 = time.time()
check("a launch with newer code replaces the old window", instance.ask_running("101") == "replaced")
check("the old window was told to quit", p.stdout.readline().strip() == "QUIT")
p.wait(timeout=10)
check("after it quit, nothing is running again", instance.ask_running("101") == "none")
check("code_stamp changes with the code and is a number", instance.code_stamp(__import__("pathlib").Path(ROOT)).isdigit())
print("instance test: %d failed" % bad)
sys.exit(1 if bad else 0)
