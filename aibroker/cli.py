"""aijob: the command line of the AI Broker.   aijob --help"""
import argparse
import json
import os
import sys
import time

from . import client

EXIT = {"done": 0, "failed": 1, "cancelled": 2, "lost": 1}


def fmt_job(j):
    bits = ["#%d" % j["id"], j["state"].upper(), j["name"], "(%s)" % j["requester"]]
    if j["state"] in EXIT:
        secs = (j.get("finished") or 0) - (j.get("started") or j.get("finished") or 0)
        bits.append("exit=%s %.0fs peakRAM=%.1fGB peakCommit=%.1fGB peakVRAM=%.1fGB" % (j.get("rc"), secs, j.get("peak_ws") or 0, j.get("peak_commit") or 0, j.get("peak_vram") or 0))
        if j.get("note"):
            bits.append("[%s]" % j["note"])
    elif j["state"] in ("running", "paused"):
        bits.append("running %ss RAM=%.1fGB VRAM=%.1fGB" % (j.get("elapsed", 0), j.get("cur_ws", 0), j.get("cur_vram", 0)))
    else:
        bits.append("est RAM %.1fGB VRAM %.1fGB %s" % (j["est_ram"], j["est_vram"], ("- " + j["reason"]) if j.get("reason") else ""))
    return " ".join(bits)


def need(resp):
    if not resp.get("ok"):
        print("error:", resp.get("error"), file=sys.stderr)
        sys.exit(1)
    return resp


