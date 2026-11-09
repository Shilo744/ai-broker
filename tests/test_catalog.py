"""Unit tests of the model catalog logic (no window, no network):  python tests/test_catalog.py"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import sandbox                                   # a throw-away data folder
from aibroker import catalog

bad = 0


def check(name, cond, extra=""):
    global bad
    print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)) if extra else ""))
    bad += not cond


tmp = tempfile.mkdtemp(prefix="aibroker_cat_")
rts = {"models": tmp, "comfy_models": os.path.join(tmp, "comfy")}
os.makedirs(rts["comfy_models"])
pack = {"id": "p", "category": "audio", "needs": {"vram_min_gb": 8, "vram_ok_gb": 12, "ram_gb": 16}, "runtime": ["comfyui"],
        "files": [{"root": "comfy_models", "dest": "a.bin", "url": "https://huggingface.co/x/a.bin", "size": 10, "sha256": "aa"},
                  {"root": "comfy_models", "dest": "b/c.bin", "url": "https://huggingface.co/x/c.bin", "size": 20, "sha256": "bb"}]}
big = {"vram_gb": 16}
mid = {"vram_gb": 10}
small = {"vram_gb": 6}
check("fits comfortably on a 16 GB card", catalog.verdict(pack, {"gpu": big, "ram_gb": 64}) == ("ok", []))
check("tight on a 10 GB card", catalog.verdict(pack, {"gpu": mid, "ram_gb": 64}) == ("tight", ["vram_tight"]))
check("does not fit a 6 GB card", catalog.verdict(pack, {"gpu": small, "ram_gb": 64})[0] == "no")
check("no GPU at all is a no", catalog.verdict(pack, {"gpu": None, "ram_gb": 64})[0] == "no")
check("too little RAM is a no", catalog.verdict(pack, {"gpu": big, "ram_gb": 8})[0] == "no")
check("nothing installed: missing", catalog.status(pack, rts) == "missing")
open(os.path.join(rts["comfy_models"], "a.bin"), "wb").write(b"x" * 10)
check("one of two files: partial", catalog.status(pack, rts) == "partial")
os.makedirs(os.path.join(rts["comfy_models"], "b"))
open(os.path.join(rts["comfy_models"], "b", "c.bin"), "wb").write(b"y" * 5)                 # wrong size
check("a file with the wrong size does not count", catalog.status(pack, rts) == "partial")
open(os.path.join(rts["comfy_models"], "b", "c.bin"), "wb").write(b"y" * 20)
check("both files, right sizes: installed", catalog.status(pack, rts) == "installed")
plan = catalog.plan(["p"], {}, rts, {"p": pack})
check("an installed pack has nothing to download", plan["tasks"] == [] and plan["total_bytes"] == 0)
os.remove(os.path.join(rts["comfy_models"], "a.bin"))
plan = catalog.plan(["p"], {}, rts, {"p": pack})
check("only the missing file is planned, with its size and checksum", len(plan["tasks"]) == 1 and plan["tasks"][0]["size"] == 10 and plan["tasks"][0]["sha256"] == "aa" and plan["total_bytes"] == 10, plan)
nofiles = {"id": "m", "category": "3d", "files": [], "manual": "do it by hand"}
check("a pack without files is manual", catalog.plan(["m"], {}, rts, {"m": nofiles})["manual"] == ["m"])
no_root = dict(pack, id="q", files=[{"root": "comfy_models", "dest": "z.bin", "url": "https://huggingface.co/x/z.bin", "size": 1}])
check("a pack whose tool folder is missing is manual, not downloaded to a wrong place", catalog.plan(["q"], {}, {"models": tmp}, {"q": no_root})["manual"] == ["q"])
detect = {"id": "d", "category": "image", "detect": [{"root": "comfy_models", "dest": "ck/x.safetensors"}]}
check("a detect-only pack is missing before the file exists", catalog.status(detect, rts) == "missing")
os.makedirs(os.path.join(rts["comfy_models"], "ck"))
open(os.path.join(rts["comfy_models"], "ck", "x.safetensors"), "wb").write(b"1")
check("and installed after", catalog.status(detect, rts) == "installed")
blender = {"id": "bl", "category": "3d", "runtime": ["blender"]}
check("a tools-only pack is installed when the tool is found", catalog.status(blender, rts, {"software": {"blender": "C:/b.exe"}}) == "installed" and catalog.status(blender, rts, {"software": {}}) == "missing")
shipped = catalog.load()
check("the shipped catalog loads and every downloadable file has an https URL, a size and a SHA-256",
      shipped and all(f["url"].startswith("https://huggingface.co/") and f["size"] > 0 and len(f["sha256"]) == 64 for p in shipped.values() for f in p.get("files", [])), len(shipped))
check("every shipped category is a known one", all(p["category"] in [c[0] for c in catalog.CATEGORIES] for p in shipped.values()))
mac = {"platform": "macos", "ram_gb": 32.0, "gpu": {"name": "Apple M3", "vram_gb": 32.0, "unified": True}, "software": {}}
win = {"platform": "windows", "ram_gb": 32.0, "gpu": {"name": "RTX", "vram_gb": 12.0}, "software": {}}
check("a CUDA-only pack does not fit a Mac, whatever its memory", catalog.verdict(shipped["triposg"], mac) == ("no", ["platform"]))
check("the same pack is judged by memory on Windows", catalog.verdict(shipped["triposg"], win)[0] in ("ok", "tight"))
check("a pack without a platform list fits any system (the language model)", catalog.verdict(shipped["ollama_llm"], mac)[0] == "ok")
check("unified memory counts as the graphics memory", catalog.verdict(shipped["acestep_music"], mac)[0] == "ok")
print("catalog test: %d failed" % bad)
sys.exit(1 if bad else 0)
