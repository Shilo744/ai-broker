"""FLUX.2 klein 4B (fp8) through a private ComfyUI: draws an image from a description, or, with --image, changes that image by instruction (colour, background, add / remove things).
  flux2_klein.py --prompt "..." --out out.png [--image in.png] [--w 1024 --h 1024 --seed 1 --steps 4]
With --image the picture keeps its own proportions (about 1 megapixel); --w/--h only apply to drawing from scratch."""
import argparse
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_common


def workflow(prompt, w, h, seed, steps, image=None):
    wf = {
        "194": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux-2-klein-4b-fp8.safetensors", "weight_dtype": "default"}},
        "195": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "flux2", "device": "default"}},
        "196": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["195", 0], "text": prompt}},
        "190": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
    }
    pos, neg = ["6", 0], ["190", 0]
    if image:
        wf["198"] = {"class_type": "LoadImage", "inputs": {"image": image}}
        wf["199"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["198", 0], "upscale_method": "nearest-exact", "megapixels": 1.0, "resolution_steps": 1}}
        wf["200"] = {"class_type": "GetImageSize", "inputs": {"image": ["199", 0]}}
        wf["206"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["199", 0], "vae": ["196", 0]}}
        wf["204"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["6", 0], "latent": ["206", 0]}}
        wf["205"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["190", 0], "latent": ["206", 0]}}
        wf["197"] = {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": ["200", 0], "height": ["200", 1], "batch_size": 1}}
        pos, neg = ["204", 0], ["205", 0]
    else:
        wf["197"] = {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}}
    wf["163"] = {"class_type": "KSampler", "inputs": {"model": ["194", 0], "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                                                      "positive": pos, "negative": neg, "latent_image": ["197", 0], "denoise": 1.0}}
    wf["164"] = {"class_type": "VAEDecode", "inputs": {"samples": ["163", 0], "vae": ["196", 0]}}
    wf["203"] = {"class_type": "SaveImage", "inputs": {"images": ["164", 0], "filename_prefix": "flux"}}
    return wf


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--image", default="")
    ap.add_argument("--w", type=int, default=1024)
    ap.add_argument("--h", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--steps", type=int, default=4)
    a = ap.parse_args()
    if a.image and not os.path.isfile(a.image):
        print("input image not found: %s" % a.image)
        sys.exit(2)
    work = os.path.join(os.environ.get("TEMP", "."), "aibroker_comfy_%s" % os.environ.get("AIBROKER_JOB_ID", "flux"))
    with comfy_common.Comfy(work, custom_nodes=False) as c:
        t0 = time.time()
        name = c.put(a.image) if a.image else None
        png = c.run(workflow(a.prompt, a.w, a.h, a.seed, a.steps, name))[0]
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "wb").write(png)
        print("saved %s (%.0f s)" % (a.out, time.time() - t0), flush=True)
