"""Paths, ports and the editable config (limits, flags, path variables used by job-type command templates)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("AIBROKER_HOME") or (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ai-broker"))
PORT = int(os.environ.get("AIBROKER_PORT", "47600"))
LOGS = HOME / "logs"
DB = HOME / "state.db"
CONFIG = HOME / "config.json"
TYPES_DIR = ROOT / "jobtypes"
USER_TYPES_DIR = HOME / "jobtypes"          # same file format; overrides / extends the shipped types
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"

GAMES = "C:/Migrated/Projects/Personal/Games"          # only the default place of the shared legacy GPU lock
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
    "gpu_lock_path": GAMES + "/Assets/3D maker/characters/.gpu.lock",
    "toast": False,
    "history_keep": 500,
    "vars": {                         # {name} placeholders in jobtypes/*.json cmd templates
        "py_comfy": "C:/Migrated/AI/ComfyUI-Easy-Install/python_embeded/python.exe",
        "py_venv": str(VENV_PY).replace("\\", "/"),
        "blender": "C:/Programs/Blender/blender.exe",
        "runners": str(ROOT / "runners").replace("\\", "/"),
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
    try:
        _merge(cfg, json.loads(CONFIG.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG)
