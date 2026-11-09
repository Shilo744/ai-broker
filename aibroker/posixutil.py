"""macOS / Linux backend of osutil: memory and disk from psutil, a process-tree "job object", per-process GPU memory from nvidia-smi (Linux), notifications.
Pure Python, importable on any system (the pieces that need a POSIX call are guarded), so its logic can be tested anywhere."""
import os
import shutil
import signal
import subprocess
import sys
import time

import psutil

GB = 1024.0 ** 3


def mem_status():
    """Physical RAM and 'commit' in GB. There is no commit charge here, so commit = RAM + swap: what the system could still hand out."""
    vm = psutil.virtual_memory()
    try:
        sw = psutil.swap_memory()
        swap_total, swap_free = sw.total, sw.free
    except (OSError, AttributeError):
        swap_total = swap_free = 0
    return {"ram_total": vm.total / GB, "ram_avail": vm.available / GB,
            "commit_limit": (vm.total + swap_total) / GB, "commit_avail": (vm.available + swap_free) / GB}


class JobObject:
    """Stand-in for the Windows Job Object: the job runs in its own session / process group, so the whole tree can be killed together.
    The peak is sampled by the broker's monitor (no kernel counter exists), so peak_commit_gb() reports 0 and the broker uses its own samples."""
    def __init__(self):
        self.pgid = None

    def assign(self, popen):
        try:
            self.pgid = os.getpgid(popen.pid)
        except (AttributeError, OSError, ProcessLookupError):
            self.pgid = None
        return self.pgid is not None

    def peak_commit_gb(self):
        return 0.0

    def terminate(self):
        if self.pgid and hasattr(os, "killpg"):
            try:
                os.killpg(self.pgid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

    def close(self):
        pass


def peak_of_process(popen):
    """No kernel counter for a finished process: the broker's own samples are used."""
    return 0.0, 0.0


class AdoptedProc:
    """A job process started by an earlier broker. Only its being alive can be seen; the exit code of a process that is not our child is lost (-2)."""
    def __init__(self, pid):
        self.pid = int(pid)
        try:
            self._p = psutil.Process(self.pid)
        except psutil.Error as e:
            raise OSError("cannot open pid %d" % pid) from e

    def poll(self):
        try:
            if self._p.is_running() and self._p.status() != psutil.STATUS_ZOMBIE:
                return None
        except psutil.Error:
            pass
        return -2


def gpu_process_mem():
    """{pid: bytes} of GPU memory per process. NVIDIA on Linux can tell (nvidia-smi); macOS cannot, so nobody is blamed there."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {}
    try:
        r = subprocess.run([exe, "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        out = {}
        for line in r.stdout.strip().splitlines():
            a = [x.strip() for x in line.split(",")]
            if len(a) == 2 and a[0].isdigit():
                try:
                    out[int(a[0])] = out.get(int(a[0]), 0) + int(float(a[1]) * 1024 * 1024)
                except ValueError:
                    pass
        return out
    except Exception:
        return {}


_disk_prev = None


def disk_busy_pct():
    """Percent of the last interval the disk was busy. Linux reports busy_time; macOS does not, so it reads 0 (the gate then never closes)."""
    global _disk_prev
    try:
        c = psutil.disk_io_counters()
        busy = getattr(c, "busy_time", None)
    except Exception:
        return 0.0
    if busy is None:
        return 0.0
    now = time.time()
    prev, _disk_prev = _disk_prev, (now, busy)
    if not prev or now - prev[0] < 0.2:
        return 0.0
    return min(100.0, max(0.0, (busy - prev[1]) / ((now - prev[0]) * 1000.0) * 100.0))


def toast(title, text):
    """A desktop notification. Fire and forget."""
    title, text = title.replace('"', "'")[:80], text.replace('"', "'")[:200]
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e", 'display notification "%s" with title "%s"' % (text, title)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def open_path(path):
    """Open a file or folder with the system's default program."""
    cmd = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([cmd, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
