"""Drives the chat panel like a user: opens the Qwen model, types a message (no attachment: it edits the last result), sends, and saves screenshots while it runs and when done.
  .venv\\Scripts\\python.exe tests\\chat_test.py     (runs one real Qwen job: about 1 minute, 33 GB RAM)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6 import QtWidgets as W, QtCore
from PySide6.QtCore import Qt
from aibroker import gui

app = W.QApplication([])
app.setStyle("Fusion")
app.setLayoutDirection(Qt.RightToLeft)
app.setStyleSheet(gui.QSS)
win = gui.Main(tray=False, model="qwen_edit")
win.resize(1280, 860)
win.show()
state = {"sent": False}


def step():
    if not win.state or not win.models or state["sent"]:
        return
    win.chat.edit.setPlainText("Make the boots white. Keep everything else identical.")
    win.chat.send()
    state["sent"] = True
    print("sent", flush=True)


def snap(name):
    win.grab().save(name)
    print("saved", name, flush=True)


timer = QtCore.QTimer()
timer.timeout.connect(step)
timer.start(1500)
QtCore.QTimer.singleShot(20000, lambda: snap("shots/chat_running.png"))
QtCore.QTimer.singleShot(90000, lambda: (snap("shots/chat_done.png"), setattr(win.poller, "alive", False), app.quit()))
app.exec()
