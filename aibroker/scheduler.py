"""Pure scheduling logic (no I/O): which queued jobs may start now, and why the others wait.

Inputs are plain dicts so the rule can be unit-tested (tests/test_scheduler.py).
  queued  : jobs in queue order. keys: id, klass('gpu'|'cpu'), est_ram, est_vram, est_commit, model, type, max_parallel, manual,
            hold_lock, self_lock, after_ok(bool), held(bool), waited_s
  running : jobs. keys: est_ram, est_vram, est_commit, cur_ws, cur_vram, cur_commit, type, model, klass, hold_lock, self_lock, age_s
  sysinfo : ram_avail, commit_avail, gpu_used (GB, whole card)
"""


def affinity_order(queued, warm_models, window, enabled):
    """Lift jobs whose model is already loaded ahead of other-model jobs inside the first `window` slots,
    but never past a job the owner moved by hand ('manual')."""
    if not enabled or not warm_models:
        return list(queued)
    head, rest = queued[:window], queued[window:]
    lifted, others, blocked = [], [], False
    for j in head:
        if j.get("manual"):
            blocked = True
        if not blocked and j.get("model") in warm_models:
            lifted.append(j)
        else:
            others.append(j)
    return lifted + others + rest


def _sum(running, key_est, key_cur):
    return sum(max(r.get(key_est, 0) or 0, r.get(key_cur, 0) or 0) for r in running)


def plan(queued, running, limits, flags, sysinfo, lock, warm_models, cfg):
    """Returns (starts, reasons). `reasons` maps job id -> why it waits (shown in the GUI)."""
    starts, reasons = [], {}
    run = [dict(r) for r in running]
    head_starving = bool(queued) and queued[0].get("waited_s", 0) > cfg.get("starve_s", 900)
    order = affinity_order(queued, warm_models, cfg.get("affinity_window", 8), cfg.get("affinity", True) and not head_starving)
    guard = False
    brake = None
    if sysinfo["ram_avail"] < limits["hard_free_ram_gb"]:
        brake = "BRAKE: free RAM %.1f GB < %.1f" % (sysinfo["ram_avail"], limits["hard_free_ram_gb"])
    elif sysinfo["commit_avail"] < limits["hard_commit_free_gb"]:
        brake = "BRAKE: free commit %.1f GB < %.1f" % (sysinfo["commit_avail"], limits["hard_commit_free_gb"])
    for idx, j in enumerate(order):
        why = None
        ram_used = _sum(run, "est_ram", "cur_ws")
        vram_used = _sum(run, "est_vram", "cur_vram")
        ramp_ram = sum(max(0.0, (r.get("est_ram") or 0) - (r.get("cur_ws") or 0)) for r in run)
        ramp_commit = sum(max(0.0, (r.get("est_commit") or 0) - (r.get("cur_commit") or 0)) for r in run)
        own_vram = sum(r.get("cur_vram") or 0 for r in run)
        foreign_vram = max(0.0, sysinfo.get("gpu_used", 0.0) - own_vram)
        gpu = j["klass"] == "gpu"
        if flags.get("paused"):
            why = "paused"
        elif brake:
            why = brake
        elif gpu and flags.get("playing"):
            why = "I am playing / recording: GPU jobs wait"
        elif j.get("held"):
            why = "held by owner"
        elif not j.get("after_ok", True):
            why = "waiting for the job it depends on"
        elif len(run) >= limits["max_jobs"]:
            why = "max concurrent jobs (%d)" % limits["max_jobs"]
        elif j.get("max_parallel") and sum(1 for r in run if r.get("type") == j["type"]) >= j["max_parallel"]:
            why = "another %s is running (max_parallel %d)" % (j["type"], j["max_parallel"])
        elif ram_used + j["est_ram"] > limits["ram_gb"] and run:
            why = "RAM budget: %.1f running + %.1f > %.0f GB" % (ram_used, j["est_ram"], limits["ram_gb"])
        elif gpu and vram_used + foreign_vram + j["est_vram"] > limits["vram_gb"] and (run or foreign_vram > 0):
            why = "VRAM budget: %.1f running + %.1f other + %.1f > %.0f GB" % (vram_used, foreign_vram, j["est_vram"], limits["vram_gb"])
        elif sysinfo["ram_avail"] - ramp_ram - j["est_ram"] < limits["reserve_ram_gb"]:
            why = "free RAM would drop below %.0f GB (now %.1f free)" % (limits["reserve_ram_gb"], sysinfo["ram_avail"])
        elif sysinfo["commit_avail"] - ramp_commit - j["est_commit"] < limits["min_commit_free_gb"]:
            why = "free commit would drop below %.0f GB" % limits["min_commit_free_gb"]
        elif (gpu or j.get("hold_lock") or j.get("self_lock")) and cfg.get("respect_gpu_lock", True):
            if lock == "foreign":
                why = "GPU lock held by another program"
            elif j.get("self_lock") and any(r.get("hold_lock") for r in run):
                why = "visual run needs the GPU lock, a broker GPU job holds it"
            elif j.get("hold_lock") and any(r.get("self_lock") for r in run):
                why = "a self-locking GPU run (Godot) is active"
        if why is None and guard:
            why = "starvation guard: the first job has waited too long, nothing overtakes it"
        if why is None:
            starts.append(j)
            run.append({"est_ram": j["est_ram"], "est_vram": j["est_vram"], "est_commit": j["est_commit"], "cur_ws": 0.0, "cur_vram": 0.0, "cur_commit": 0.0,
                        "type": j["type"], "model": j["model"], "klass": j["klass"], "hold_lock": j.get("hold_lock"), "self_lock": j.get("self_lock")})
        else:
            reasons[j["id"]] = why
            if idx == 0 and head_starving and why.startswith(("RAM budget", "VRAM budget", "free RAM", "free commit", "max concurrent", "another")):
                guard = True
            if not cfg.get("backfill", True) and not j.get("held"):
                for k in order[idx + 1:]:
                    reasons.setdefault(k["id"], "backfill off: waiting behind #%s" % j["id"])
                break
    return starts, reasons, brake
