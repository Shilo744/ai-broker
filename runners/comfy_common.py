"""Private ComfyUI for broker jobs (own port, own folders, no lab guard: the broker does the scheduling).
Runs with the ComfyUI python:  C:/Migrated/AI/ComfyUI-Easy-Install/python_embeded/python.exe -I <runner>.py ..."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

COMFY = Path(os.environ.get("LAB_COMFY", "C:/Migrated/AI/ComfyUI-Easy-Install"))
PY = COMFY / "python_embeded" / "python.exe"
DOWNLOADS = os.environ.get("LAB_DOWNLOADS", "C:/Migrated/AI/lab_downloads")
sys.stdout.reconfigure(encoding="utf-8")


class Comfy:
    def __init__(self, work, custom_nodes=True, timeout=600):
        self.work, self.custom_nodes, self.timeout, self.proc = Path(work), custom_nodes, timeout, None

    def __enter__(self):
        for d in ("out", "tmp", "in"):
            (self.work / d).mkdir(parents=True, exist_ok=True)
        so = socket.socket()
        so.bind(("127.0.0.1", 0))
        self.port = so.getsockname()[1]
        so.close()
        yaml = ["labdl:", "    base_path: " + DOWNLOADS.replace("\\", "/") + "/", "    upscale_models: realesrgan", "    diffusion_models: acestep15/diffusion_models",
                "    text_encoders: acestep15/text_encoders", "    vae: acestep15/vae", ""]
        (self.work / "extra_model_paths.yaml").write_text("\n".join(yaml))
        cmd = [str(PY), "-I", "-X", "utf8", "-W", "ignore::FutureWarning", "ComfyUI\\main.py", "--windows-standalone-build", "--listen", "127.0.0.1", "--port", str(self.port),
               "--disable-auto-launch", "--output-directory", str(self.work / "out"), "--temp-directory", str(self.work / "tmp"), "--input-directory", str(self.work / "in"),
               "--extra-model-paths-config", str(self.work / "extra_model_paths.yaml")]
        if not self.custom_nodes:
            cmd.append("--disable-all-custom-nodes")
        self.proc = subprocess.Popen(cmd, cwd=str(COMFY), stdout=open(self.work / "server.log", "wb"), stderr=subprocess.STDOUT, creationflags=0x08000000 | 0x4000)
        t0 = time.time()
        while time.time() - t0 < self.timeout:
            if self.proc.poll() is not None:
                raise RuntimeError("ComfyUI exited, see %s" % (self.work / "server.log"))
            try:
                urllib.request.urlopen(self._u("/system_stats"), timeout=2).read()
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("ComfyUI start timeout")
        print("ComfyUI up on port %d after %.0f s" % (self.port, time.time() - t0), flush=True)
        return self

    def __exit__(self, *a):
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)

    def _u(self, p):
        return "http://127.0.0.1:%d%s" % (self.port, p)

    def put(self, path):
        name = Path(path).name
        shutil.copy(path, self.work / "in" / name)
        return name

    def run(self, wf, timeout=1200):
        req = urllib.request.Request(self._u("/prompt"), json.dumps({"prompt": wf, "client_id": uuid.uuid4().hex}).encode(), {"Content-Type": "application/json"})
        try:
            pid = json.loads(urllib.request.urlopen(req).read())["prompt_id"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode()[:1500])
        t0 = time.time()
        while time.time() - t0 < timeout:
            h = json.loads(urllib.request.urlopen(self._u("/history/" + pid)).read())
            if pid in h:
                st = h[pid]["status"]
                if st.get("status_str") == "error":
                    raise RuntimeError(json.dumps(st)[:1500])
                outs = []
                for node in h[pid]["outputs"].values():
                    for key in ("images", "audio"):
                        for it in node.get(key, []):
                            q = urllib.parse.urlencode({"filename": it["filename"], "subfolder": it.get("subfolder", ""), "type": it.get("type", "output")})
                            outs.append(urllib.request.urlopen(self._u("/view?" + q)).read())
                return outs
            time.sleep(0.5)
        raise RuntimeError("workflow timeout")
