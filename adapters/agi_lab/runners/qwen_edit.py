"""Qwen-Image-Edit-2509 (Nunchaku fp4, 4 steps) through a private ComfyUI. Workflow = the lab's hero_lib.edit().
  qwen_edit.py --image a.png --instruction "..." --out out.png [--image2 b.png] [--seed 1] [--steps 4] [--megapix 1.0]
  qwen_edit.py --batch jobs.json     jobs: [{"image":..,"instruction":..,"out":..,"image2":..,"seed":..}]  (ONE ComfyUI start + model load for many edits)"""
import argparse
import json
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "C:/Migrated/Projects/Personal/Games/_lab/tools/assets")
import comfy_common
import hero_lib                      # only for the workflow builders (its Comfy class is not used)

ap = argparse.ArgumentParser()
ap.add_argument("--image")
ap.add_argument("--image2")
ap.add_argument("--instruction")
ap.add_argument("--out")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--steps", type=int, default=4)
ap.add_argument("--megapix", type=float, default=1.0)
ap.add_argument("--batch")
a = ap.parse_args()
jobs = json.load(open(a.batch)) if a.batch else [dict(image=a.image, image2=a.image2, instruction=a.instruction, out=a.out, seed=a.seed, steps=a.steps, megapix=a.megapix)]
work = os.path.join(os.environ.get("TEMP", "."), "aibroker_comfy_%s" % os.environ.get("AIBROKER_JOB_ID", "x"))
with comfy_common.Comfy(work, custom_nodes=True) as c:
    for j in jobs:
        t0 = time.time()
        i1 = c.put(j["image"])
        i2 = c.put(j["image2"]) if j.get("image2") else None
        wf = hero_lib.edit(j["instruction"], i1, i2, seed=j.get("seed", a.seed), steps=j.get("steps", a.steps), prefix="aib", megapix=j.get("megapix", a.megapix))
        png = c.run(wf)[0]
        os.makedirs(os.path.dirname(os.path.abspath(j["out"])), exist_ok=True)
        open(j["out"], "wb").write(png)
        print("saved %s (%d bytes, %.0f s)" % (j["out"], len(png), time.time() - t0), flush=True)
print("DONE", flush=True)
