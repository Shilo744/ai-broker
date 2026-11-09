"""The broker service. Runs in the background (pythonw), listens on 127.0.0.1:<port> (one JSON line in, one JSON line out).
Owns the queue, starts jobs when the scheduler says they fit, measures them, keeps the legacy GPU lock, suspends under pressure.
Start:  python -m aibroker.daemon      (or `aijob daemon start`)"""
import collections
import ctypes
import statistics
import re
import shutil
from pathlib import Path
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
import traceback

import psutil

from . import hardware, paths, permissions, scheduler, store as st, winutil as wu

TERMINAL = ("done", "failed", "cancelled", "lost")


class AdoptedProc:
    """A job process started by an earlier broker. It is opened by pid, so its real exit code can still be read when it ends."""
    def __init__(self, pid):
        wu.k32.OpenProcess.restype = wu.wt.HANDLE
        self._handle = wu.k32.OpenProcess(0x1000 | 0x100000 | 0x0001 | 0x0100, False, int(pid))     # query limited, synchronize, terminate, set quota
        if not self._handle:
            raise OSError("cannot open pid %d" % pid)
        self.pid = int(pid)

    def poll(self):
        code = wu.wt.DWORD()
        wu.k32.GetExitCodeProcess.argtypes = [wu.wt.HANDLE, ctypes.POINTER(wu.wt.DWORD)]
        if not wu.k32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            return None
        return None if code.value == 259 else code.value


class Live:
    """Runtime data of one running job."""
    def __init__(self, proc, jobobj, fh):
        self.proc, self.jobobj, self.fh = proc, jobobj, fh
        self.t0 = time.time()
        self.peak_ws = self.peak_vram = self.cur_ws = self.cur_vram = self.cur_commit = 0.0
        self.cancel = False
        self.timed_out = False
        self.susp_user = self.susp_brake = False
        self.suspended = False


