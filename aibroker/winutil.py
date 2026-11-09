"""Windows backend of osutil (ctypes only, no pywin32): memory status, Job Objects (peak commit of a whole process tree), PDH counters
(per-process GPU memory, disk busy), toast. Imported only on Windows; everything else goes through aibroker.osutil."""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import time

NO_WINDOW = 0x08000000
BELOW_NORMAL = 0x00004000
NEW_GROUP = 0x00000200
DETACHED = 0x00000008
BREAKAWAY = 0x01000000
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

GB = 1024.0 ** 3


class _MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def mem_status():
    """Physical RAM and commit (RAM + pagefile) in GB."""
    m = _MEMSTAT()
    m.dwLength = ctypes.sizeof(m)
    k32.GlobalMemoryStatusEx(ctypes.byref(m))
    return {"ram_total": m.ullTotalPhys / GB, "ram_avail": m.ullAvailPhys / GB,
            "commit_limit": m.ullTotalPageFile / GB, "commit_avail": m.ullAvailPageFile / GB}


# ---------------------------------------------------------------- Job Object (peak commit of a tree)
class _BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wt.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]


class _IOC(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("ro", "wo", "oo", "rb", "wb", "ob")]


class _EXT(ctypes.Structure):
    _fields_ = [("Basic", _BASIC), ("Io", _IOC), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class JobObject:
    """Every job runs inside one; PeakJobMemoryUsed = peak commit summed over all its processes."""
    def __init__(self):
        k32.CreateJobObjectW.restype = wt.HANDLE
        self.h = k32.CreateJobObjectW(None, None)

    def assign(self, popen):
        k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        return bool(k32.AssignProcessToJobObject(self.h, int(popen._handle)))

    def peak_commit_gb(self):
        info = _EXT()
        k32.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
        if k32.QueryInformationJobObject(self.h, 9, ctypes.byref(info), ctypes.sizeof(info), None):
            return info.PeakJobMemoryUsed / GB
        return 0.0

    def terminate(self):
        k32.TerminateJobObject.argtypes = [wt.HANDLE, wt.UINT]
        k32.TerminateJobObject(self.h, 1)

    def close(self):
        k32.CloseHandle.argtypes = [wt.HANDLE]
        k32.CloseHandle(self.h)


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def peak_of_process(popen):
    """(peak working set GB, peak commit GB) of the ROOT process, readable from its handle even after it exited."""
    c = _PMC()
    c.cb = ctypes.sizeof(c)
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]
    if psapi.GetProcessMemoryInfo(int(popen._handle), ctypes.byref(c), c.cb):
        return c.PeakWorkingSetSize / GB, c.PeakPagefileUsage / GB
    return 0.0, 0.0


# ---------------------------------------------------------------- PDH
pdh = ctypes.WinDLL("pdh")
PDH_FMT_LARGE = 0x400
PDH_FMT_DOUBLE = 0x200
PDH_MORE_DATA = 0x800007D2


class _VAL(ctypes.Structure):
    _fields_ = [("CStatus", wt.DWORD), ("pad", wt.DWORD), ("v", ctypes.c_int64)]


class _ITEM(ctypes.Structure):
    _fields_ = [("name", ctypes.c_void_p), ("val", _VAL)]


class PdhQuery:
    """One wildcard or scalar counter. `array()` returns {instance_name: value}; `scalar()` a single float."""
    def __init__(self, path):
        self.q = ctypes.c_void_p()
        self.c = ctypes.c_void_p()
        self.ok = (pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.q)) == 0 and
                   pdh.PdhAddEnglishCounterW(self.q, path, 0, ctypes.byref(self.c)) == 0)
        if self.ok:
            pdh.PdhCollectQueryData(self.q)

    def array(self, fmt=PDH_FMT_LARGE):
        if not self.ok or pdh.PdhCollectQueryData(self.q) != 0:
            return {}
        size, cnt = wt.DWORD(0), wt.DWORD(0)
        if pdh.PdhGetFormattedCounterArrayW(self.c, fmt, ctypes.byref(size), ctypes.byref(cnt), None) & 0xFFFFFFFF != PDH_MORE_DATA:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        if pdh.PdhGetFormattedCounterArrayW(self.c, fmt, ctypes.byref(size), ctypes.byref(cnt), buf) != 0:
            return {}
        out = {}
        arr = ctypes.cast(buf, ctypes.POINTER(_ITEM))
        for i in range(cnt.value):
            it = arr[i]
            nm = ctypes.wstring_at(it.name)
            if fmt == PDH_FMT_DOUBLE:
                out[nm] = ctypes.c_double.from_buffer_copy(ctypes.c_int64(it.val.v)).value
            else:
                out[nm] = it.val.v
        return out


_gpu_q = None
_disk_q = None


def gpu_process_mem():
    """{pid: bytes dedicated GPU memory} from the 'GPU Process Memory' counter (nvidia-smi cannot show this on WDDM)."""
    global _gpu_q
    if _gpu_q is None:
        _gpu_q = PdhQuery(r"\GPU Process Memory(*)\Dedicated Usage")
    res = {}
    for name, val in _gpu_q.array().items():
        if name.startswith("pid_"):
            try:
                pid = int(name.split("_")[1])
            except ValueError:
                continue
            res[pid] = res.get(pid, 0) + val
    return res


def disk_busy_pct():
    global _disk_q
    if _disk_q is None:
        _disk_q = PdhQuery(r"\PhysicalDisk(_Total)\% Disk Time")
    arr = _disk_q.array(PDH_FMT_DOUBLE)
    return min(100.0, max(arr.values())) if arr else 0.0


def toast(title, text):
    """Windows toast notification through PowerShell/WinRT (no module needed). Fire and forget."""
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
          "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
          "$n=$t.GetElementsByTagName('text');$n.Item(0).AppendChild($t.CreateTextNode('%s'))|Out-Null;$n.Item(1).AppendChild($t.CreateTextNode('%s'))|Out-Null;"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('AI Broker').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
          % (title.replace("'", " ")[:80], text.replace("'", " ")[:200]))
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], creationflags=NO_WINDOW,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


class AdoptedProc:
    """A job process started by an earlier broker. It is opened by pid, so its real exit code can still be read when it ends."""
    def __init__(self, pid):
        k32.OpenProcess.restype = wt.HANDLE
        self._handle = k32.OpenProcess(0x1000 | 0x100000 | 0x0001 | 0x0100, False, int(pid))     # query limited, synchronize, terminate, set quota
        if not self._handle:
            raise OSError("cannot open pid %d" % pid)
        self.pid = int(pid)

    def poll(self):
        code = wt.DWORD()
        k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        if not k32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            return None
        return None if code.value == 259 else code.value


def open_path(path):
    os.startfile(str(path))
