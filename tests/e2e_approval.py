"""End-to-end test of the assistant's permission flow with REAL Claude (haiku, a few cents of quota) on a SEPARATE throw-away broker (port 47699, temp data folder):
the owner's service, window, chat history and settings are never touched.

  .venv\\Scripts\\python.exe tests\\e2e_approval.py

With real Claude: (1) a file write at level "normal" shows a Hebrew question card, the test clicks Approve -> the file exists; (2) the same with Decline -> no file.
Through the broker itself (deterministic: what Claude Code decides to ask about is its own business and varies from run to run, the broker's answer must not):
(3) the policy per level for a read-only command, a write, a delete and a blocked action."""
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
    elif s == 3:
        policy_checks()
        finish()


def ask(level, tool, tin):
    client.call({"op": "assistant_level", "set": level})
    r = client.call({"op": "perm_ask", "tool": tool, "input": tin})
    if r["state"] == "pending":                       # clean up: answer it so nothing stays open
        client.call({"op": "perm_answer", "id": r["id"], "allow": False})
    return r["state"]


def policy_checks():
    disk = {"command": "Get-PSDrive -PSProvider FileSystem | Select-Object Name, @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}"}
    write = {"command": "Set-Content -Path C:\\\\t\\\\a.txt -Value hi"}
    delete = {"command": "Remove-Item C:\\\\Users\\\\shilo\\\\Downloads\\\\x.zip"}
    blocked = {"command": "Format-Volume -DriveLetter D"}
    check("3: normal: a read-only disk check is allowed at once", ask("normal", "PowerShell", disk) == "allow")
    check("3: normal: a file write asks", ask("normal", "PowerShell", write) == "pending")
    check("4: careful: even the read-only command asks", ask("careful", "PowerShell", disk) == "pending")
    check("4: careful: reading a file is free", ask("careful", "Read", {"file_path": "C:\\\\x.txt"}) == "allow")
    check("5: free: a file write runs at once", ask("free", "PowerShell", write) == "allow")
    check("5: free: a delete still asks", ask("free", "PowerShell", delete) == "pending")
    check("6: a blocked action is refused at every level", all(ask(lv, "PowerShell", blocked) == "deny" for lv in ("careful", "normal", "free")))
    log = broker_log()
    check("7: the broker's log records allow / asks / deny", "assistant allow [normal]" in log and "asks the owner [careful]" in log and "assistant deny [free]" in log)


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
