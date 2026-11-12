"""Paths, ports and the editable config (limits, flags, path variables used by job-type command templates)."""
import functools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
ROOT = Path(__file__).resolve().parent.parent


def default_home():
    """Where the program keeps its data: the queue database, logs, the config, chats. AIBROKER_HOME overrides it (tests use a throw-away folder)."""
    if os.environ.get("AIBROKER_HOME"):
        return Path(os.environ["AIBROKER_HOME"])
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ai-broker"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "ai-broker"
    return Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "ai-broker"


def system_lang():
    """'he' when the computer's language is Hebrew, otherwise 'en'."""
    import locale
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            code = (locale.getdefaultlocale()[0] or "")
    except Exception:
        code = ""
    return "he" if code.lower().startswith(("he", "iw")) else "en"


HOME = default_home()
PORT = int(os.environ.get("AIBROKER_PORT", "47600"))
LOGS = HOME / "logs"
DB = HOME / "state.db"
CONFIG = HOME / "config.json"
TYPES_DIR = ROOT / "jobtypes"
USER_TYPES_DIR = HOME / "jobtypes"          # same file format; overrides / extends the shipped types
if IS_WIN:
    VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
    VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"       # no console window
else:
    VENV_PY = ROOT / ".venv" / "bin" / "python"
    VENV_PYW = VENV_PY

PYTHON = VENV_PY if VENV_PY.exists() else Path(sys.executable)      # the private environment when it exists, otherwise the Python that runs us

GAMES = "C:/Migrated/Projects/Personal/Games"          # only the default place of the shared legacy GPU lock (used when that folder exists)


def _default_gpu_lock():
    legacy = GAMES + "/Assets/3D maker/characters/.gpu.lock"
    return legacy if os.path.isdir(os.path.dirname(legacy)) else str(HOME / ".gpu.lock").replace("\\", "/")


def code_stamp():
    """A number that changes when the program's code changes (the newest modification time of aibroker/*.py). The window and the service compare it with the one they started with
    to know they are running old code."""
    try:
        return "%d" % max(int(f.stat().st_mtime) for f in (ROOT / "aibroker").glob("*.py"))
    except (OSError, ValueError):
        return "0"


def _py_whisper():
    """The Python with faster-whisper: <program folder>/.local/envs/whisper (not in the data folder: on Windows an app that runs inside a package, like the Claude desktop app, sees a different copy of AppData); until it exists, the broker's own Python (the job then says faster-whisper is missing)."""
    p = ROOT / ".local" / "envs" / "whisper" / ("Scripts/python.exe" if IS_WIN else "bin/python")
    return str(p if p.exists() else PYTHON).replace("\\", "/")


def _default_blender():
    if IS_WIN:
        return "C:/Programs/Blender/blender.exe"
    return shutil.which("blender") or ("/Applications/Blender.app/Contents/MacOS/Blender" if IS_MAC else "blender")


