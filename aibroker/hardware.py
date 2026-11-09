"""What this computer can do: graphics card, memory, disks and the programs the models need. Read-only and fast (about a second).
Used by the assistant (the `hardware_profile` tool, so it never needs a shell command to look at the machine) and by the setup wizard."""
import os
import platform
import shutil
import subprocess

import psutil

from . import paths, winutil

GB = 1024.0 ** 3


def _gpu():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version,compute_cap", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=6, creationflags=winutil.NO_WINDOW)
        out = []
        for line in r.stdout.strip().splitlines():
            a = [x.strip() for x in line.split(",")]
            out.append({"name": a[0], "vram_gb": round(float(a[1]) / 1024.0, 1), "vram_used_gb": round(float(a[2]) / 1024.0, 1),
                        "driver": a[3] if len(a) > 3 else "", "compute_capability": a[4] if len(a) > 4 else ""})
        return out
    except Exception:
        return []


def _cpu_name():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
    except Exception:
        return platform.processor()


def _disks():
    out = []
    for p in psutil.disk_partitions(all=False):
        if "cdrom" in p.opts or not p.fstype:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        out.append({"drive": p.mountpoint.rstrip("\\"), "free_gb": round(u.free / GB, 1), "total_gb": round(u.total / GB, 1)})
    return out


def _which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _software():
    """Programs the models need, found from the broker's own configured paths first (vars: blender, py_comfy ...), then the usual places."""
    cfg = paths.load_config()
    vars_ = cfg.get("vars", {})

    def given(key):
        v = vars_.get(key)
        return str(v) if v and os.path.exists(str(v)) else None

    blender = given("blender") or _which("blender")
    if not blender:
        base = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Blender Foundation")
        if os.path.isdir(base):
            for d in sorted(os.listdir(base), reverse=True):
                exe = os.path.join(base, d, "blender.exe")
                if os.path.exists(exe):
                    blender = exe
                    break
    comfy_py = given("py_comfy")                      # ComfyUI's own embedded Python: its folder is the ComfyUI install
    comfy = None
    if comfy_py:
        root = os.path.dirname(os.path.dirname(comfy_py))
        comfy = root if os.path.isdir(os.path.join(root, "ComfyUI")) else os.path.dirname(comfy_py)
    return {"blender": blender, "git": _which("git"), "python": given("py_sys") or _which("python", "py"), "ffmpeg": _which("ffmpeg"), "claude_code": _which("claude"),
            "comfyui": comfy, "nvidia_smi": _which("nvidia-smi")}


def profile():
    mem = winutil.mem_status()
    cfg = paths.load_config()
    out_root = cfg.get("output_root") or str(paths.ROOT / "output")
    try:
        out_free = round(shutil.disk_usage(out_root if os.path.isdir(out_root) else os.path.dirname(out_root.rstrip("/\\")) or ".").free / GB, 1)
    except OSError:
        out_free = None
    gpus = _gpu()
    return {
        "ok": True,
        "os": platform.platform(),
        "cpu": {"name": _cpu_name(), "cores": psutil.cpu_count(logical=False), "threads": psutil.cpu_count(logical=True)},
        "ram_gb": round(mem["ram_total"], 1),
        "ram_free_gb": round(mem["ram_avail"], 1),
        "gpu": gpus[0] if gpus else None,
        "gpus": gpus,
        "disks": _disks(),
        "output_root": out_root,
        "output_free_gb": out_free,
        "software": _software(),
        "limits": cfg.get("limits", {}),
        "note": "vram_gb is the card's total memory; the broker's own limits (limits) may be lower. Models that need more VRAM than the card has will not run well.",
    }
