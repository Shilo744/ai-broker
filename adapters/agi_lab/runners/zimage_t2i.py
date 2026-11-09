"""Z-Image-Turbo text-to-image through a private ComfyUI.  zimage_t2i.py --prompt "..." --out out.png [--w 832 --h 1216 --seed 1 --steps 8]"""
import argparse
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "C:/Migrated/Projects/Personal/Games/_lab/tools/assets")
import comfy_common
import hero_lib

ap = argparse.ArgumentParser()
ap.add_argument("--prompt", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--w", type=int, default=832)
ap.add_argument("--h", type=int, default=1216)
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--steps", type=int, default=8)
a = ap.parse_args()
work = os.path.join(os.environ.get("TEMP", "."), "aibroker_comfy_%s" % os.environ.get("AIBROKER_JOB_ID", "x"))
with comfy_common.Comfy(work, custom_nodes=False) as c:
    t0 = time.time()
    png = c.run(hero_lib.t2i(a.prompt, a.w, a.h, a.seed, a.steps, "aib"))[0]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "wb").write(png)
    print("saved %s (%.0f s)" % (a.out, time.time() - t0), flush=True)
