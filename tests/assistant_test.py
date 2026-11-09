"""Drives the assistant panel like a user (headless Claude inside the window). Sends a read-only question, then asks for something that needs approval (pause the queue)
and DECLINES it. Saves screenshots.   .venv\Scripts\python.exe tests\assistant_test.py   (uses a little of the Claude quota)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sandbox          # FIRST: throw-away data folder and Qt settings (the real service is still used, so these tests spend real model time)
from PySide6 import QtWidgets as W, QtCore
from PySide6.QtCore import Qt
from aibroker import gui

sandbox.require_running_broker()
app = W.QApplication([])
app.setStyle("Fusion")
app.setLayoutDirection(Qt.RightToLeft)
app.setStyleSheet(gui.QSS)
win = gui.Main(tray=False)
win.resize(1280, 860)
win.show()
st = {"step": 0}


def tick():
    p = win.assistant_panel
    if not win.models or (p.worker and p.worker.isRunning()):
        return
    if st["step"] == 0:
        win.open_claude()
        p.reset()
        p.edit.setPlainText("מה מצב התור והזיכרון עכשיו? תענה בשורה אחת.")
        p.on_send_click()
        st["step"] = 1
    elif st["step"] == 1:
        win.grab().save("shots/assist_1.png")
        p.edit.setPlainText("תעצור את התור בבקשה.")
        p.on_send_click()
        st["step"] = 2
    elif st["step"] == 2:
        win.grab().save("shots/assist_2_approval.png")
        for e in p.pending:
            p.answer(e, False)                      # decline: never really pause the owner's queue in a test
        st["step"] = 3
    elif st["step"] == 3:
        win.grab().save("shots/assist_3_declined.png")
        print("done; paused flag:", win.state and win.state["paused"], flush=True)
        win.poller.alive = False
        app.quit()


t = QtCore.QTimer()
t.timeout.connect(tick)
t.start(2500)
QtCore.QTimer.singleShot(240000, app.quit)
app.exec()