class Broker:
    def __init__(self):
        paths.HOME.mkdir(parents=True, exist_ok=True)
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        self.cfg = paths.load_config()
        self.store = st.Store()
        self.types = st.load_types()
        self.live = {}
        self.lock = threading.RLock()
        self.events = collections.deque(maxlen=400)
        self.ev_n = 0
        self.perms = {}                    # permission requests of the in-window assistant (id -> entry), see perm_ask
        self.perm_n = 0
        self.sys = {}
        self.reasons = {}
        self.brake = None
        self.owns_lock = False
        self.finished_models = {}          # model -> time of last finish (warm for affinity)
        self.hist_rev = 0
        self.gpu_total = 16.0
        self._smi_t = 0.0
        self._smi = (0.0, 16.0, 0.0)
        self.stop = threading.Event()
        self.t_start = time.time()
        self.disk_hist = collections.deque(maxlen=10)
        self._typ_cache = {}
        # jobs that were running when the previous broker stopped keep their place in the list: the process is found again by pid
        for j in self.store.by_state("running", "paused"):
            if not self.adopt(j):
                self.store.update(j["id"], state="lost", finished=time.time(), note="broker restarted while the job ran and the process could not be found again")
        # the legacy GPU lock may be ours from the previous run (a restart must not turn it into a foreign lock that blocks every GPU job for 25 minutes)
        lock = self.cfg["gpu_lock_path"]
        if wu.lock_holder(lock).startswith("aibroker"):
            if any((self.store.get(i) or {}).get("hold_lock") for i in self.live):
                self.owns_lock = True
            else:
                wu.lock_release(lock)
        self.log("broker started (pid %d, port %d)" % (os.getpid(), paths.PORT))

    def adopt(self, j):
        try:
            p = psutil.Process(j["pid"])
            if abs(p.create_time() - (j["started"] or 0)) > 60:       # another process with a reused pid
                return False
            proc = AdoptedProc(j["pid"])
            jo = wu.JobObject()
            jo.assign(proc)                                           # best effort: lets the peak commit be measured again
            fh = open(j["log"], "ab")
            fh.write(b"\n[broker] service restarted; this job kept running and was picked up again\n")
            fh.flush()
            lv = Live(proc, jo, fh)
            lv.t0 = j["started"] or time.time()
            lv.peak_ws, lv.peak_vram = j["peak_ws"] or 0.0, j["peak_vram"] or 0.0
            lv.suspended = p.status() == "stopped"
            self.live[j["id"]] = lv
            self.store.update(j["id"], state="paused" if lv.suspended else "running")
            self.log("service restarted: job #%d is still running and was picked up again" % j["id"])
            return True
        except (psutil.Error, OSError, KeyError, TypeError):
            return False

    def _kill(self, lv):
        """Terminate a job and everything it started (job object first, then the process tree: an adopted process may not be in our job object)."""
        try:
            lv.jobobj.terminate()
        except Exception:
            pass
        for p in self._tree(lv.proc):
            try:
                p.kill()
            except psutil.Error:
                pass

    def typical(self, est_key):
        """(median seconds, number of runs) of the last successful runs of the same kind of job."""
        c = self._typ_cache.get(est_key)
        if c and time.time() - c[0] < 10:
            return c[1]
        ds = self.store.durations(est_key)
        res = (statistics.median(ds), len(ds)) if ds else (None, 0)
        self._typ_cache[est_key] = (time.time(), res)
        return res

    # ------------------------------------------------------------ helpers
    def log(self, text):
        with self.lock:
            self.ev_n += 1
            self.events.append((self.ev_n, time.time(), text))
        try:
            with open(paths.HOME / "broker.log", "a", encoding="utf-8") as f:
                f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
        except OSError:
            pass

    def save_cfg(self):
        paths.save_config(self.cfg)

    def type_of(self, tid):
        t = self.types.get(tid)
        if not t:
            raise ValueError("unknown job type '%s' (known: %s)" % (tid, ", ".join(sorted(self.types))))
        return t

    # ------------------------------------------------------------ submit
    def submit(self, req):
        with self.lock:
            t = self.type_of(req.get("type", "custom"))
            params = dict(req.get("params") or {})
            if t["id"] == "custom":
                if not req.get("cmd"):
                    raise ValueError("custom job needs a command (aijob submit custom -- <command...>)")
                params["extra"] = [str(x) for x in req["cmd"]]
            outdir = self.make_outdir(t, req.get("name") or params.get("name") or t.get("title", t["id"]))
            full, cmd, env, est_key = st.resolve_command(t, params, self.cfg["vars"], {"outdir": outdir.replace("\\", "/")})
            env["AIBROKER_OUTDIR"] = outdir
            default = dict(ram_gb=2.0, vram_gb=0.0, commit_gb=3.0)
            default.update(t.get("est") or {})
            est = st.learned_estimate(self.store, est_key, default)
            if req.get("est"):
                for k in ("ram_gb", "vram_gb", "commit_gb"):
                    if req["est"].get(k) is not None:
                        est[k] = float(req["est"][k])
                est["source"] = "given by requester"
                est.setdefault("commit_gb", est["ram_gb"] * 1.2)
                if req["est"].get("ram_gb") is not None and req["est"].get("commit_gb") is None:
                    est["commit_gb"] = est["ram_gb"] * 1.2
            klass = req.get("klass") or t.get("klass") or "cpu"
            env.update({str(k): str(v) for k, v in (req.get("env") or {}).items()})
            name = req.get("name") or full.get("name") or t.get("title", t["id"])
            after = req.get("after")
            if after is not None and not self.store.get(int(after)):
                raise ValueError("--after: no job #%s" % after)
            pos = self.store.next_pos()
            job = dict(type=t["id"], name=name, requester=req.get("requester") or "unknown", state="queued", pos=pos, manual=0, held=1 if req.get("hold") else 0,
                       params=full, cmd=cmd, cwd=req.get("cwd") or (render_cwd(t, self.cfg["vars"], full)), env=env, model=req.get("model") or st.render(t.get("model", t["id"]), dict(self.cfg["vars"], **full)),
                       klass=klass, est_key=est_key, est_ram=est["ram_gb"], est_vram=est["vram_gb"], est_commit=est.get("commit_gb") or est["ram_gb"] * 1.2,
                       est_source=est["source"], max_parallel=int(t.get("max_parallel", 0) or 0),
                       hold_lock=1 if (klass == "gpu" and not t.get("self_lock")) else 0, self_lock=1 if t.get("self_lock") else 0,
                       after_id=int(after) if after is not None else None, timeout_s=int(req.get("timeout_s") or t.get("timeout_s") or 0),
                       submitted=time.time(), peak_ws=0, peak_commit=0, peak_vram=0, log="", outdir=outdir)
            jid = self.store.add(job)
            self.store.update(jid, log=str(paths.LOGS / ("%d.log" % jid)))
            if req.get("next"):
                self.move([jid], "top")
            self.log("submitted #%d %s by %s (est RAM %.1f GB, VRAM %.1f GB, %s)" % (jid, name, job["requester"], job["est_ram"], job["est_vram"], est["source"]))
            return jid

    def make_outdir(self, t, name):
        """Every model type has its OWN folder: <output_root>/<type output_dir>/<date>_<time>_<job name>/ (created here, always)."""
        if t.get("no_outdir"):
            return ""
        root = Path(self.cfg["output_root"]) / (t.get("output_dir") or t["id"])
        slug = re.sub(r"[^A-Za-z0-9\-]+", "_", str(name)).strip("_")[:40] or "job"      # ASCII only: some tools (cv2 and friends) cannot open non-ASCII paths on Windows
        base = root / ("%s_%s" % (time.strftime("%Y-%m-%d_%H%M%S"), slug))
        d, n = base, 1
        while d.exists():
            n += 1
            d = Path("%s-%d" % (base, n))
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def ensure_preview(self, glb):
        """Queue a turntable preview of a .glb unless one exists or is already queued. Returns the job id or None."""
        glb = str(glb).replace("\\", "/")
        out = os.path.join(os.path.dirname(glb), "preview").replace("\\", "/")
        if os.path.exists(os.path.join(out, "preview.png")) or not os.path.exists(glb):
            return None
        for j in self.store.by_state("queued", "running", "paused"):
            if j["type"] == "glb_preview" and (j["params"] or {}).get("glb") == glb:
                return None
        return self.submit(dict(type="glb_preview", params={"glb": glb, "out": out}, name="preview " + os.path.basename(glb), requester="broker"))

    def auto_preview(self, j, state):
        if state != "done" or not self.cfg.get("auto_preview", True) or j["type"] == "glb_preview" or not j.get("outdir"):
            return
        try:
            n = 0
            for root, dirs, names in os.walk(j["outdir"]):
                dirs[:] = [d for d in dirs if d != "preview"]
                for nm in names:
                    if nm.lower().endswith(".glb") and n < 3:
                        n += 1
                        self.ensure_preview(os.path.join(root, nm))
        except Exception as e:
            self.log("auto preview failed: %r" % (e,))

    # ------------------------------------------------------------ queue ops
    def move(self, ids, to):
        with self.lock:
            q = [j["id"] for j in self.store.by_state("queued")]
            ids = [i for i in ids if i in q]
            if not ids:
                raise ValueError("job not in the queue")
            rest = [i for i in q if i not in ids]
            first = q.index(ids[0])
            if to == "top":
                new = ids + rest
            elif to == "bottom":
                new = rest + ids
            elif to == "up":
                at = max(0, first - 1)
                new = rest[:at] + ids + rest[at:]
            elif to == "down":
                at = min(len(rest), first + 1)
                new = rest[:at] + ids + rest[at:]
            else:
                at = max(0, min(len(rest), int(to) - 1))
                new = rest[:at] + ids + rest[at:]
            self.store.renumber(new)
            for i in ids:
                self.store.update(i, manual=1)
            self.log("moved %s -> %s" % (",".join("#%d" % i for i in ids), to))

    def cancel(self, jid):
        with self.lock:
            j = self.store.get(jid)
            if not j:
                raise ValueError("no job #%d" % jid)
            if j["state"] == "queued":
                self.store.update(jid, state="cancelled", finished=time.time(), note="cancelled while queued")
                self.hist_rev += 1
            elif jid in self.live:
                lv = self.live[jid]
                lv.cancel = True
                self._unsuspend(lv)
                self._kill(lv)
            else:
                raise ValueError("job #%d is already %s" % (jid, j["state"]))
            self.log("cancel #%d" % jid)

    def rerun(self, jid, requester=None):
        """Queue the same job again (same type, parameters, estimate override, name) with a NEW output folder."""
        with self.lock:
            j = self.store.get(jid)
            if not j:
                raise ValueError("no job #%d" % jid)
            old = (j.get("outdir") or "").replace("\\", "/")

            def fix(v):
                if isinstance(v, str):
                    return v.replace(old, "{outdir}") if old else v
                if isinstance(v, list):
                    return [fix(x) for x in v]
                return v
            params = {k: fix(v) for k, v in (j["params"] or {}).items()}
            req = dict(type=j["type"], params=params, name=(j["name"] + " (שוב)") if "(שוב)" not in j["name"] else j["name"], requester=requester or "owner", model=j["model"])
            if j["type"] == "custom":
                req["cmd"] = params.pop("extra", None) or [fix(x) for x in j["cmd"]]
            if str(j["est_source"]).startswith("given"):
                req["est"] = {"ram_gb": j["est_ram"], "vram_gb": j["est_vram"], "commit_gb": j["est_commit"]}
            return self.submit(req)

    def job_pause(self, jid):
        with self.lock:
            j = self.store.get(jid)
            if j and j["state"] == "queued":
                self.store.update(jid, held=1)
            elif jid in self.live:
                self.live[jid].susp_user = True
            else:
                raise ValueError("job #%s cannot be paused" % jid)
            self.log("pause #%d" % jid)

    def job_resume(self, jid):
        with self.lock:
            j = self.store.get(jid)
            if j and j["state"] == "queued":
                self.store.update(jid, held=0)
            elif jid in self.live:
                self.live[jid].susp_user = False
            else:
                raise ValueError("job #%s cannot be resumed" % jid)
            self.log("resume #%d" % jid)

    # ------------------------------------------------------------ process control
    @staticmethod
    def _tree(proc):
        try:
            p = psutil.Process(proc.pid)
            return [p] + p.children(recursive=True)
        except psutil.Error:
            return []

    def _suspend(self, lv):
        if not lv.suspended:
            for p in self._tree(lv.proc):
                try:
                    p.suspend()
                except psutil.Error:
                    pass
            lv.suspended = True

    def _unsuspend(self, lv):
        if lv.suspended:
            for p in self._tree(lv.proc):
                try:
                    p.resume()
                except psutil.Error:
                    pass
            lv.suspended = False

    # ------------------------------------------------------------ main loop
    def sample_system(self):
        m = wu.mem_status()
        now = time.time()
        if now - self._smi_t > 2.0:
            r = wu.nvidia_smi()
            if r:
                self._smi = r
                self.gpu_total = r[1]
            self._smi_t = now
        disk = wu.disk_busy_pct()
        self.disk_hist.append(disk)
        self.sys = dict(m, cpu=psutil.cpu_percent(None), disk=disk, disk_avg=sum(self.disk_hist) / len(self.disk_hist), gpu_used=self._smi[0], gpu_total=self._smi[1], gpu_util=self._smi[2], t=now)

    def monitor(self):
        gpu = wu.gpu_process_mem()
        for jid, lv in list(self.live.items()):
            tree = self._tree(lv.proc)
            ws = com = vr = 0.0
            for p in tree:
                try:
                    mi = p.memory_info()
                    ws += mi.rss
                    com += getattr(mi, "pagefile", 0)
                    vr += gpu.get(p.pid, 0)
                except psutil.Error:
                    pass
            lv.cur_ws, lv.cur_commit, lv.cur_vram = ws / wu.GB, com / wu.GB, vr / wu.GB
            lv.peak_ws = max(lv.peak_ws, lv.cur_ws)
            lv.peak_vram = max(lv.peak_vram, lv.cur_vram)
            j = self.store.get(jid)
            if j and j["timeout_s"] and time.time() - lv.t0 > j["timeout_s"] and not lv.timed_out:
                lv.timed_out = True
                self._kill(lv)
                self.log("#%d killed: timeout %ds" % (jid, j["timeout_s"]))

    def finalize(self):
        for jid, lv in list(self.live.items()):
            rc = lv.proc.poll()
            if rc is None:
                continue
            secs = time.time() - lv.t0
            root_ws, root_commit = wu.peak_of_process(lv.proc)
            lv.peak_ws = max(lv.peak_ws, root_ws)
            peak_c = max(lv.jobobj.peak_commit_gb(), root_commit)
            state = "cancelled" if lv.cancel else ("done" if rc == 0 else "failed")
            note = "timeout" if lv.timed_out else ""
            j = self.store.get(jid)
            self.store.update(jid, state=state, rc=rc, finished=time.time(), peak_ws=round(lv.peak_ws, 2), peak_commit=round(peak_c, 2), peak_vram=round(lv.peak_vram, 2), note=note)
            try:
                lv.fh.write(("\n[broker] exit code %s after %.0f s; peak RAM %.1f GB, peak commit %.1f GB, peak VRAM %.1f GB\n" % (rc, secs, lv.peak_ws, peak_c, lv.peak_vram)).encode())
                lv.fh.close()
            except Exception:
                pass
            lv.jobobj.close()
            self.write_result(j, state, rc, secs, lv.peak_ws, peak_c, lv.peak_vram)
            self.auto_preview(j, state)
            del self.live[jid]
            self.finished_models[j["model"]] = time.time()
            self.hist_rev += 1
            self.log("#%d %s -> %s (exit %s, %.0f s, peak RAM %.1f GB, commit %.1f GB, VRAM %.1f GB)" % (jid, j["name"], state, rc, secs, lv.peak_ws, peak_c, lv.peak_vram))
            if self.cfg.get("toast"):
                wu.toast("AI Broker: job #%d %s" % (jid, state), "%s (%s) %.0f s" % (j["name"], j["requester"], secs))
        # legacy lock: ours only while a lock-holding GPU job runs
        holders = [1 for jid in self.live if self.store.get(jid) and self.store.get(jid)["hold_lock"]]
        if self.owns_lock and not holders:
            wu.lock_release(self.cfg["gpu_lock_path"])
            self.owns_lock = False
        elif self.owns_lock:
            wu.lock_touch(self.cfg["gpu_lock_path"])

    def write_result(self, j, state, rc, secs, ws, commit, vram):
        """result.json + a copy of the log inside the job's output folder (the record of what produced the files)."""
        try:
            d = Path(j["outdir"] or "")
            if not d.is_dir():
                return
            info = dict(job_id=j["id"], name=j["name"], type=j["type"], requester=j["requester"], state=state, exit_code=rc, seconds=round(secs, 1),
                        peak_ram_gb=round(ws, 2), peak_commit_gb=round(commit, 2), peak_vram_gb=round(vram, 2), command=j["cmd"], finished=time.strftime("%Y-%m-%d %H:%M:%S"))
            (d / "result.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
            if j.get("log") and os.path.exists(j["log"]):
                shutil.copyfile(j["log"], d / "job.log")
        except OSError:
            pass

    def apply_suspensions(self):
        c = self.cfg
        lim = c["limits"]
        brake_on = bool(self.brake) and c.get("emergency_suspend", True)
        if brake_on:
            cand = [lv for lv in sorted(self.live.values(), key=lambda x: -x.t0) if not lv.susp_brake and not lv.suspended]
            if cand:
                cand[0].susp_brake = True
                self.log("SAFETY BRAKE: suspended the youngest job (%s)" % self.brake)
        elif self.sys.get("ram_avail", 99) > lim["hard_free_ram_gb"] + 4 and self.sys.get("commit_avail", 999) > lim["hard_commit_free_gb"] + 8:
            old = [lv for lv in sorted(self.live.values(), key=lambda x: x.t0) if lv.susp_brake]
            if old:
                old[0].susp_brake = False
                self.log("memory recovered: resumed a job held by the brake")
        for jid, lv in self.live.items():
            j = self.store.get(jid)
            want = (lv.susp_user or lv.susp_brake or (c["paused"] and c["suspend_on_pause"]) or (c["playing"] and c["playing_suspends_gpu"] and j["klass"] == "gpu"))
            if want and not lv.suspended:
                self._suspend(lv)
                self.store.update(jid, state="paused")
            elif not want and lv.suspended:
                self._unsuspend(lv)
                self.store.update(jid, state="running")

    def refresh_estimates(self, queued):
        cache = {}
        for j in queued:
            if j["est_source"].startswith("given"):
                continue
            if j["est_key"] not in cache:
                t = self.types.get(j["type"], {})
                default = dict(ram_gb=2.0, vram_gb=0.0, commit_gb=3.0)
                default.update(t.get("est") or {})
                cache[j["est_key"]] = st.learned_estimate(self.store, j["est_key"], default)
            e = cache[j["est_key"]]
            if (abs(e["ram_gb"] - j["est_ram"]) > 0.01 or e["source"] != j["est_source"]):
                self.store.update(j["id"], est_ram=e["ram_gb"], est_vram=e["vram_gb"], est_commit=e["commit_gb"], est_source=e["source"])
                j.update(est_ram=e["ram_gb"], est_vram=e["vram_gb"], est_commit=e["commit_gb"], est_source=e["source"])

    def schedule(self):
        queued = self.store.by_state("queued")
        self.refresh_estimates(queued)
        now = time.time()
        for j in queued:
            j["waited_s"] = now - j["submitted"]
            j["after_ok"] = True
            if j["after_id"]:
                a = self.store.get(j["after_id"])
                j["after_ok"] = bool(a and a["state"] == "done")
                if a and a["state"] in ("failed", "cancelled", "lost"):
                    self.store.update(j["id"], state="cancelled", finished=now, note="dependency #%d %s" % (a["id"], a["state"]))
                    self.hist_rev += 1
                    j["state"] = "cancelled"
        queued = [j for j in queued if j["state"] == "queued"]
        running = []
        for jid, lv in self.live.items():
            j = self.store.get(jid)
            running.append(dict(est_ram=j["est_ram"], est_vram=j["est_vram"], est_commit=j["est_commit"], cur_ws=lv.cur_ws, cur_vram=lv.cur_vram, cur_commit=lv.cur_commit,
                                type=j["type"], model=j["model"], klass=j["klass"], hold_lock=j["hold_lock"], self_lock=j["self_lock"]))
        warm = {r["model"] for r in running} | {m for m, t in self.finished_models.items() if now - t < self.cfg["warm_s"]}
        lock = wu.lock_state(self.cfg["gpu_lock_path"], self.owns_lock)
        flags = dict(paused=self.cfg["paused"], playing=self.cfg["playing"])
        starts, self.reasons, self.brake = scheduler.plan(queued, running, self.cfg["limits"], flags, self.sys, lock, warm, self.cfg)
        for j in starts:
            if j["hold_lock"] and not self.owns_lock:
                if not wu.lock_take(self.cfg["gpu_lock_path"], "aibroker"):
                    self.reasons[j["id"]] = "GPU lock could not be taken"
                    continue
                self.owns_lock = True
            self.start(j)

    def start(self, j):
        jid = j["id"]
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in (j["env"] or {}).items()})
        env.update(AIBROKER="1", AIBROKER_JOB_ID=str(jid))
        env.setdefault("PYTHONUTF8", "1")
        fh = open(j["log"], "ab")
        fh.write(("[broker] job #%d %s\n[broker] cmd: %s\n[broker] est RAM %.1f GB, VRAM %.1f GB (%s)\n" % (jid, j["name"], subprocess.list2cmdline(j["cmd"]), j["est_ram"], j["est_vram"], j["est_source"])).encode())
        fh.flush()
        try:
            proc = subprocess.Popen(j["cmd"], cwd=j["cwd"] or None, env=env, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    creationflags=wu.NO_WINDOW | wu.BELOW_NORMAL | wu.NEW_GROUP)
        except OSError as e:
            fh.write(("[broker] cannot start: %r\n" % (e,)).encode())
            fh.close()
            self.store.update(jid, state="failed", started=time.time(), finished=time.time(), rc=-1, note="cannot start: %r" % (e,))
            self.hist_rev += 1
            self.log("#%d failed to start: %r" % (jid, e))
            return
        jo = wu.JobObject()
        jo.assign(proc)
        lv = Live(proc, jo, fh)
        self.live[jid] = lv
        self.store.update(jid, state="running", started=time.time(), pid=proc.pid, avail_before=round(self.sys.get("ram_avail", 0), 1))
        self.log("started #%d %s (pid %d, est RAM %.1f GB, VRAM %.1f GB; %d running)" % (jid, j["name"], proc.pid, j["est_ram"], j["est_vram"], len(self.live)))

    def tick(self):
        with self.lock:
            self.sample_system()
            self.monitor()
            self.finalize()
            self.schedule()
            self.apply_suspensions()
            if self.hist_rev % 50 == 0:
                self.store.prune(self.cfg["history_keep"])

    def loop(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                self.log("tick error: " + traceback.format_exc().replace("\n", " | ")[-600:])
            self.stop.wait(1.0)

    # ------------------------------------------------------------ views
    def job_view(self, j):
        lv = self.live.get(j["id"])
        d = {k: j[k] for k in ("id", "type", "name", "requester", "state", "model", "klass", "est_ram", "est_vram", "est_commit", "est_source", "held", "manual", "submitted",
                              "started", "finished", "rc", "peak_ws", "peak_commit", "peak_vram", "after_id", "note", "pid", "outdir", "params")}
        d["pos"] = j["pos"]
        d["typical_s"], d["typical_n"] = self.typical(j["est_key"])
        if lv:
            d.update(cur_ws=round(lv.cur_ws, 2), cur_vram=round(lv.cur_vram, 2), elapsed=round(time.time() - lv.t0), suspended=lv.suspended)
        if j["state"] == "queued":
            d["reason"] = self.reasons.get(j["id"], "")
        return d

    def state(self, ev_since=0):
        with self.lock:
            running = [self.job_view(self.store.get(i)) for i in self.live]
            queued = [self.job_view(j) for j in self.store.by_state("queued")]
            lim = self.cfg["limits"]
            est_ram = sum(max(r["est_ram"], r.get("cur_ws", 0)) for r in running)
            est_vram = sum(max(r["est_vram"], r.get("cur_vram", 0)) for r in running)
            status = "BRAKE" if self.brake else "PLAYING" if self.cfg["playing"] else "PAUSED" if self.cfg["paused"] else "ACTIVE"
            return dict(ok=True, sys=self.sys, limits=lim, paused=self.cfg["paused"], playing=self.cfg["playing"], status=status, brake=self.brake,
                        flags={k: self.cfg[k] for k in ("suspend_on_pause", "playing_suspends_gpu", "emergency_suspend", "affinity", "backfill", "toast", "respect_gpu_lock")},
                        running=running, queued=queued, budget=dict(ram=est_ram, vram=est_vram), hist_rev=self.hist_rev,
                        lock="ours" if self.owns_lock else wu.lock_state(self.cfg["gpu_lock_path"], False), lock_holder=wu.lock_holder(self.cfg["gpu_lock_path"]),
                        events=[e for e in self.events if e[0] > ev_since], ev_n=self.ev_n, uptime=time.time() - self.t_start, pid=os.getpid(),
                        perms=self.perm_pending(), assistant_level=self.cfg.get("assistant_level", permissions.DEFAULT_LEVEL))

    # ------------------------------------------------------------ the in-window assistant asks for permission
    def perm_ask(self, req):
        """Claude Code (headless, in the window) asks if a tool call may run. The permission level the owner chose decides: allow at once, deny, or put a
        question in the window and wait (perm_get polls, perm_answer is the owner's click)."""
        tool = str(req.get("tool", ""))
        v = permissions.analyze(tool, req.get("input") or {})
        level = self.cfg.get("assistant_level", permissions.DEFAULT_LEVEL)
        decision = permissions.decide(level, v)
        with self.lock:
            self.perm_n += 1
            now = time.time()
            e = dict(id=self.perm_n, ts=now, polled=now, tool=tool, text=v.text, risk=v.risk, kind=v.kind, why=v.why, detail=(v.detail or "")[:3000], shell=v.shell,
                     level=level, state={"allow": "allow", "deny": "deny", "ask": "pending"}[decision], message="")
            if decision == "deny":
                e["message"] = "חסום תמיד: %s. %s" % (v.text, v.why)
            for k in [k for k, x in self.perms.items() if now - x["ts"] > 3600]:
                del self.perms[k]
            self.perms[e["id"]] = e
        self.log("assistant %s [%s]: %s" % (decision if decision != "ask" else "asks the owner", level, v.text))
        return dict(ok=True, id=e["id"], state=e["state"], message=e["message"], text=e["text"])

    def perm_get(self, pid):
        with self.lock:
            e = self.perms.get(pid)
            if not e:
                return dict(ok=False, error="no such request")
            e["polled"] = time.time()
            return dict(ok=True, state=e["state"], message=e["message"])

    def perm_answer(self, pid, allow, message=""):
        with self.lock:
            e = self.perms.get(pid)
            if not e or e["state"] != "pending":
                return dict(ok=False, error="request is not waiting")
            e["state"] = "allow" if allow else "deny"
            e["message"] = "" if allow else (message or "המשתמש דחה את הפעולה. הצע חלופה או המשך בלי זה.")
        self.log("owner %s: %s" % ("allowed" if allow else "declined", e["text"]))
        return dict(ok=True)

    def perm_pending(self):
        """Questions waiting for the owner. One that Claude stopped polling for (the turn was cancelled) is dropped."""
        now = time.time()
        out = []
        for e in self.perms.values():
            if e["state"] != "pending":
                continue
            if now - e["polled"] > 20:
                e["state"] = "expired"
                continue
            out.append({k: e[k] for k in ("id", "ts", "tool", "text", "risk", "kind", "why", "detail", "shell", "level")})
        return out

    def tail(self, jid, nbytes=20000):
        j = self.store.get(jid)
        if not j or not j.get("log"):
            return ""
        try:
            with open(j["log"], "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - nbytes))
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    # ------------------------------------------------------------ rpc
    def handle(self, req):
        op = req.get("op")
        c = self.cfg
        if op == "ping":
            return dict(ok=True, pid=os.getpid(), version="1.0")
        if op == "state":
            return self.state(int(req.get("ev_since", 0)))
        if op == "submit":
            return dict(ok=True, id=self.submit(req))
        if op == "get":
            with self.lock:
                j = self.store.get(int(req["id"]))
                return dict(ok=True, job=self.job_view(j)) if j else dict(ok=False, error="no job #%s" % req["id"])
        if op == "history":
            with self.lock:
                return dict(ok=True, jobs=[self.job_view(j) for j in self.store.finished(int(req.get("limit", 200)))])
        if op == "move":
            self.move([int(i) for i in req["ids"]], req["to"])
            return dict(ok=True)
        if op == "type_stats":
            with self.lock:
                return dict(ok=True, stats=self.store.type_stats())
        if op == "preview":
            with self.lock:
                return dict(ok=True, id=self.ensure_preview(req["path"]))
        if op == "rerun":
            return dict(ok=True, id=self.rerun(int(req["id"]), req.get("requester")))
        if op == "cancel":
            self.cancel(int(req["id"]))
            return dict(ok=True)
        if op == "job_pause":
            self.job_pause(int(req["id"]))
            return dict(ok=True)
        if op == "job_resume":
            self.job_resume(int(req["id"]))
            return dict(ok=True)
        if op == "pause":
            c["paused"] = True
            if "suspend" in req:
                c["suspend_on_pause"] = bool(req["suspend"])
            self.save_cfg()
            self.log("PAUSED (queue%s)" % (" + running jobs suspended" if c["suspend_on_pause"] else ""))
            return dict(ok=True)
        if op == "resume":
            c["paused"] = False
            self.save_cfg()
            self.log("RESUMED")
            return dict(ok=True)
        if op == "playing":
            c["playing"] = bool(req["on"])
            self.save_cfg()
            self.log("I AM PLAYING / RECORDING: " + ("ON (GPU jobs wait, running GPU jobs suspended)" if c["playing"] else "off"))
            return dict(ok=True)
        if op == "limits":
            with self.lock:
                for k, v in (req.get("set") or {}).items():
                    if k in c["limits"]:
                        c["limits"][k] = type(c["limits"][k])(v)
                for k, v in (req.get("flags") or {}).items():
                    if k in ("suspend_on_pause", "playing_suspends_gpu", "emergency_suspend", "affinity", "backfill", "toast", "respect_gpu_lock"):
                        c[k] = bool(v)
                if req.get("set") or req.get("flags"):
                    self.save_cfg()
                    self.log("limits/flags changed: %s %s" % (req.get("set") or "", req.get("flags") or ""))
                return dict(ok=True, limits=c["limits"])
        if op == "assistant_level":
            if req.get("set") in permissions.LEVEL_KEYS:
                c["assistant_level"] = req["set"]
                self.save_cfg()
                self.log("assistant permission level -> %s" % req["set"])
            return dict(ok=True, level=c.get("assistant_level", permissions.DEFAULT_LEVEL))
        if op == "perm_ask":
            return self.perm_ask(req)
        if op == "perm_get":
            return self.perm_get(int(req["id"]))
        if op == "perm_answer":
            return self.perm_answer(int(req["id"]), bool(req.get("allow")), str(req.get("message", "")))
        if op == "hardware":
            return hardware.profile()
        if op == "tail":
            return dict(ok=True, text=self.tail(int(req["id"]), int(req.get("bytes", 20000))))
        if op == "types":
            self.types = st.load_types()
            return dict(ok=True, types=self.types, vars=c["vars"], output_root=c["output_root"])
        if op == "shutdown":
            self.log("shutdown requested")
            if self.owns_lock and not any((self.store.get(i) or {}).get("hold_lock") for i in self.live):
                wu.lock_release(self.cfg["gpu_lock_path"])
                self.owns_lock = False
            self.stop.set()
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
            return dict(ok=True)
        return dict(ok=False, error="unknown op %r" % op)


def render_cwd(t, cfgvars, params):
    cw = t.get("cwd")
    return st.render(cw, dict(cfgvars, **params)) if cw else None


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(1 << 20)
            if not line:
                return
            req = json.loads(line.decode("utf-8"))
            try:
                resp = self.server.broker.handle(req)
            except (ValueError, KeyError) as e:
                resp = dict(ok=False, error=str(e) if isinstance(e, ValueError) else "missing field %s" % e)
            except Exception:
                resp = dict(ok=False, error=traceback.format_exc()[-400:])
            self.wfile.write((json.dumps(resp, default=str) + "\n").encode("utf-8"))
        except (OSError, ValueError):
            pass


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = False         # a second broker must fail to bind
    daemon_threads = True


def main():
    try:
        srv = Server(("127.0.0.1", paths.PORT), Handler)
    except OSError:
        print("broker already running on port %d" % paths.PORT)
        return 1
    broker = Broker()
    srv.broker = broker
    threading.Thread(target=broker.loop, daemon=True).start()
    try:
        srv.serve_forever()
    finally:
        if broker.owns_lock:
            wu.lock_release(broker.cfg["gpu_lock_path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
