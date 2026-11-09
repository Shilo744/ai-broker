"""End-to-end test of the assistant's permission flow with REAL Claude (haiku, a few cents of quota) on a SEPARATE throw-away broker (port 47699, temp data folder):
the owner's service, window, chat history and settings are never touched.

  .venv\\Scripts\\python.exe tests\\e2e_approval.py

Scenarios: (1) a file write at level "normal" shows a Hebrew question card, the test clicks Approve -> the file exists;
(2) the same with Decline -> no file, Claude says so; (3) a read-only disk check at "normal" runs with NO question;
(4) the same read-only command at level "careful" DOES ask. (Claude Code itself never asks about trivial commands such as Get-Date, so the test uses a command with a script block.)"""
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import sandbox                                   # temp data folder + Qt settings

os.environ["AIBROKER_PORT"] = "47699"
from PySide6 import QtCore, QtWidgets as W
from PySide6.QtCore import Qt
from aibroker import client, gui, paths

sys.excepthook = lambda *a: (traceback.print_exception(*a), sys.stdout.flush())
daemon = subprocess.Popen([str(paths.VENV_PY), "-m", "aibroker.daemon"], cwd=ROOT, env=dict(os.environ), creationflags=0x08000000)
t0 = time.time()
while not client.is_up():
    if time.time() - t0 > 20:
        daemon.kill()
        sys.exit("test broker did not start")
    time.sleep(0.4)

app = W.QApplication([])
app.setStyle("Fusion")
app.setLayoutDirection(Qt.RightToLeft)
app.setStyleSheet(gui.QSS)
win = gui.Main(tray=False)
win.persist = False
win.resize(1400, 900)
win.show()
panel = win.assistant_panel
work = tempfile.mkdtemp(prefix="aibroker_e2e_")
res = []


def check(name, cond, extra=""):
    res.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:200]) if extra else ""), flush=True)


state = {"step": 0, "t": time.time(), "cards_seen": 0, "clicked": False}
FILE1 = os.path.join(work, "approved.txt")
FILE2 = os.path.join(work, "declined.txt")


def broker_log():
    try:
        return open(os.path.join(sandbox.DIR, "broker.log"), encoding="utf-8").read()
    except OSError:
        return ""


def say(text):
    panel.edit.setPlainText(text)
    panel.on_send_click()
    state["cards_seen"] = len(panel.perm_cards)
    state["clicked"] = False
    state["t"] = time.time()


def busy():
    return panel.worker is not None and panel.worker.isRunning()


def tick():
    s = state["step"]
    if time.time() - state["t"] > 150 and s not in (0,):
        check("step %d finished in time" % s, False)
        finish()
        return
    if s == 0:
        if not win.models:
            return
        win.open_claude()
        client.call({"op": "assistant_level", "set": "normal"})
        say("Use the PowerShell tool to run exactly this command: Set-Content -Path '%s' -Value 'hello'  and give the tool call the description 'יוצר קובץ בדיקה'. Then answer in one short sentence." % FILE1)
        state["step"] = 1
    elif s == 1:
        new = [c for pid, c in panel.perm_cards.items() if not c["answered"]]
        if new and not state["clicked"]:
            card_text = " ".join(l.toPlainText() for l in new[0]["bubble"].findChildren(gui.MessageView))
            check("1: a Hebrew question card appeared for the file write", any("֐" <= ch <= "׿" for ch in card_text), card_text)
            check("1: the card does not show raw JSON", "{\"command\"" not in card_text and "tool_input" not in card_text)
            new[0]["yes"].click()
            state["clicked"] = True
        if not busy() and state["clicked"]:
            check("1: file written after Approve", os.path.exists(FILE1))
            state["step"] = 2
            say("Use the PowerShell tool to run exactly this command: Set-Content -Path '%s' -Value 'no'  (description 'יוצר קובץ שני'). Then answer in one short sentence." % FILE2)
    elif s == 2:
        new = [c for pid, c in panel.perm_cards.items() if not c["answered"]]
        if new and not state["clicked"]:
            new[0]["no"].click()
            state["clicked"] = True
        if not busy() and state["clicked"]:
            check("2: no file after Decline", not os.path.exists(FILE2))
            state["step"] = 3
            say("Use the PowerShell tool to run exactly this command: Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}  (description 'בודק מקום פנוי'). Then answer in one short sentence.")
    elif s == 3:
        if not busy():
            check("3: read-only disk check ran with NO question at level normal", len(panel.perm_cards) == state["cards_seen"], len(panel.perm_cards) - state["cards_seen"])
            check("3: the broker decided it silently (log says allow [normal])", "assistant allow [normal]" in broker_log())
            client.call({"op": "assistant_level", "set": "careful"})
            time.sleep(1.2)
            state["step"] = 4
            say("Use the PowerShell tool to run exactly this command: Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='UsedGB';e={[math]::Round($_.Used/1GB,1)}}  (description 'בודק מקום בשימוש'). Then answer in one short sentence.")
    elif s == 4:
        new = [c for pid, c in panel.perm_cards.items() if not c["answered"]]
        if new and not state["clicked"]:
            check("4: at level careful the same read-only command asks", True)
            new[0]["yes"].click()
            state["clicked"] = True
        if not busy():
            if not state["clicked"]:
                check("4: at level careful the same read-only command asks", len(panel.perm_cards) > state["cards_seen"])
            check("4: log says asks the owner [careful]", "asks the owner [careful]" in broker_log())
            for line in broker_log().splitlines():
                if "assistant" in line or "owner" in line:
                    print("   log:", line[:160], flush=True)
            finish()


def finish():
    print("RESULT %d/%d" % (sum(res), len(res)), flush=True)
    try:
        client.call({"op": "shutdown"}, timeout=5)
    except Exception:
        pass
    daemon.terminate()
    app.quit()


timer = QtCore.QTimer()
timer.timeout.connect(tick)
timer.start(500)
app.exec()
