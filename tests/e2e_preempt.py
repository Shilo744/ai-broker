"""End-to-end test of "stop the running job and run this one" on a SEPARATE throw-away broker (port 47696). Pausing a job does not free its memory, so a waiting job
that does not fit would wait for ever; `preempt` stops the running job, puts it back in the queue, and runs the waiting one.   python tests/e2e_preempt.py"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import sandbox

os.environ["AIBROKER_PORT"] = "47696"
sandbox.lenient_limits()
cfgp = os.path.join(sandbox.DIR, "config.json")
cfg = json.load(open(cfgp))
cfg["limits"].update(vram_gb=16.0, max_jobs=3)
json.dump(cfg, open(cfgp, "w"))
from aibroker import client, osutil


def main():
    res = []

    def check(name, cond, extra=""):
        res.append(bool(cond))
        print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:200]) if (extra and not cond) else ""), flush=True)

    daemon = subprocess.Popen([sys.executable, "-m", "aibroker.daemon"], cwd=ROOT, env=dict(os.environ), creationflags=osutil.NO_WINDOW, **osutil.SESSION)
    t0 = time.time()
    while not client.is_up():
        if time.time() - t0 > 20:
            daemon.kill()
            sys.exit("test broker did not start")
        time.sleep(0.4)

    def job(name, vram, secs=60):
        return client.call({"op": "submit", "type": "custom", "cmd": [sys.executable, "-c", "import time;time.sleep(%d)" % secs], "est": {"ram_gb": 1, "vram_gb": vram}, "klass": "gpu",
                            "name": name, "requester": "test"}, timeout=10)["id"]

    def state(i):
        return client.call({"op": "get", "id": i}, timeout=5)["job"]

    def wait(i, want, secs=15):
        end = time.time() + secs
        while time.time() < end:
            if state(i)["state"] == want:
                return True
            time.sleep(0.4)
        return False
    try:
        a = job("A", 9)
        check("A runs", wait(a, "running"))
        b = job("B", 9, secs=4)
        time.sleep(2.5)
        check("B waits for memory", state(b)["state"] == "queued" and "VRAM" in (state(b).get("reason") or ""), state(b).get("reason"))
        client.call({"op": "job_pause", "id": a}, timeout=5)
        time.sleep(3)
        check("pausing A does NOT let B run (a paused job keeps its memory)", state(b)["state"] == "queued")
        client.call({"op": "job_resume", "id": a}, timeout=5)
        r = client.call({"op": "preempt", "id": b}, timeout=5)
        check("preempt is accepted and says how many it stopped", r.get("ok") and r.get("stopped") == 1, r)
        check("B runs now", wait(b, "running", 20) or state(b)["state"] == "done")
        check("A is not lost: it is waiting in the queue again", state(a)["state"] in ("queued", "running"), state(a)["state"])
        check("B finishes", wait(b, "done", 20), state(b)["state"])
        check("then A starts again by itself", wait(a, "running", 20), state(a)["state"])
        r = client.call({"op": "preempt", "id": b}, timeout=5)
        check("a job that is not waiting cannot be preempted", not r.get("ok"), r)
        client.call({"op": "cancel", "id": a}, timeout=5)
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
