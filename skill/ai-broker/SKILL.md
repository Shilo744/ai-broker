---
name: ai-broker
description: Use for ANY heavy local AI/GPU job on this computer: image generation or editing (ComfyUI Qwen / Z-Image), 3D shape models (TripoSG, Step1X-3D), Blender cleaning or baking of big meshes, music or sound models, and hidden Godot test runs. Submit them to the AI Broker queue instead of running them directly. Do not use for quick light commands.
---

# AI Broker: how an agent runs heavy local AI jobs

The owner's laptop (64 GB RAM, 16 GB GPU, shared by several agents, the game and screen recording) froze on 2026-11-09 when many model jobs ran at once. **The AI Broker is now the only way to start heavy AI jobs.** It runs as a background service with a window the owner watches; it fits as many jobs at once as the RAM/VRAM limits allow, learns real memory use, groups jobs that use the same model, and waits while the owner is playing or recording.

## When to use it
Submit to the broker when the work is any of: ComfyUI / Qwen-Image-Edit / Z-Image, TripoSG or Step1X-3D shapes, Blender on large meshes (bake, clean, decimate millions of faces), ACE-Step music, MOSS sound, Godot `shots`/`film` runs, or any script that loads a model on the GPU or needs more than about 3 GB RAM.
The owner also submits jobs by hand in the window ("New job" / drag a file); those jobs show up in the same queue with requester `owner`. Do NOT use it for: git, file edits, short Python/PowerShell, small Blender operations on tiny files.
**Never start those heavy jobs directly in a shell** (no `python run_job.py`, no direct ComfyUI, no `blender -b` on big meshes) and never kill another session's process.

## The tools (MCP server `ai-broker`)
| Tool | Use |
|---|---|
| `list_job_types` | First time per session: the job types, their parameters and default memory estimates |
| `submit_job` | Queue one job. Returns `job_id` at once |
| `queue_status` / `resources` | What runs, what waits and why, free RAM, GPU memory |
| `job_status` / `job_output` / `job_history` | State, exit code, measured peaks, log tail |
| `wait_for_job` | Block up to `timeout_s` (max 1500). Call again if `finished` is false |
| `rerun_job` | Repeat a past job (same parameters, new output folder) |
| `move_job`, `hold_job`, `release_job`, `cancel_job` | Queue control (your own jobs only) |
| `pause_queue`, `resume_queue`, `set_playing_mode`, `get_limits`, `set_limits` | **Owner's controls: use only when the owner asked** |

CLI equivalent (when MCP is not available): `aijob submit <type> key=value ...`, `aijob status`, `aijob wait <id>`, `aijob types -v`.

## How to submit well
1. Pick a type from `list_job_types`. If none fits, use `custom` with `command=[...]` and give **est_ram_gb / est_vram_gb yourself** (measure or take it from `job_history`; say a bit more, not less).
2. For the known types do **not** pass estimates: the broker uses the last measured runs (shown as "learned from N runs" in the queue). Pass them only if you know this input is unusually big (for example a 4-million-face mesh in Blender: about 15 GB).
3. **Do not pass an output path.** Every job gets its own folder `output/<model type>/<date>_<name>/` (created by the broker; also available to the job as env `AIBROKER_OUTDIR` and as `{outdir}` in parameters). `job_status` returns `outdir` and `output_files`. The owner browses these folders in the window. Give a short human `name` (ASCII letters in the name become the folder name) and your agent name as `requester`. Use absolute paths.
4. Many items of the same kind? Prefer ONE batch job (the Qwen runner takes `batch=jobs.json`; the lab's shape scripts take a jobs.json) so the model loads once, rather than 20 separate jobs. Otherwise submit them all: jobs of the same model are grouped automatically.
5. Chains: `after_job_id=<id>` starts a job only after the first one succeeded (it is cancelled if that one fails).
6. Do not use `run_next` unless the owner told you something is urgent. The owner may move jobs by hand; do not fight that.

## How you get notified (a tool cannot message you, so one of these)
- **Short wait:** `wait_for_job(job_id, timeout_s=300)`; repeat while `finished` is false.
- **Long job (recommended):** start `aijob wait <id> [<id> ...]` as a **background** shell command (`run_in_background`). It exits when the job ends and prints one line (state, exit code, seconds, peak RAM); that wakes you. Keep working on something else meanwhile. Exit code 0 ok, 1 failed, 2 cancelled, 3 timeout.
- Then `job_status` / `job_output` to read the result and the files the job wrote.

## Reading the result
`state` done with `rc` 0 means the process succeeded; check that the expected output files exist. `failed`: read `job_output` (last lines), fix, resubmit. `lost` means the broker restarted while it ran (exit code unknown): check the output files. A queued job's `reason` says why it waits (RAM/VRAM budget, owner is playing, paused, another job of the same type). Waiting is normal; do not resubmit.

## Rules of the house
- The queue, limits, pause and "I am playing / recording" are the owner's. Only the owner changes limits or pauses everything.
- One job at a time per type is normal for the big models (TripoSG, Qwen); different kinds run side by side when they fit.
- Report job numbers and measured peak RAM/VRAM in your notes so the owner can see what a job really costs.