@functools.lru_cache(maxsize=1)
def auto_limits():
    """Memory budgets that fit THIS computer (used until the owner saves his own): most of the RAM, the card's memory, a reserve that always stays free.
    With no NVIDIA card (a Mac, or a PC without one) the GPU budget is the RAM budget: the graphics memory is the same memory."""
    import psutil
    gb = 1024.0 ** 3
    total = psutil.virtual_memory().total / gb
    gpu_total = 0.0
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            r = subprocess.run([exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=6,
                               creationflags=0x08000000 if IS_WIN else 0)
            gpu_total = float(r.stdout.strip().splitlines()[0]) / 1024.0
        except Exception:
            gpu_total = 0.0
    ram = round(total * 0.8, 1)
    # Windows has a pagefile commit charge, so it gets its own floors; elsewhere "commit" is RAM + swap and the floors are the same as for RAM
    lim = dict(DEFAULT_CONFIG["limits"])
    reserve, hard = round(max(2.0, total * 0.1), 1), round(max(1.0, total * 0.05), 1)
    lim.update(ram_gb=ram, vram_gb=round(gpu_total * 0.9, 1) if gpu_total else ram, max_jobs=2 if total < 24 else 4,
               reserve_ram_gb=reserve, min_commit_free_gb=round(max(4.0, total * 0.15), 1) if IS_WIN else reserve,
               hard_free_ram_gb=hard, hard_commit_free_gb=round(max(2.0, total * 0.1), 1) if IS_WIN else hard)
    return lim


ADAPTERS = ROOT / "adapters"
DEFAULT_CONFIG = {
    "limits": {
        "ram_gb": 46.0,              # budget for the SUM of running jobs (physical RAM, working set)
        "vram_gb": 14.0,             # budget for jobs + whatever other programs already use on the GPU
        "max_jobs": 4,
        "reserve_ram_gb": 6.0,       # must stay free after a start
        "min_commit_free_gb": 20.0,  # free commit (RAM + pagefile) must stay above this after a start
        "hard_free_ram_gb": 2.5,     # safety brake: below this, nothing starts and the youngest job is suspended
        "hard_commit_free_gb": 8.0,
        "disk_busy_pct": 85.0,       # while a job runs and the disk is busier than this (10 s average), no further job starts
    },
    "paused": False,
    "playing": False,
    "suspend_on_pause": False,
    "playing_suspends_gpu": True,
    "emergency_suspend": True,
    "affinity": True,
    "affinity_window": 8,
    "warm_s": 180,
    "backfill": True,
    "starve_s": 900,
    "respect_gpu_lock": True,
    "gpu_lock_path": _default_gpu_lock(),
    "toast": False,
    "lang": system_lang(),           # UI language: "he" (right-to-left) or "en"; the computer's language until chosen
    "assistant_level": "normal",     # what the in-window Claude may do without asking: careful / normal / free
    "history_keep": 500,
    "auto_preview": True,            # after a job that wrote .glb files, queue a turntable preview job for each
    "output_root": str(ROOT / "output").replace("\\", "/"),   # every model type gets its own folder under here
    "vars": {                         # {name} placeholders in jobtypes/*.json cmd templates
        "py_comfy": "C:/Migrated/AI/ComfyUI-Easy-Install/python_embeded/python.exe" if IS_WIN else "",
        "py_venv": str(PYTHON).replace("\\", "/"),
        "blender": _default_blender(),
        "runners": str(ROOT / "runners").replace("\\", "/"),
        "py_whisper": _py_whisper(),      # Python that has faster-whisper (its own environment); the broker's own Python when that is missing, so the job says "not installed"
        "whisper_model": str(HOME / "models" / "whisper" / "ivrit-ai-large-v3-turbo-ct2").replace("\\", "/"),
        "whisper_model_full": str(ROOT / ".local" / "models" / "whisper" / "ivrit-ai-large-v3-ct2").replace("\\", "/"),      # the full large-v3 (more accurate, slower than the turbo one)
        "diar_seg": str(ROOT / ".local" / "models" / "diarization" / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx").replace("\\", "/"),
        "diar_emb": str(ROOT / ".local" / "models" / "diarization" / "3dspeaker_eres2net_base_16k.onnx").replace("\\", "/"),
        "cudnn_dir": "C:/Migrated/AI/ComfyUI-Easy-Install/python_embeded/Lib/site-packages/torch/lib" if IS_WIN else "",     # a folder that has cuDNN 9 (ComfyUI's torch ships it)
    },
}


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def adapter_vars():
    """vars.json of every adapter (project-specific paths); '{ROOT}' = this tool's folder."""
    out = {}
    for f in sorted(ADAPTERS.glob("*/vars.json")):
        try:
            for k, v in json.loads(f.read_text(encoding="utf-8")).items():
                out[k] = v.replace("{ROOT}", str(ROOT).replace("\\", "/"))
        except (OSError, ValueError):
            pass
    return out


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["vars"].update(adapter_vars())
    saved = {}
    try:
        saved = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not isinstance(saved.get("limits"), dict):
        cfg["limits"] = dict(auto_limits())               # nothing saved yet: budgets that fit this computer
    _merge(cfg, saved if isinstance(saved, dict) else {})
    return cfg


def save_config(cfg):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG)
