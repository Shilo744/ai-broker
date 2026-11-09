"""End-to-end test of the model setup on a SEPARATE throw-away broker (port 47698, temp data folder) with a LOCAL fake file server (nothing is downloaded from the internet):
a test pack (two small files, one of them with a wrong checksum on purpose) is installed through the broker's queue as `download` jobs; the test checks the files, the progress
lines, the state of the pack, a second install (nothing left to do) and the disk-space refusal.   python tests/e2e_setup.py"""
import hashlib
import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import sandbox                                      # temp data folder (AIBROKER_HOME)

os.environ["AIBROKER_PORT"] = "47698"
from aibroker import client, paths
from aibroker import osutil

GOOD = os.urandom(2 * 1024 * 1024)
BAD = os.urandom(300 * 1024)
SHA_GOOD = hashlib.sha256(GOOD).hexdigest()


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = GOOD if self.path == "/good.bin" else BAD
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    res = []

    def check(name, cond, extra=""):
        res.append(bool(cond))
        print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:220]) if extra else ""), flush=True)

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    # the test pack lives in the throw-away data folder, so the shipped catalog is untouched
    cat = os.path.join(sandbox.DIR, "catalog")
    os.makedirs(cat)
    json.dump({"packs": [{"id": "test_pack", "category": "audio", "title": "חבילת בדיקה", "title_en": "Test pack", "what": "x", "jobtypes": [], "runtime": [], "needs": {"vram_min_gb": 0},
                          "license": {"name": "test"}, "files": [
                              {"root": "models", "dest": "test/good.bin", "url": base + "/good.bin", "size": len(GOOD), "sha256": SHA_GOOD},
                              {"root": "models", "dest": "test/bad.bin", "url": base + "/bad.bin", "size": len(BAD), "sha256": "0" * 64}]},
                         {"id": "huge_pack", "category": "audio", "title": "Huge", "title_en": "Huge", "what": "x", "needs": {}, "files": [
                              {"root": "models", "dest": "huge/x.bin", "url": base + "/good.bin", "size": 900 * 1024 ** 4, "sha256": ""}]}]}, open(os.path.join(cat, "test.json"), "w", encoding="utf-8"))
    daemon = subprocess.Popen([sys.executable, "-m", "aibroker.daemon"], cwd=ROOT, env=dict(os.environ), creationflags=osutil.NO_WINDOW, **osutil.SESSION)
    t0 = time.time()
    while not client.is_up():
        if time.time() - t0 > 20:
            daemon.kill()
            sys.exit("test broker did not start")
        time.sleep(0.4)
    try:
        r = client.call({"op": "packs", "categories": ["audio"]}, timeout=30)
        mine = next((p for p in r["packs"] if p["id"] == "test_pack"), None)
        check("the pack list contains the test pack, missing, downloadable", mine and mine["status"] == "missing" and mine["downloadable"] and mine["todo_bytes"] == len(GOOD) + len(BAD), mine and (mine["status"], mine["todo_bytes"]))
        r = client.call({"op": "install_packs", "ids": ["huge_pack"]}, timeout=30)
        check("an install that cannot fit on the disk is refused before anything starts", not r.get("ok") and "disk space" in r.get("error", ""), r)
        r = client.call({"op": "install_packs", "ids": ["test_pack"]}, timeout=30)
        check("install queued two download jobs", r.get("ok") and len(r["ids"]) == 2, r)
        ids = r.get("ids", [])
        end = time.time() + 90
        states = {}
        while time.time() < end:
            states = {i: client.call({"op": "get", "id": i}, timeout=10)["job"]["state"] for i in ids}
            if all(s in ("done", "failed", "cancelled", "lost") for s in states.values()):
                break
            time.sleep(0.7)
        check("both jobs finished", all(s in ("done", "failed") for s in states.values()), states)
        good_path = os.path.join(sandbox.DIR, "models", "test", "good.bin")
        bad_path = os.path.join(sandbox.DIR, "models", "test", "bad.bin")
        check("the good file arrived intact", os.path.exists(good_path) and open(good_path, "rb").read() == GOOD)
        check("the file with the wrong checksum was refused and not kept", not os.path.exists(bad_path) and not os.path.exists(bad_path + ".part"))
        tails = [client.call({"op": "tail", "id": i, "bytes": 4000}, timeout=10).get("text", "") for i in ids]
        check("the job logs say DONE / CHECKSUM MISMATCH", any("DONE" in t for t in tails) and any("CHECKSUM MISMATCH" in t for t in tails), tails)
        check("states: one done, one failed", sorted(states.values()) == ["done", "failed"], states)
        r = client.call({"op": "packs", "categories": ["audio"]}, timeout=30)
        mine = next(p for p in r["packs"] if p["id"] == "test_pack")
        check("the pack is now partial (one of two files)", mine["status"] == "partial" and mine["todo_bytes"] == len(BAD), (mine["status"], mine["todo_bytes"]))
    finally:
        print("RESULT %d/%d" % (sum(res), len(res)), flush=True)
        try:
            client.call({"op": "shutdown"}, timeout=5)
        except Exception:
            pass
        daemon.terminate()
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())
