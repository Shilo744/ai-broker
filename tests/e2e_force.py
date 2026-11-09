"""End-to-end test of "run anyway" on a SEPARATE throw-away broker (port 47695): a job whose memory estimate cannot fit waits with a reason that has numbers,
and `force_start` makes it run.   python tests/e2e_force.py"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import sandbox

os.environ["AIBROKER_PORT"] = "47695"
from aibroker import client, paths
from aibroker import osutil


def main():
    res = []

    def check(name, cond, extra=""):
        res.append(bool(cond))
        print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:200]) if extra else ""), flush=True)

    daemon = subprocess.Popen([sys.executable, "-m", "aibroker.daemon"], cwd=ROOT, env=dict(os.environ), creationflags=osutil.NO_WINDOW, **osutil.SESSION)
    t0 = time.time()
    while not client.is_up():
        if time.time() - t0 > 20:
            daemon.kill()
            sys.exit("test broker did not start")
        time.sleep(0.4)
    try:
        r = client.call({"op": "submit", "type": "custom", "cmd": [sys.executable, "-c", "print('hello')"], "est": {"ram_gb": 500.0}, "name": "cannot fit", "requester": "test"}, timeout=10)
        jid = r["id"]
        time.sleep(3.5)
        j = client.call({"op": "get", "id": jid}, timeout=5)["job"]
        check("a job that cannot fit waits", j["state"] == "queued", j["state"])
        check("the reason says what is missing", "free RAM would drop below" in (j.get("reason") or ""), j.get("reason"))
        r = client.call({"op": "force_start", "id": jid}, timeout=5)
        check("force_start is accepted", r.get("ok"), r)
        end = time.time() + 30
        state = "queued"
        while time.time() < end:
            state = client.call({"op": "get", "id": jid}, timeout=5)["job"]["state"]
            if state in ("done", "failed"):
                break
            time.sleep(0.5)
        check("the job ran after 'run anyway'", state == "done", state)
        r = client.call({"op": "force_start", "id": jid}, timeout=5)
        check("a job that is not waiting cannot be forced", not r.get("ok"), r)
        s = client.call({"op": "state"}, timeout=5)
        check("the state carries the GPU sampling (gpu_hogs is a list)", isinstance(s["sys"].get("gpu_hogs"), list), s["sys"].get("gpu_hogs"))
        client.call({"op": "pause"}, timeout=5)
        r = client.call({"op": "submit", "type": "custom", "cmd": [sys.executable, "-c", "print('x')"], "est": {"ram_gb": 1.0}, "name": "paused", "requester": "test"}, timeout=10)
        client.call({"op": "force_start", "id": r["id"]}, timeout=5)
        time.sleep(2.5)
        check("'run anyway' does not beat the pause", client.call({"op": "get", "id": r["id"]}, timeout=5)["job"]["state"] == "queued")
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
