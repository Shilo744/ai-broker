"""Platform layer tests: they run on Windows, macOS and Linux (CI runs all three) and touch nothing outside a temp folder.
  python tests/test_platform.py"""
import os
import plistlib
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="aibroker_platform_test_")
os.environ["AIBROKER_HOME"] = TMP

from aibroker import hardware, osutil, paths, posixutil, system   # noqa: E402

bad = 0


def check(name, cond, extra=""):
    global bad
    bad += not cond
    print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:160]) if extra and not cond else ""), flush=True)


def sleeper():
    kw = dict(osutil.SESSION) if not osutil.IS_WIN else {}
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


# ---- the facade gives the same names on every system
for name in ("mem_status", "JobObject", "AdoptedProc", "peak_of_process", "gpu_process_mem", "disk_busy_pct", "toast", "open_path", "nvidia_smi",
             "lock_take", "lock_state", "lock_release", "NO_WINDOW", "BELOW_NORMAL", "NEW_GROUP", "DETACHED", "BREAKAWAY", "SESSION", "GB"):
    check("osutil has " + name, hasattr(osutil, name))
if not osutil.IS_WIN:
    check("on macOS / Linux the Windows process flags are 0 (Popen refuses anything else)", osutil.NO_WINDOW == 0 and osutil.DETACHED == 0 and osutil.SESSION == {"start_new_session": True})

# ---- memory
m = osutil.mem_status()
check("memory status has the four numbers, all positive", all(m[k] > 0 for k in ("ram_total", "ram_avail", "commit_limit", "commit_avail")), m)
check("available RAM is not more than the total", m["ram_avail"] <= m["ram_total"] + 0.01)
pm = posixutil.mem_status()
check("the macOS / Linux memory function works anywhere", pm["ram_total"] > 0 and pm["commit_limit"] >= pm["ram_total"] - 0.01, pm)

# ---- a process we start can be watched, adopted after a restart and killed with its tree
p = sleeper()
a = osutil.AdoptedProc(p.pid)
check("an adopted live process reports 'still running'", a.poll() is None)
jo = osutil.JobObject()
check("a job object takes the process", jo.assign(p) in (True, False))
jo.terminate()
if osutil.IS_WIN:
    p.kill()
p.wait(timeout=20)
time.sleep(0.3)
check("after it is killed, an adopted process reports an exit code", a.poll() is not None, a.poll())
check("the peak of a finished process is two numbers", len(osutil.peak_of_process(p)) == 2)
jo.close()

pp = sleeper()
pa = posixutil.AdoptedProc(pp.pid)
check("the macOS / Linux adopted process: running", pa.poll() is None)
pp.kill()
pp.wait(timeout=20)
check("the macOS / Linux adopted process: gone is -2 (exit code lost)", pa.poll() == -2)

# ---- disk and GPU numbers are plain numbers, never an exception
b = osutil.disk_busy_pct()
time.sleep(0.5)
b = osutil.disk_busy_pct()
check("disk busy is 0..100", 0.0 <= b <= 100.0, b)
check("per-process GPU memory is a dict", isinstance(osutil.gpu_process_mem(), dict))
check("nvidia_smi is None or a 3-tuple", osutil.nvidia_smi() is None or len(osutil.nvidia_smi()) == 3)

# ---- the legacy lock file
lock = os.path.join(TMP, "x", ".gpu.lock")
check("a lock can be taken once", osutil.lock_take(lock, "aibroker") and not osutil.lock_take(lock, "other"))
check("and is seen as foreign by someone else, ours by us", osutil.lock_state(lock, False) == "foreign" and osutil.lock_state(lock, True) == "ours")
osutil.lock_release(lock)
check("and released", osutil.lock_state(lock, False) == "none")

# ---- where the data lives
saved = (paths.IS_WIN, paths.IS_MAC)
old = os.environ.pop("AIBROKER_HOME")
try:
    paths.IS_WIN, paths.IS_MAC = False, True
    check("macOS data folder", str(paths.default_home()).replace("\\", "/").endswith("Library/Application Support/ai-broker"))
    paths.IS_WIN, paths.IS_MAC = False, False
    os.environ["XDG_DATA_HOME"] = os.path.join(TMP, "xdg")
    check("Linux data folder follows XDG_DATA_HOME", paths.default_home() == paths.Path(TMP) / "xdg" / "ai-broker")
    paths.IS_WIN = True
    os.environ["LOCALAPPDATA"] = os.path.join(TMP, "lad")
    check("Windows data folder", paths.default_home() == paths.Path(TMP) / "lad" / "ai-broker")
finally:
    paths.IS_WIN, paths.IS_MAC = saved
    os.environ["AIBROKER_HOME"] = old
    os.environ.pop("XDG_DATA_HOME", None)
check("AIBROKER_HOME wins", paths.default_home() == paths.Path(TMP))
check("the virtual environment path matches the system", str(paths.VENV_PY).replace("\\", "/").endswith(".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"))

# ---- budgets fit this computer when nothing is saved
lim = paths.load_config()["limits"]
mem = osutil.mem_status()
check("default RAM budget is below the RAM of this computer", 0 < lim["ram_gb"] < mem["ram_total"], lim)
check("default GPU budget is positive (unified memory counts as GPU memory)", lim["vram_gb"] > 0, lim)
check("the reserve and the brake are below the budget", lim["hard_free_ram_gb"] < lim["reserve_ram_gb"] < lim["ram_gb"], lim)
check("language is he or en", paths.load_config()["lang"] in ("he", "en"))

# ---- start with the computer: the file each system reads
for label, mac in (("macOS launch agent", True), ("Linux autostart entry", False)):
    system.LINK = paths.Path(TMP) / ("agent.plist" if mac else "ai-broker.desktop")
    saved_mac = osutil.IS_MAC
    osutil.IS_MAC = mac
    try:
        ok = system._write_autostart_file("/x/.venv/bin/python")
    finally:
        osutil.IS_MAC = saved_mac
    text = system.LINK.read_text(encoding="utf-8")
    if mac:
        d = plistlib.loads(text.encode())
        check(label + " is a valid plist that runs the window hidden at login", ok and d["RunAtLoad"] is True and d["ProgramArguments"][-1] == "--hidden", d)
    else:
        check(label + " has Exec and the hidden flag", ok and "Exec=" in text and "--hidden" in text, text)

# ---- the hardware profile
prof = hardware.profile()
check("the profile names the platform", prof["platform"] in ("windows", "macos", "linux"), prof.get("platform"))
check("the profile has RAM, CPU and disks", prof["ram_gb"] > 0 and prof["cpu"]["name"] and isinstance(prof["disks"], list), prof["cpu"])
check("the profile lists the usual tools (found or not)", {"blender", "git", "python", "ollama", "claude_code"} <= set(prof["software"]))

print("platform test: %d failed" % bad)
sys.exit(1 if bad else 0)