def parse_kv(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit("parameter must be key=value: %r" % it)
        k, v = it.split("=", 1)
        try:
            out[k] = json.loads(v) if v[:1] in "[{" or v in ("true", "false") or v.lstrip("-").replace(".", "", 1).isdigit() else v
        except ValueError:
            out[k] = v
    return out


def cmd_submit(a):
    extra = a.cmd or []
    est = {}
    for k, v in (("ram_gb", a.ram), ("vram_gb", a.vram), ("commit_gb", a.commit)):
        if v is not None:
            est[k] = v
    req = dict(op="submit", type=a.type, params=parse_kv(a.params), name=a.name, requester=a.requester or os.environ.get("AIJOB_REQUESTER") or "unknown",
               est=est or None, model=a.model, klass=a.klass, cwd=a.cwd, after=a.after, next=a.next, hold=a.hold, timeout_s=a.timeout,
               env=parse_kv(a.env), cmd=extra or None)
    jid = need(client.call(req, start=True))["id"]
    print(jid, flush=True)
    if a.wait:
        return wait_for([jid], None)


def wait_for(ids, timeout):
    t0 = time.time()
    pending = list(ids)
    worst = 0
    last_err = 0
    while pending:
        for jid in list(pending):
            try:
                r = client.call({"op": "get", "id": jid}, timeout=10)
            except client.BrokerDown as e:
                if time.time() - last_err > 60:
                    print("waiting: broker unreachable (%s)" % e, file=sys.stderr, flush=True)
                    last_err = time.time()
                continue
            if not r.get("ok"):
                print("error:", r.get("error"), file=sys.stderr)
                return 1
            j = r["job"]
            if j["state"] in EXIT:
                print(fmt_job(j), flush=True)
                worst = max(worst, EXIT[j["state"]])
                pending.remove(jid)
        if pending:
            if timeout and time.time() - t0 > timeout:
                print("timeout: still waiting for %s" % ",".join("#%d" % i for i in pending), flush=True)
                return 3
            time.sleep(2.0)
    return worst


def cmd_status(a):
    s = need(client.call({"op": "state"}))
    if a.id:
        j = need(client.call({"op": "get", "id": a.id}))["job"]
        print(fmt_job(j))
        if a.tail:
            print(need(client.call({"op": "tail", "id": a.id, "bytes": 4000}))["text"])
        return
    sy = s["sys"]
    print("broker %s | RAM free %.1f/%.0f GB | commit free %.0f GB | VRAM %.1f/%.1f GB | disk %.0f%% | AI budget RAM %.1f/%.0f VRAM %.1f/%.0f%s" % (
        s["status"], sy["ram_avail"], sy["ram_total"], sy["commit_avail"], sy["gpu_used"], sy["gpu_total"], sy["disk"], s["budget"]["ram"], s["limits"]["ram_gb"],
        s["budget"]["vram"], s["limits"]["vram_gb"], (" | " + s["brake"]) if s["brake"] else ""))
    for j in s["running"] + s["queued"]:
        print(" ", fmt_job(j))
    if not (s["running"] or s["queued"]):
        print("  (queue empty)")
    if a.history:
        for j in need(client.call({"op": "history", "limit": a.history}))["jobs"]:
            print(" ", fmt_job(j))


def cmd_move(a):
    to = a.to
    need(client.call({"op": "move", "ids": a.ids, "to": to if to in ("top", "bottom", "up", "down") else int(to)}))
    print("ok")


LIMIT_KEYS = (("ram_gb", float), ("vram_gb", float), ("max_jobs", int), ("reserve_ram_gb", float), ("min_commit_free_gb", float),
              ("hard_free_ram_gb", float), ("hard_commit_free_gb", float))


def cmd_limits(a):
    s = {k: getattr(a, k) for k, _ in LIMIT_KEYS if getattr(a, k) is not None}
    r = need(client.call({"op": "limits", "set": s}))
    print(json.dumps(r["limits"], indent=1))


def cmd_types(a):
    r = need(client.call({"op": "types"}))
    for tid, t in sorted(r["types"].items(), key=lambda kv: (kv[1].get("group", ""), kv[0])):
        e = t.get("est", {})
        print("%-18s %-4s est RAM %4.1f VRAM %4.1f  %s" % (tid, t.get("klass", "cpu"), e.get("ram_gb", 0), e.get("vram_gb", 0), t.get("title", "")))
        if a.verbose:
            for k, v in (t.get("params") or {}).items():
                d = v.get("default") if isinstance(v, dict) else v
                print("      %s=%s  %s" % (k, d, (v.get("help", "") if isinstance(v, dict) else "")))


def cmd_daemon(a):
    if a.what == "start":
        client.start_daemon()
        print("broker running")
    elif a.what == "stop":
        try:
            client.call({"op": "shutdown"})
            print("stopping (running jobs keep running as orphans)")
        except client.BrokerDown:
            print("not running")
    else:
        print("running" if client.is_up() else "not running")


def simple(op, **extra):
    def f(a):
        req = {"op": op}
        for k, v in extra.items():
            req[k] = getattr(a, v)
        need(client.call(req, start=True))
        print("ok")
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aijob", description="AI Broker: submit and manage local AI/GPU jobs.")
    sp = ap.add_subparsers(dest="c", required=True)

    p = sp.add_parser("submit", help="aijob submit <type> key=value ...   |   aijob submit custom --ram 4 -- <command...>")
    p.add_argument("type")
    p.add_argument("params", nargs="*", help="key=value parameters of the job type")
    p.add_argument("--name")
    p.add_argument("--requester")
    p.add_argument("--model")
    p.add_argument("--klass", choices=["gpu", "cpu"])
    p.add_argument("--ram", type=float, help="estimated RAM GB (overrides the learned estimate)")
    p.add_argument("--vram", type=float)
    p.add_argument("--commit", type=float)
    p.add_argument("--cwd")
    p.add_argument("--env", nargs="*", help="K=V")
    p.add_argument("--after", type=int, help="start only after this job id finished OK")
    p.add_argument("--next", action="store_true", help="put at the top of the queue")
    p.add_argument("--hold", action="store_true", help="queue it paused")
    p.add_argument("--timeout", type=int, help="kill after N seconds")
    p.add_argument("--wait", action="store_true", help="block until it ends")
    p.set_defaults(f=cmd_submit)

    p = sp.add_parser("status", help="queue overview, or one job")
    p.add_argument("id", nargs="?", type=int)
    p.add_argument("--tail", action="store_true")
    p.add_argument("--history", type=int, nargs="?", const=10)
    p.set_defaults(f=cmd_status)
    sp.add_parser("list", help="same as status").set_defaults(f=lambda a: cmd_status(argparse.Namespace(id=None, tail=False, history=None)))
    p = sp.add_parser("move", help="aijob move <id>... --to top|bottom|up|down|<position>")
    p.add_argument("ids", nargs="+", type=int)
    p.add_argument("--to", required=True)
    p.set_defaults(f=cmd_move)
    for name, op, hlp in (("cancel", "cancel", "cancel a job (kills it if running)"), ("hold", "job_pause", "pause one queued/running job"),
                          ("release", "job_resume", "resume one held job")):
        p = sp.add_parser(name, help=hlp)
        p.add_argument("id", type=int)
        p.set_defaults(f=simple(op, id="id"))
    p = sp.add_parser("rerun", help="queue the same job again (new output folder); prints the new id")
    p.add_argument("id", type=int)
    p.add_argument("--requester")
    p.set_defaults(f=lambda a: print(need(client.call({"op": "rerun", "id": a.id, "requester": a.requester or os.environ.get("AIJOB_REQUESTER")}, start=True))["id"]))
    p = sp.add_parser("pause", help="stop starting new jobs (--suspend also freezes the running ones)")
    p.add_argument("--suspend", action="store_true")
    p.set_defaults(f=simple("pause", suspend="suspend"))
    sp.add_parser("resume", help="start jobs again").set_defaults(f=simple("resume"))
    p = sp.add_parser("playing", help="aijob playing on|off  (GPU jobs wait while you play / record)")
    p.add_argument("state", choices=["on", "off"])
    p.set_defaults(f=lambda a: simple("playing", on="on")(argparse.Namespace(on=a.state == "on")))
    p = sp.add_parser("wait", help="block until the job(s) end (run it as a BACKGROUND command so the agent is woken up)")
    p.add_argument("ids", nargs="+", type=int)
    p.add_argument("--timeout", type=int, help="seconds; exit 3 when exceeded")
    p.set_defaults(f=lambda a: wait_for(a.ids, a.timeout))
    p = sp.add_parser("limits", help="show / change the soft limits")
    for k, t in LIMIT_KEYS:
        p.add_argument("--" + k.replace("_", "-"), dest=k, type=t)
    p.set_defaults(f=cmd_limits)
    p = sp.add_parser("types", help="list job types")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(f=cmd_types)
    p = sp.add_parser("daemon", help="start / stop / status of the background broker")
    p.add_argument("what", choices=["start", "stop", "status"])
    p.set_defaults(f=cmd_daemon)

    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")      # the Hebrew Windows console is cp1255: never crash on a character
        except Exception:
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    tail = []
    if "--" in argv:                      # everything after the first '--' is the command of a custom job
        i = argv.index("--")
        argv, tail = argv[:i], argv[i + 1:]
    a = ap.parse_args(argv)
    a.cmd = tail
    try:
        sys.exit(a.f(a) or 0)
    except client.BrokerDown as e:
        print("error:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
