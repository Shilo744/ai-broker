"""Model packs for the first-run setup: what the broker can run, what it needs, what fits this computer, what is already installed, and how to get the rest.

A pack is data (catalog/packs.json): the job types it enables, the hardware it needs, its licence, the files it needs (with the official URL, size and SHA-256 when the source
is verified) and the tools it runs on. Downloads are never started from here: the setup window turns the ticked packs into `download` jobs in the broker's queue."""
import json
import os
from pathlib import Path

from . import paths

GB = 1024.0 ** 3
CATALOG_DIRS = (paths.ROOT / "catalog", paths.HOME / "catalog")

CATEGORIES = (
    # key, Hebrew title, Hebrew one-liner, icon
    ("image", "תמונות", "ליצור תמונות מתיאור במילים, ולערוך תמונות קיימות", "image"),
    ("3d", "תלת-ממד", "להפוך תמונה לדגם תלת-ממדי, ולהכין אותו למשחק", "cube"),
    ("audio", "צלילים ומוזיקה", "מוזיקת רקע, אפקטים וקולות", "music"),
    ("game", "בדיקות משחק", "להריץ את המשחק ברקע ולצלם ממנו", "gamepad"),
    ("text", "מודל שפה (LLM)", "צ'אט ועזרה בטקסט על המחשב שלך. עוד לא נתמך: בקרוב", "sparkles"),
)


def load():
    """All packs from catalog/*.json (shipped) and <data folder>/catalog/*.json (your own). A pack with the same id in your folder replaces the shipped one."""
    packs = {}
    for d in CATALOG_DIRS:
        for f in sorted(Path(d).glob("*.json")) if Path(d).is_dir() else []:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for p in (data if isinstance(data, list) else data.get("packs", [])):
                if p.get("id"):
                    packs[p["id"]] = p
    return packs


def roots(cfg=None):
    """Folders the pack files are relative to, by name. From the broker's configured tool paths; the models folder is ours."""
    cfg = cfg or paths.load_config()
    v = cfg.get("vars", {})
    out = {"models": str(Path(cfg.get("models_root") or (paths.HOME / "models")))}
    py = v.get("py_comfy")
    if py and os.path.exists(str(py)):
        base = Path(str(py)).parent.parent
        cm = base / "ComfyUI" / "models"
        if cm.is_dir():
            out["comfy_models"] = str(cm)
    return out


def file_path(f, rts):
    base = rts.get(f.get("root", "models"))
    return str(Path(base) / f["dest"]) if base else None


def status(pack, rts, profile=None):
    """'installed' (every file there with the right size), 'partial', 'missing', or 'unknown' (nothing the program can check: the owner set it up another way).
    A pack that has no files, only tools to run on (Blender), is installed when those tools are found."""
    files = pack.get("files") or []
    detect = pack.get("detect") or []
    items = files or detect
    if not items:
        if pack.get("runtime") and profile is not None:
            return "installed" if not runtime_missing(pack, profile) else "missing"
        return "unknown"
    have = 0
    for f in items:
        p = file_path(f, rts)
        if p and os.path.isfile(p) and (not f.get("size") or os.path.getsize(p) == f["size"]):
            have += 1
    return "installed" if have == len(items) else "partial" if have else "missing"


def runtime_missing(pack, profile):
    """Tools the pack runs on that this computer does not have (from the hardware profile's software list)."""
    sw = (profile or {}).get("software", {})
    return [r for r in pack.get("runtime", []) if not sw.get(r)]


def verdict(pack, profile):
    """('ok' | 'tight' | 'no', [reasons]) for THIS computer. VRAM: 'ok' when the pack's comfortable need fits, 'tight' when only the minimum fits."""
    need = pack.get("needs", {})
    reasons = []
    level = "ok"
    gpu = (profile or {}).get("gpu") or {}
    vram = float(gpu.get("vram_gb") or 0)
    ram = float((profile or {}).get("ram_gb") or 0)
    vmin, vok = float(need.get("vram_min_gb", 0)), float(need.get("vram_ok_gb", need.get("vram_min_gb", 0)))
    if vmin and not vram:
        level = "no"
        reasons.append("no_gpu")
    elif vmin and vram < vmin:
        level = "no"
        reasons.append("vram_low")
    elif vok and vram < vok:
        level = "tight"
        reasons.append("vram_tight")
    if need.get("ram_gb") and ram and ram < float(need["ram_gb"]):
        level = "no" if level != "no" else level
        reasons.append("ram_low")
    return level, reasons


def plan(pack_ids, profile, rts=None, packs=None):
    """What to download for the chosen packs: [{pack, url, dest, sha256, size}], the total bytes, and what cannot be downloaded automatically."""
    packs = packs or load()
    rts = rts or roots()
    tasks, manual, total = [], [], 0
    for pid in pack_ids:
        p = packs.get(pid)
        if not p:
            continue
        files = p.get("files") or []
        if not files:
            manual.append(pid)
            continue
        for f in files:
            dest = file_path(f, rts)
            if not dest:
                manual.append(pid)
                break
            if os.path.isfile(dest) and (not f.get("size") or os.path.getsize(dest) == f["size"]):
                continue
            tasks.append({"pack": pid, "url": f["url"], "dest": dest, "sha256": f.get("sha256", ""), "size": int(f.get("size") or 0)})
            total += int(f.get("size") or 0)
    return {"tasks": tasks, "total_bytes": total, "manual": sorted(set(manual))}


def recommend(categories, profile, rts=None, packs=None):
    """The packs of the chosen categories, each with its verdict for this computer, its install state and the tools it still needs. Best fit first."""
    packs = packs or load()
    rts = rts or roots()
    out = []
    for p in packs.values():
        if categories and p.get("category") not in categories:
            continue
        lvl, why = verdict(p, profile)
        out.append({"pack": p, "fit": lvl, "why": why, "status": status(p, rts, profile), "missing_tools": runtime_missing(p, profile)})
    order = {"ok": 0, "tight": 1, "no": 2}
    out.sort(key=lambda r: (order[r["fit"]], r["pack"].get("title_en", r["pack"]["id"])))
    return out
