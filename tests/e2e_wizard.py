"""End-to-end test of the setup wizard window on a THROW-AWAY broker (port 47697) with a fake local file server (nothing leaves the machine):
  python tests/e2e_wizard.py"""
import hashlib, http.server, json, os, socketserver, subprocess, sys, threading, time, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(ROOT)
import sandbox
os.environ["AIBROKER_PORT"] = "47697"
from PySide6 import QtWidgets as W, QtCore
from PySide6.QtCore import Qt
from aibroker import client, gui, osutil, paths, i18n
sys.excepthook = lambda *a: (traceback.print_exception(*a), sys.stdout.flush())
GOOD = os.urandom(6 * 1024 * 1024)
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Length", str(len(GOOD))); self.end_headers()
        for i in range(0, len(GOOD), 256 * 1024):
            self.wfile.write(GOOD[i:i + 256 * 1024]); time.sleep(0.12)
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H); srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % srv.server_address[1]
os.makedirs(os.path.join(sandbox.DIR, "catalog"))
json.dump({"packs": [{"id": "demo_pack", "category": "audio", "title": "חבילת הדגמה (קובץ קטן מהשרת המקומי)", "title_en": "Demo pack (a small file from the local server)", "what": "הדגמה של הורדה עם התקדמות.", "what_en": "A demo of a download with progress.",
    "jobtypes": [], "runtime": [], "needs": {"vram_min_gb": 2, "vram_ok_gb": 4, "ram_gb": 4}, "license": {"name": "demo"}, "files": [
    {"root": "models", "dest": "demo/demo.bin", "url": base + "/demo.bin", "size": len(GOOD), "sha256": hashlib.sha256(GOOD).hexdigest()}]}]}, open(os.path.join(sandbox.DIR, "catalog", "demo.json"), "w", encoding="utf-8"))
daemon = subprocess.Popen([sys.executable, "-m", "aibroker.daemon"], cwd=".", env=dict(os.environ), creationflags=osutil.NO_WINDOW, **osutil.SESSION)
t0 = time.time()
while not client.is_up():
    if time.time() - t0 > 20: sys.exit("no broker")
    time.sleep(0.4)
app = W.QApplication([]); app.setStyle("Fusion"); app.setLayoutDirection(Qt.RightToLeft if i18n.rtl() else Qt.LeftToRight); app.setStyleSheet(gui.QSS)
win = gui.Main(tray=False); win.persist = False; win.resize(1415, 917); win.show()
wiz = gui.SetupWizard(win); wiz.resize(900, 720); wiz.show()
res = []
def check(name, cond, extra=""):
    res.append(bool(cond)); print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:160]) if extra else ""), flush=True)
suffix = ""
def step1():
    wiz.toggle_cat("image"); wiz.toggle_cat("3d"); wiz.toggle_cat("audio")
    check("page 1: three categories chosen, Next enabled", wiz.cats == {"image", "3d", "audio"} and wiz.next_btn.isEnabled())
    wiz.next()
    QtCore.QTimer.singleShot(1200, step2)
def step2():
    check("page 2 shown with pack cards", wiz.page == 1 and len(wiz.checks) >= 3, len(wiz.checks))
    demo = wiz.checks.get("demo_pack")
    check("the demo pack is offered, enabled and pre-ticked (it fits and is missing)", demo and demo[0].isEnabled() and demo[0].isChecked())
    inst = [pid for pid, (cb, p) in wiz.checks.items() if p["status"] == "installed"]
    check("an installed pack is never ticked for download", all(not wiz.checks[i][0].isChecked() for i in inst), inst)
    check("a pack that cannot be downloaded automatically is not tickable", all(not cb.isEnabled() for pid, (cb, p) in wiz.checks.items() if not p["downloadable"]))
    # tick only the demo pack for the download demo
    for pid, (cb, p) in wiz.checks.items():
        cb.setChecked(pid == "demo_pack")
    wiz.next()
    QtCore.QTimer.singleShot(1500, step3)
    check("page 3 shown", wiz.page == 2 and len(wiz.ids) == 1, wiz.ids)
def step3():
    QtCore.QTimer.singleShot(8000, step4)
def step4():
    p = os.path.join(sandbox.DIR, "models", "demo", "demo.bin")
    check("the file arrived intact through the queue", os.path.exists(p) and open(p, "rb").read() == GOOD)
    check("the wizard shows the finished state and stopped polling", (not wiz.timer.isActive()) and ("הושלמה" in wiz.title.text() or "complete" in wiz.title.text()), wiz.title.text())
    check("setup is marked as done", bool(win.settings.value("setup_done")))
    print("RESULT %d/%d" % (sum(res), len(res)), flush=True)
    try: client.call({"op": "shutdown"}, timeout=5)
    except Exception: pass
    daemon.terminate(); app.quit()
QtCore.QTimer.singleShot(2500, step1)
app.exec()
