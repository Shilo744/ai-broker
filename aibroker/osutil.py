"""The one place the rest of the program asks the operating system for things (memory, process control, GPU numbers, notifications, opening a file).
Windows uses winutil (ctypes), macOS and Linux use posixutil (psutil). Nothing else in the package imports either of them directly."""
import os
import subprocess
import sys
import time

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
GB = 1024.0 ** 3

if IS_WIN:
    from .winutil import (AdoptedProc, JobObject, disk_busy_pct, gpu_process_mem, mem_status, open_path, peak_of_process, toast,        # noqa: F401
                          NO_WINDOW, BELOW_NORMAL, NEW_GROUP, DETACHED, BREAKAWAY)
    SESSION = {}                                             # kwargs that start a process in its own group (Windows: creationflags carry it)
else:
    from .posixutil import (AdoptedProc, JobObject, disk_busy_pct, gpu_process_mem, mem_status, open_path, peak_of_process, toast)      # noqa: F401
    NO_WINDOW = BELOW_NORMAL = NEW_GROUP = DETACHED = BREAKAWAY = 0
    SESSION = {"start_new_session": True}                    # own session = own process group: the whole tree can be signalled together


def nvidia_smi():
    """(used_gb, total_gb, util_pct) of the NVIDIA card, or None (no NVIDIA card, e.g. on a Mac)."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW)
        a = [float(x) for x in r.stdout.strip().splitlines()[0].split(",")]
        return a[0] / 1024.0, a[1] / 1024.0, a[2]
    except Exception:
        return None


# ---------------------------------------------------------------- legacy GPU lock (char_forge / gpu_lock.py convention)
LOCK_STALE_S = 1500


def lock_state(path, ours):
    """'none' | 'ours' | 'foreign' (a fresh lock file we did not write; one older than 25 min is stale)."""
    try:
        age = time.time() - os.stat(path).st_mtime
    except OSError:
        return "none"
    if ours:
        return "ours"
    return "foreign" if age < LOCK_STALE_S else "none"


def lock_holder(path):
    try:
        return open(path, encoding="utf-8").read().strip()
    except OSError:
        return ""


def lock_take(path, name):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:                                              # stale foreign lock: take it over
            if time.time() - os.stat(path).st_mtime >= LOCK_STALE_S:
                os.remove(path)
                return lock_take(path, name)
        except OSError:
            pass
        return False
    except OSError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("%s %s\n" % (name, time.strftime("%H:%M:%S")))
    return True


def lock_touch(path):
    try:
        os.utime(path)
    except OSError:
        pass


def lock_release(path):
    try:
        os.remove(path)
    except OSError:
        pass
