"""Scheduler rule tests (pure logic).  Run:  .venv\\Scripts\\python.exe tests\\test_scheduler.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from aibroker import scheduler

LIM = dict(ram_gb=46.0, vram_gb=14.0, max_jobs=4, reserve_ram_gb=6.0, min_commit_free_gb=20.0, hard_free_ram_gb=2.5, hard_commit_free_gb=8.0)
CFG = dict(affinity=True, affinity_window=8, backfill=True, starve_s=900, respect_gpu_lock=True)
SYS = dict(ram_avail=58.0, commit_avail=150.0, gpu_used=0.0)


def job(i, typ, ram, vram=0.0, model=None, klass=None, **kw):
    d = dict(id=i, type=typ, est_ram=ram, est_vram=vram, est_commit=ram * 1.3, model=model or typ, klass=klass or ("gpu" if vram else "cpu"), max_parallel=kw.pop("max_parallel", 0),
             manual=0, held=0, after_ok=True, waited_s=0, hold_lock=1 if vram else 0, self_lock=0)
    d.update(kw)
    return d


def run(q, running=(), flags=None, sysinfo=None, lock="none", warm=(), lim=None, cfg=None):
    return scheduler.plan(q, list(running), lim or LIM, flags or dict(paused=False, playing=False), sysinfo or SYS, lock, set(warm), cfg or CFG)


def ids(r):
    return [j["id"] for j in r[0]]


def test_pack_three():
    q = [job(1, "triposg", 7, 7, max_parallel=1), job(2, "blender", 4), job(3, "blender", 4)]
    assert ids(run(q)) == [1, 2, 3]


def test_ram_budget_backfill():
    q = [job(1, "qwen", 36, 9, max_parallel=1), job(2, "bl", 4), job(3, "bl", 4), job(4, "bl", 4)]
    r = run(q)
    assert ids(r) == [1, 2, 3], r          # 36+4+4 = 44 fits, +4 = 48 > 46
    assert "RAM budget" in r[1][4]
    r = run([job(1, "qwen", 36, 9), job(2, "triposg", 7, 7)])
    assert ids(r) == [1] and "VRAM" in r[1][2]   # 9 + 7 > 14 GB of VRAM


def test_vram_budget():
    q = [job(1, "a", 5, 9), job(2, "b", 5, 9)]
    r = run(q)
    assert ids(r) == [1] and "VRAM" in r[1][2]


def test_foreign_vram_counts():
    q = [job(1, "a", 5, 9)]
    r = run(q, sysinfo=dict(SYS, gpu_used=8.0))        # the game already uses 8 GB
    assert ids(r) == [] and "VRAM" in r[1][1]


def test_max_parallel():
    run1 = dict(est_ram=7, est_vram=7, est_commit=9, cur_ws=6, cur_vram=6, cur_commit=8, type="triposg", model="triposg", klass="gpu", hold_lock=1, self_lock=0)
    r = run([job(2, "triposg", 7, 7, max_parallel=1)], running=[run1])
    assert ids(r) == [] and "max_parallel" in r[1][2]


def test_paused_playing():
    q = [job(1, "a", 5, 5), job(2, "b", 2)]
    assert ids(run(q, flags=dict(paused=True, playing=False))) == []
    assert ids(run(q, flags=dict(paused=False, playing=True))) == [2]      # the CPU job still runs while playing


def test_brake():
    r = run([job(1, "a", 1)], sysinfo=dict(SYS, ram_avail=2.0))
    assert ids(r) == [] and r[2].startswith("BRAKE")


def test_reserve():
    r = run([job(1, "a", 10)], sysinfo=dict(SYS, ram_avail=14.0))
    assert ids(r) == [] and "free RAM" in r[1][1]


def test_affinity_lifts_same_model():
    q = [job(1, "qwen", 36, 9, model="qwen"), job(2, "triposg", 7, 7, model="triposg"), job(3, "triposg", 7, 7, model="triposg")]
    order = [j["id"] for j in scheduler.affinity_order(q, {"triposg"}, 8, True)]
    assert order == [2, 3, 1]


def test_affinity_respects_manual():
    q = [job(1, "qwen", 36, 9, model="qwen", manual=1), job(2, "triposg", 7, 7, model="triposg")]
    assert [j["id"] for j in scheduler.affinity_order(q, {"triposg"}, 8, True)] == [1, 2]


def test_starvation_guard():
    q = [job(1, "qwen", 36, 9, waited_s=2000), job(2, "blender", 4)]
    run1 = dict(est_ram=10, est_vram=0, est_commit=12, cur_ws=10, cur_vram=0, cur_commit=12, type="x", model="x", klass="cpu", hold_lock=0, self_lock=0)
    r = run(q, running=[run1, dict(run1, est_ram=20, cur_ws=20)])           # 30 running + 36 > 46 -> head blocked
    assert ids(r) == [] and "starvation" in r[1][2]


def test_disk_gate():
    run1 = dict(est_ram=7, est_vram=0, est_commit=9, cur_ws=6, cur_vram=0, cur_commit=8, type="x", model="x", klass="cpu", hold_lock=0, self_lock=0)
    lim = dict(LIM, disk_busy_pct=85.0)
    busy = dict(SYS, disk_avg=95.0)
    assert ids(run([job(1, "a", 2)], running=[run1], sysinfo=busy, lim=lim)) == []          # a job runs and the disk is busy: wait
    assert "disk busy" in run([job(1, "a", 2)], running=[run1], sysinfo=busy, lim=lim)[1][1]
    assert ids(run([job(1, "a", 2)], running=[], sysinfo=busy, lim=lim)) == [1]              # nothing running: never block a lone job
    assert ids(run([job(1, "a", 2)], running=[run1], sysinfo=dict(SYS, disk_avg=40.0), lim=lim)) == [1]


def test_foreign_lock_and_self_lock():
    assert ids(run([job(1, "a", 5, 5)], lock="foreign")) == []
    g = job(2, "godot", 4, 3, self_lock=1, hold_lock=0)
    holder = dict(est_ram=7, est_vram=7, est_commit=9, cur_ws=6, cur_vram=6, cur_commit=8, type="triposg", model="triposg", klass="gpu", hold_lock=1, self_lock=0)
    r = run([g], running=[holder])
    assert ids(r) == [] and "lock" in r[1][2]


def test_vram_reason_has_numbers_and_names():
    """The owner asked why a job waited with '10 GB free': the reason now says what the job needs, how much is free and who holds the rest."""
    sysinfo = dict(SYS, gpu_used=6.0, gpu_hogs=[("chrome.exe", 2.5), ("python.exe", 2.0)])
    lim = dict(LIM, vram_gb=16.0)
    r = run([job(1, "zimage", 15.3, 13.6)], sysinfo=sysinfo, lim=lim)
    assert ids(r) == []
    why = r[1][1]
    assert why.startswith("VRAM budget") and "13.6 GB needed" in why and "6.0 GB by other programs" in why and "chrome.exe 2.5 GB" in why and "16 GB limit" in why, why


def test_force_start_skips_the_soft_budgets_only():
    sysinfo = dict(SYS, gpu_used=6.0)
    lim = dict(LIM, vram_gb=16.0)
    q = [job(1, "zimage", 15.3, 13.6, manual=2)]
    assert ids(run(q, sysinfo=sysinfo, lim=lim)) == [1]                                       # "run anyway": the VRAM budget is skipped
    assert ids(run([dict(q[0], manual=1)], sysinfo=sysinfo, lim=lim)) == []                   # moved by hand is NOT "run anyway"
    assert ids(run(q, sysinfo=sysinfo, lim=lim, flags=dict(paused=True, playing=False))) == []           # the pause stays
    assert ids(run(q, sysinfo=sysinfo, lim=lim, flags=dict(paused=False, playing=True))) == []           # "I am playing" stays
    assert ids(run([dict(q[0], held=1)], sysinfo=sysinfo, lim=lim)) == []                    # held by the owner stays
    assert ids(run(q, sysinfo=dict(sysinfo, ram_avail=2.0), lim=lim)) == []                   # the hard RAM brake stays
    run1 = dict(est_ram=7, est_vram=7, est_commit=9, cur_ws=6, cur_vram=6, cur_commit=8, type="x", model="x", klass="gpu", hold_lock=0, self_lock=0)
    assert ids(run([dict(job(2, "zimage", 15.3, 13.6, manual=2), max_parallel=1)], running=[dict(run1, type="zimage")], sysinfo=sysinfo, lim=lim)) == []   # max_parallel stays


def test_vram_estimate_is_not_decided_by_one_outlier():
    import tempfile
    from aibroker import store
    s = store.Store.__new__(store.Store)
    peaks = [10.45, 6.52, 10.45, 12.39, 10.45]               # the real Z-Image history that made a job wait: one 12.4 GB run decided the estimate (13.6)
    s.history = lambda key: [dict(peak_ws=11.9, peak_commit=17.0, peak_vram=v) for v in peaks]
    est = store.learned_estimate(s, "zimage", dict(ram_gb=14, vram_gb=9, commit_gb=18))
    assert 11.0 <= est["vram_gb"] <= 12.0, est
    assert est["ram_gb"] > 12.0                                # RAM keeps the cautious rule


if __name__ == "__main__":
    n = 0
    for k, f in sorted(globals().items()):
        if k.startswith("test_"):
            f()
            n += 1
            print("ok", k)
    print(n, "tests passed")
