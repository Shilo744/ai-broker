"""TripoSG (MIT) image -> raw shape GLB, no cleaning (the lab's part_shape.py logic with an output folder you choose, without its private lock).
Run with the ComfyUI python and PYTHONPATH set to the diso stand-in (the job type does this):
  triposg_shape.py --ref ref.png --out <dir> [--depth 9] [--seed 7] [--steps 50]      -> <dir>/raw_s<seed>.glb, <dir>/result.json
--ref may be an RGBA png (used as is) or a green-screen picture (keyed like the lab does)."""
import argparse
import gc
import json
import os
import sys
import time
TRI = r"C:\Migrated\AI\Tripo-3D-and-Voice\TripoSG"
sys.path.insert(0, TRI)
sys.path.insert(0, TRI + r"\scripts")
for _p in [x for x in os.environ.get("FORGE_SHAPE_PATHS", os.environ.get("PYTHONPATH", "")).split(";") if x]:
    sys.path.insert(0, _p)
sys.path.insert(0, "C:/Migrated/Projects/Personal/Games/_lab/modular/v3")
import numpy as np
import torch
import trimesh
from PIL import Image
from huggingface_hub import snapshot_download
from triposg.pipelines.pipeline_triposg import TripoSGPipeline
from image_process import prepare_image
from key_ref import key

ap = argparse.ArgumentParser()
ap.add_argument("--ref", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--depth", type=int, default=9)
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--steps", type=int, default=50)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
t0 = time.time()
rgba = os.path.join(a.out, "ref_rgba.png")
im = Image.open(a.ref)
if im.mode == "RGBA" and np.array(im)[..., 3].min() < 250:
    im.save(rgba)
else:
    Image.fromarray(key(a.ref, 0.10, 0.55), "RGBA").save(rgba)
img = prepare_image(rgba, bg_color=np.array([1.0, 1.0, 1.0]), rmbg_net=None)
w = snapshot_download(repo_id="VAST-AI/TripoSG", local_dir=r"C:\Migrated\AI\Tripo-3D-and-Voice\pretrained\TripoSG")
pipe = TripoSGPipeline.from_pretrained(w).to("cuda", torch.float16)
print("model loaded %.0f s" % (time.time() - t0), flush=True)
torch.cuda.reset_peak_memory_stats()
t1 = time.time()
d = a.depth
res = pipe(image=img, generator=torch.Generator(device="cuda").manual_seed(a.seed), num_inference_steps=a.steps, guidance_scale=7.0,
           use_flash_decoder=not os.environ.get("FORGE_SHAPE_NOFLASH"), flash_octree_depth=d, hierarchical_octree_depth=d, dense_octree_depth=min(8, d))
v, f = res.samples[0]
m = trimesh.Trimesh(v.astype(np.float32), np.ascontiguousarray(f))
m.fix_normals()
glb = os.path.join(a.out, "raw_s%d.glb" % a.seed)
m.export(glb)
info = dict(faces=int(len(m.faces)), secs=round(time.time() - t1, 1), torch_peak_vram_gb=round(torch.cuda.max_memory_allocated() / 1e9, 2), depth=d, glb=glb)
json.dump(info, open(os.path.join(a.out, "result.json"), "w"))
print("RESULT", json.dumps(info), flush=True)
del res, v, f, m
gc.collect()
torch.cuda.empty_cache()
