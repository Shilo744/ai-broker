"""UI smoke test: drives the window like a user (paste, recall, send-to, zoom, toasts, palette targets, layout save). Run from the repo root:
  python tests/ui_smoke.py   (with the project venv)"""
import sys, os, traceback
sys.path.insert(0, ".")
import sandbox          # FIRST: throw-away data folder and Qt settings, the test never edits the real chat history or window layout
from PySide6 import QtWidgets as W, QtCore, QtGui, QtTest
from PySide6.QtCore import Qt
from aibroker import gui, client, catalog
from aibroker.osutil import IS_WIN as osutil_is_win
sys.excepthook = lambda *a: (traceback.print_exception(*a), sys.stdout.flush())
app = W.QApplication([]); app.setStyle("Fusion"); app.setLayoutDirection(Qt.RightToLeft); app.setStyleSheet(gui.QSS)
sandbox.require_running_broker()
_status = catalog.status
catalog.status = lambda pk, rts, profile=None: "installed" if pk["id"] == "ollama_llm" else _status(pk, rts, profile)     # pretend this pack is installed: it has no job type yet
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
    # 10b) an installed model without a job type has a clickable page of its own, in its category, and its chat goes to the assistant with the pack id
    rows = [win.model_list.item(i) for i in range(win.model_list.count())]
    it = next((r for r in rows if r.data(Qt.UserRole) == "pack_ollama_llm"), None)
    check("installed model without a job type is a clickable list entry", it is not None and it.data(gui.ROLE_KIND) == "item" and bool(it.flags() & Qt.ItemIsEnabled))
    cap = [r.text() for r in rows if r.data(gui.ROLE_KIND) == "caption"]
    check("it sits under its own category, not in a separate 'no job type' section", it is not None and rows.index(it) > 0 and not any("עדיין בלי סוג" in c for c in cap))
    sent.clear(); win.select_model("pack_ollama_llm"); win.chat.edit.setPlainText("transcribe a file"); win.chat.send()
    check("its page routes to the assistant with the pack id", win.assistant_mode and "ollama_llm" in sent.get("message", ""))
    # 10c) a rebuild of the model page (a job finished, a file appeared) must not throw the view to the start of the conversation
    ch = win.chat
    win.select_model("zimage")
    jobs = [{"id": 900 + i, "state": "done", "type": "zimage_t2i"} for i in range(40)]
    win.model_jobs = lambda: jobs
    ch.add_job = lambda j, cfg: ch.col.addWidget(W.QLabel("job %d" % j["id"] + chr(10) * 4))
    ch.sig = None; ch.build(True); QtTest.QTest.qWait(700)
    bar = ch.scroll.verticalScrollBar()
    check("a page with many jobs opens at the newest (the end)", bar.maximum() > 200 and bar.value() >= bar.maximum() - 6)
    jobs.append({"id": 999, "state": "done", "type": "zimage_t2i"}); ch.build(True); QtTest.QTest.qWait(250)
    check("a new result while you are at the end keeps you at the end", bar.value() >= bar.maximum() - 6)
    bar.setValue(bar.maximum() // 2); mid = bar.value()
    jobs.append({"id": 1000, "state": "done", "type": "zimage_t2i"}); ch.build(True); QtTest.QTest.qWait(250)
    check("a rebuild while you read higher up keeps your place (not the start, not jumping down)", abs(bar.value() - mid) <= 6 and bar.value() > 0)
    del win.model_jobs; del ch.add_job
    # 10d) a finished transcription: its text, a sample + name field per speaker, and saving names rewrites the transcript files
    import tempfile, json as _json, wave
    from aibroker import transcript_fmt
    tmp = tempfile.mkdtemp()
    for n in ("1", "2", "1_2"):
        with wave.open(os.path.join(tmp, "speaker_%s.wav" % n), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(96000))
    transcript_fmt.write(tmp, {"language": "en", "duration": 9, "names": {}, "speakers": [{"id": 1, "sample": "speaker_1.wav", "samples": [{"file": "speaker_1.wav", "text": "first clip"}, {"file": "speaker_1_2.wav", "text": "second clip"}]}, {"id": 2, "sample": "speaker_2.wav"}],
                               "segments": [{"start": 0, "end": 2, "text": "Hello there.", "speaker": 1}, {"start": 3, "end": 5, "text": "Hi.", "speaker": 2}]})
    job = {"id": 950, "type": "ivrit_transcribe", "state": "done", "requester": "owner", "name": "talk", "params": {"audio": os.path.join(tmp, "speaker_1.wav")}, "outdir": tmp,
           "started": 1, "finished": 5, "submitted": 0}
    win.select_model("transcribe"); ch = win.chat
    win.model_jobs = lambda: [job]
    ch.sig = None; ch.build(True); QtTest.QTest.qWait(300)
    fields = ch.col.parent().findChildren(W.QLineEdit) if ch.col.parent() else []
    fields = [f for f in ch.findChildren(W.QLineEdit)]
    check("a finished transcript shows one name field per speaker", len(fields) == 2)
    check("the recording's file name is shown in the request bubble (not an empty bubble)", any("speaker_1.wav" in l.text() for l in ch.findChildren(W.QLabel)))
    fields[0].setText("Dana")
    save = next(b for b in ch.findChildren(W.QPushButton) if "שמור שמות" in b.text() or "Save the names" in b.text())
    save.click(); QtTest.QTest.qWait(300)
    check("saving names rewrites the transcript with them", "Dana: Hello there." in open(os.path.join(tmp, "transcript.txt"), encoding="utf-8").read() and "Speaker 2: Hi." in open(os.path.join(tmp, "transcript.srt"), encoding="utf-8").read())
    import winsound
    plays = []
    real_ps = winsound.PlaySound
    winsound.PlaySound = lambda *a_: plays.append(a_)                # no sound in the test
    pb = [b for b in ch.findChildren(W.QToolButton) if "קול" in b.toolTip() or "voice" in b.toolTip()]
    check("every speaker has a play button", len(pb) == 2 and all(b.isEnabled() for b in pb))
    other = [b for b in ch.findChildren(W.QToolButton) if "קטע אחר" in b.toolTip() or "Another sample" in b.toolTip()]
    check("every speaker has an 'another sample' button", len(other) == 2 and all(b.isEnabled() for b in other))
    if osutil_is_win:
        pb[0].click(); QtTest.QTest.qWait(200)
        check("play: a click starts that speaker's sample", any(isinstance(a_[0], str) and a_[0].endswith("speaker_1.wav") for a_ in plays))
        check("while it plays its button is the active one and shows another (pause) icon", ch.play_btn is pb[0] and pb[0].property("playing") is True)
        n = len(plays); pb[0].click(); QtTest.QTest.qWait(200)
        check("a second click stops it and the button shows play again", len(plays) == n + 1 and plays[-1][0] is None and ch.play_btn is None and pb[0].property("playing") is False)
        pb[0].click(); QtTest.QTest.qWait(100)
        ch.play_ended(ch.play_gen)
        check("when the clip ends by itself the button goes back to play", ch.play_btn is None and pb[0].property("playing") is False)
        plays.clear(); other[0].click(); QtTest.QTest.qWait(200)
        check("'another sample' plays the next clip, shows its text and the button shows pause", any(isinstance(a_[0], str) and a_[0].endswith("speaker_1_2.wav") for a_ in plays)
              and any("second clip" in l.text() for l in ch.findChildren(W.QLabel)) and ch.play_btn is pb[0])
        ch.stop_clip(); plays.clear(); other[1].click(); QtTest.QTest.qWait(100)
        check("'another sample' on a transcript with one sample explains it and plays nothing", not any(isinstance(a_[0], str) for a_ in plays))
    winsound.PlaySound = real_ps
    del win.model_jobs
    # 10d2) Small and Large transcription are two separate models in the list, each with its own page
    dirs = [m["dir"] for m in win.models]
    check("Small and Large transcription are separate entries (Small first)", "transcribe" in dirs and "transcribe_large" in dirs and dirs.index("transcribe") < dirs.index("transcribe_large"))
    titles = {m["dir"]: m["title"] for m in win.models}
    check("their names say which is which", "Small" in titles.get("transcribe", "") and "Large" in titles.get("transcribe_large", ""))
    win.select_model("transcribe_large"); ch = win.chat; ch.set_attached(os.path.join(tmp, "speaker_1.wav"))
    sent_jobs = []
    real_api = win.api
    win.api = lambda req, *a_, **k_: (sent_jobs.append(req), {"ok": True, "id": 1})[1]
    ch.send(); win.api = real_api
    check("a recording sent from the Large page is a job of the Large type", sent_jobs and sent_jobs[0]["type"] == "ivrit_transcribe_large" and sent_jobs[0]["params"].get("audio", "").endswith("speaker_1.wav"))
    ch.set_attached(None)
    # 10d3) a job type file that appears while the window is open shows up in the list without a restart
    from aibroker import paths as _paths
    import json as _json
    extra = _paths.TYPES_DIR / "zz_smoke_type.json"                  # the broker that serves the types is a separate process: the file must be where it looks
    extra.write_text(_json.dumps({"id": "zz_smoke_type", "title": "Smoke test type", "group": "Other", "klass": "cpu", "model": "zz", "est": {"ram_gb": 1}, "params": {}, "cmd": ["x"],
                                  "output_dir": "zz_smoke", "he_title": "סוג בדיקה", "en_title": "Smoke test type"}), encoding="utf-8")
    try:
        win.reload_types_if_changed(); QtTest.QTest.qWait(300)
        check("a new job type file shows up in the model list without a restart", any(m["dir"] == "zz_smoke" for m in win.models))
    finally:
        extra.unlink()
        win.reload_types_if_changed()
    check("and goes away again when the file is removed", not any(m["dir"] == "zz_smoke" for m in win.models))
    # 10d4) the window notices that the code on disk is newer than the code it runs: a click to restart when visible, at once when hidden in the tray
    from aibroker import paths as _p
    real_stamp, restarts = _p.code_stamp, []
    win.restart_self = lambda: restarts.append(1)
    win.code_stamp0, win.told_window, win.update_ticks = real_stamp(), False, 1
    win.check_updates()
    check("same code: nothing happens", not restarts and not win.told_window)
    _p.code_stamp = lambda: "999999999999"
    win.check_updates()
    check("newer code and the window is visible: it offers a restart, does not restart by itself", win.told_window and not restarts)
    win.hide(); win.check_updates()
    check("newer code and the window is hidden in the tray: it restarts at once", restarts == [1])
    _p.code_stamp = real_stamp; win.show(); del win.restart_self
    # 10g) a running job can be stopped from its card; a job waiting for memory offers "stop the running one and run this one"
    win.select_model("transcribe"); ch = win.chat
    run_job = {"id": 960, "type": "ivrit_transcribe", "state": "running", "requester": "owner", "name": "runs", "params": {}, "submitted": 0, "started": 1, "elapsed": 5, "cur_ws": 1, "cur_vram": 4}
    wait_job = {"id": 961, "type": "ivrit_transcribe", "state": "queued", "requester": "owner", "name": "waits", "params": {}, "submitted": 0, "reason": "VRAM budget: 9.0 GB used by jobs, 0.0 GB by other programs + 9.0 GB needed > 16 GB limit"}
    real_state = win.state
    win.state = {"running": [run_job], "queued": [wait_job]}
    win.model_jobs = lambda: [run_job, wait_job]
    ch.sig = None; ch.build(True); QtTest.QTest.qWait(300)
    btns = {b.text().strip(): b for b in ch.findChildren(W.QPushButton)}
    labels = list(btns)
    check("the running job's card has a Stop button", any(l in ("עצור", "Stop") for l in labels))
    pre = [b for l, b in btns.items() if "עצור את הרצה" in l or "Stop the running" in l]
    check("the waiting job's card offers 'stop the running one and run this one'", len(pre) == 1)
    calls = []
    real_api = win.api
    win.api = lambda req, *a_, **k_: (calls.append(req), {"ok": True, "stopped": 1})[1]
    pre[0].click(); win.api = real_api
    check("it asks the service to preempt that job", calls and calls[0] == {"op": "preempt", "id": 961})
    win.state = real_state; del win.model_jobs
    # 10e) a running job that prints "PROGRESS <percent> <text>" gets a real progress bar (the last such line counts)
    lf = os.path.join(tempfile.mkdtemp(), "j.log")
    open(lf, "w").write(chr(10).join(["[broker] x", "PROGRESS 12 100/523 s", "noise", "PROGRESS 47 245/523 s", "more noise", ""]))
    check("log_progress reads the last PROGRESS line", gui.log_progress({"log": lf}) == (47.0, "245/523 s"))
    check("no log, no PROGRESS line, or an old-style line: no real bar", gui.log_progress({}) is None and gui.log_progress({"log": lf + "x"}) is None)
    # 10f) Windows: the window carries its own taskbar identity, so pinning it pins AI Broker (icon + launcher) and not python.exe
    if osutil_is_win:
        from aibroker import winshell
        h = int(win.winId())
        check("window has the AI Broker taskbar identity (id, relaunch command and icon)", winshell.read_window_property(h, "id") == "AIBroker.Window"
              and "AI_Broker.bat" in (winshell.read_window_property(h, "relaunch_command") or "") and (winshell.read_window_property(h, "relaunch_icon") or "").endswith("ai-broker-v4.ico,0"))
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
