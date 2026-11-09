"""UI smoke test: drives the window like a user (paste, recall, send-to, zoom, toasts, palette targets, layout save). Run from the repo root:
  python tests/ui_smoke.py   (with the project venv)"""
import sys, os, traceback
sys.path.insert(0, ".")
import sandbox          # FIRST: throw-away data folder and Qt settings, the test never edits the real chat history or window layout
from PySide6 import QtWidgets as W, QtCore, QtGui, QtTest
from PySide6.QtCore import Qt
from aibroker import gui, client
sys.excepthook = lambda *a: (traceback.print_exception(*a), sys.stdout.flush())
app = W.QApplication([]); app.setStyle("Fusion"); app.setLayoutDirection(Qt.RightToLeft); app.setStyleSheet(gui.QSS)
sandbox.require_running_broker()
win = gui.Main(tray=False, model="qwen_edit"); win.persist = False; win.resize(1400, 880); win.show()
res = []
def check(name, cond): res.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name, flush=True)
def run():
    # 1) paste an image from the clipboard into the Qwen chat
    img = QtGui.QImage(64, 64, QtGui.QImage.Format_RGB32); img.fill(QtGui.QColor("#ff8800"))
    W.QApplication.clipboard().setImage(img)
    check("paste image attaches", win.chat.paste_attachment() and win.chat.attached and os.path.exists(win.chat.attached))
    win.chat.set_attached(None); check("attachment removed", win.chat.attached is None)
    # 2) recall previous messages with the Up key
    win.chat.recall = ["first prompt", "second prompt"]; win.chat.recall_i = -1; win.chat.edit.clear(); win.chat.edit.setFocus()
    QtTest.QTest.keyClick(win.chat.edit, Qt.Key_Up); check("Up recalls the last prompt", win.chat.edit.toPlainText() == "second prompt")
    QtTest.QTest.keyClick(win.chat.edit, Qt.Key_Up); check("Up again goes further back", win.chat.edit.toPlainText() == "first prompt")
    QtTest.QTest.keyClick(win.chat.edit, Qt.Key_Down); check("Down returns", win.chat.edit.toPlainText() == "second prompt")
    win.chat.edit.clear()
    # 3) send an image to another model
    p = os.path.abspath("assets/logo.png").replace("\\", "/")
    win.send_to("tripo_shape", p); check("send_to switches model and attaches", win.sel_model == "tripo_shape" and win.chat.attached == p)
    # 4) palette actions
    win.select_model("zimage"); check("select_model", win.sel_model == "zimage")
    # 5) zoom
    z0 = win.zoom; win.zoom_by(0.1); check("zoom in", win.zoom > z0); win.zoom_by(0, True); check("zoom reset", abs(win.zoom - 1.0) < 0.01)
    # 6) toasts
    win.toast("test", "ok"); check("toast visible", win.toaster.isVisible())
    win.on_down("x"); check("service-down toast", win.toaster.isVisible())
    # 7) queue double click / delete on empty table do not crash
    win.queue_action("cancel"); win.queue_action("hold"); check("queue actions on empty selection", True)
    # 8) model list badges / counts
    check("model list has captions", any(win.model_list.item(i).data(gui.ROLE_KIND) == "caption" for i in range(win.model_list.count())))
    # 9) layout save/restore
    win.persist = True; win.save_layout(); check("layout saved", bool(win.settings.value("split_main")))
    win.persist = False
    # 10) a model page without an interface of its own sends the request to the assistant (Claude is stubbed here)
    sent = {}
    win.assistant_panel.start_turn = lambda message, extra: sent.update(message=message)
    win.select_model("sound"); win.chat.edit.setPlainText("make a door sound"); win.chat.send()
    check("page without interface routes to the assistant", win.assistant_mode and "moss_sound" in sent.get("message", ""))
    # 11) a permission-level card takes a click anywhere on it (the owner could only hit the tiny radio button before)
    got = []
    dlg = gui.LevelDialog(win, "normal", QtCore.QSettings("ai-broker", "assistant"), lambda k: (got.append(k), True)[1])
    dlg.show()
    card, _rb = dlg.cards["careful"]
    QtTest.QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, card.rect().center() + QtCore.QPoint(0, 18))
    check("level card: a click on its text chooses it and applies it", dlg.choice == "careful" and got == ["careful"])
    dlg.close()
    print("RESULT %d/%d" % (sum(1 for _, ok in res if ok), len(res)), flush=True)
    app.quit()
QtCore.QTimer.singleShot(3500, run)
app.exec()
