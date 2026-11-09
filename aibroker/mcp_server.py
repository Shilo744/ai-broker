"""AI Broker MCP server (stdio). Lets Claude Code start and manage heavy local AI/GPU jobs through the broker instead of running them directly.
Run:  .venv\\Scripts\\python.exe -m aibroker.mcp_server      (register with register.bat / `claude mcp add`, see README)"""
import os
import time
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from . import client

INSTRUCTIONS = """AI Broker is the ONE entry point for heavy local AI/GPU work on this computer (image models such as Qwen/Z-Image through ComfyUI,
TripoSG/Step1X 3D shapes, Blender cleaning and baking, music/sound models, hidden Godot test runs). NEVER start such a job directly in a shell:
queue it with submit_job. The broker fits as many jobs at once as the RAM/VRAM limits allow, learns real memory use from history, groups jobs
that use the same model, and pauses everything when the owner is playing or recording.
Every job gets its OWN output folder (<output_root>/<model type>/<date>_<name>/): you normally do not pass any output path; job_status returns `outdir` and `output_files`.
Workflow: list_job_types (first time) -> submit_job -> keep working on something else -> wait_for_job (short timeout, repeat) or run
`aijob wait <id>` as a BACKGROUND shell command to be woken when it ends -> read the result with job_status / job_output.
Small light commands (a quick script, a git command) do NOT belong here. Do not change limits or pause the queue unless the owner asked."""

mcp = MCPServer("ai-broker", instructions=INSTRUCTIONS)
REQUESTER = os.environ.get("AIJOB_REQUESTER", "claude")


def _call(req, start=False, timeout=15.0):
    try:
        r = client.call(req, timeout=timeout, start=start)
    except client.BrokerDown as e:
        return {"ok": False, "error": str(e), "hint": "The broker service is not running. Any submit_job starts it automatically."}
    return r


def _brief(j: dict) -> dict:
    keys = ("id", "state", "name", "type", "requester", "est_ram", "est_vram", "est_source", "reason", "elapsed", "cur_ws", "cur_vram", "rc", "peak_ws", "peak_commit",
            "peak_vram", "note", "outdir")
    out = {k: j[k] for k in keys if k in j and j[k] not in (None, "")}
    if j.get("finished") and j.get("started"):
        out["seconds"] = round(j["finished"] - j["started"], 1)
    return out


@mcp.tool()
def list_job_types() -> dict:
    """List the kinds of jobs the broker can run: id, title, class (gpu/cpu), default memory estimate, and the parameters each one takes
    (with defaults; 'required' ones must be given). Call this once before your first submit_job in a session."""
    r = _call({"op": "types"}, start=True)
    if not r.get("ok"):
        return r
    out = {}
    for tid, t in r["types"].items():
        params = {}
        for k, v in (t.get("params") or {}).items():
            params[k] = {"default": v.get("default"), "required": bool(v.get("required")), "help": v.get("help", "")} if isinstance(v, dict) else {"default": v}
        out[tid] = {"title": t.get("title"), "class": t.get("klass", "cpu"), "est_ram_gb": (t.get("est") or {}).get("ram_gb"), "est_vram_gb": (t.get("est") or {}).get("vram_gb"),
                    "notes": t.get("notes", ""), "params": params}
    return {"ok": True, "types": out, "tip": "type 'custom' runs any command (pass command=[...]) and needs your own memory estimates"}


@mcp.tool()
def submit_job(
    job_type: Annotated[str, Field(description="A type id from list_job_types, e.g. 'triposg_shape', 'qwen_image_edit', 'blender_script', or 'custom' for any command.")],
    params: Annotated[dict[str, Any] | None, Field(description="Parameters of that type (see list_job_types). Input paths must be absolute. Output paths are optional: by default results go to the job's own output folder (returned as outdir). Lists are JSON lists.")] = None,
    name: Annotated[str | None, Field(description="Short human name shown to the owner in the queue, e.g. 'coat shape depth 9'.")] = None,
    requester: Annotated[str | None, Field(description="Who is asking (your agent/session name), shown to the owner.")] = None,
    est_ram_gb: Annotated[float | None, Field(description="Only if you KNOW the peak RAM in GB (otherwise leave empty: the broker uses measured history). REQUIRED for 'custom'.")] = None,
    est_vram_gb: Annotated[float | None, Field(description="Only if you know the peak GPU memory in GB. 0 for CPU-only.")] = None,
    command: Annotated[list[str] | None, Field(description="For job_type='custom' only: the command and its arguments as a list, e.g. ['python','C:/x/run.py','--n','3'].")] = None,
    run_next: Annotated[bool, Field(description="Put it at the top of the queue. Use only when the owner asked for urgency.")] = False,
    after_job_id: Annotated[int | None, Field(description="Start only after this job finished successfully (a chain). It is cancelled if that job fails.")] = None,
    timeout_s: Annotated[int | None, Field(description="Kill the job if it runs longer than this many seconds.")] = None,
    model: Annotated[str | None, Field(description="Affinity key. Jobs with the same model run back to back to avoid reloading. Normally leave empty (the type sets it).")] = None,
) -> dict:
    """Queue ONE heavy local AI/GPU job. Returns immediately with job_id; the job starts when it fits in the RAM/VRAM limits (it may wait; see job_status 'reason').
    After submitting, do other work, then use wait_for_job or the CLI `aijob wait <id>` in the background. Never run the same heavy work directly instead."""
    est = {k: v for k, v in (("ram_gb", est_ram_gb), ("vram_gb", est_vram_gb)) if v is not None}
    req = dict(op="submit", type=job_type, params=params or {}, name=name, requester=requester or REQUESTER, est=est or None, cmd=command, next=run_next,
               after=after_job_id, timeout_s=timeout_s, model=model)
    r = _call(req, start=True)
    if not r.get("ok"):
        return r
    g = _call({"op": "get", "id": r["id"]})
    return {"ok": True, "job_id": r["id"], "job": _brief(g["job"]) if g.get("ok") else {}, "next_step": "wait_for_job(job_id) or run `aijob wait %d` in the background" % r["id"]}


@mcp.tool()
def queue_status() -> dict:
    """Overview: broker status (ACTIVE / PAUSED / PLAYING / BRAKE), RAM/VRAM/disk numbers, the soft limits, running jobs and waiting jobs in order
    (each waiting job says why it waits)."""
    s = _call({"op": "state"})
    if not s.get("ok"):
        return s
    sy = s["sys"]
    return {"ok": True, "status": s["status"], "brake": s["brake"], "paused": s["paused"], "playing": s["playing"],
            "ram_free_gb": round(sy["ram_avail"], 1), "ram_total_gb": round(sy["ram_total"], 1), "commit_free_gb": round(sy["commit_avail"], 1),
            "vram_used_gb": round(sy["gpu_used"], 1), "vram_total_gb": round(sy["gpu_total"], 1), "disk_busy_pct": round(sy["disk"]),
            "ai_budget_used": {k: round(v, 1) for k, v in s["budget"].items()}, "limits": s["limits"],
            "running": [_brief(j) for j in s["running"]], "queued": [_brief(j) for j in s["queued"]]}


@mcp.tool()
def job_status(job_id: Annotated[int, Field(description="Job id returned by submit_job.")],
               output_tail_chars: Annotated[int, Field(description="Also return the last N characters of the job's output (0 = none).", ge=0, le=20000)] = 0) -> dict:
    """State of one job: queued / running / paused / done / failed / cancelled / lost. When finished: exit code (rc), seconds, peak RAM, peak commit, peak VRAM.
    'reason' explains why a queued job is still waiting."""
    r = _call({"op": "get", "id": job_id})
    if not r.get("ok"):
        return r
    out = {"ok": True, "job": _brief(r["job"])}
    d = r["job"].get("outdir")
    if d and os.path.isdir(d) and r["job"]["state"] in ("done", "failed"):
        files = []
        for root, _dirs, names in os.walk(d):
            _dirs[:] = [x for x in _dirs if x != "preview"]
            for n in names:
                if n not in ("job.log", "result.json"):
                    fp = os.path.join(root, n)
                    files.append({"path": fp.replace("\\", "/"), "mb": round(os.path.getsize(fp) / 1e6, 2)})
        out["output_files"] = files[:40]
    if output_tail_chars:
        out["output_tail"] = (_call({"op": "tail", "id": job_id, "bytes": output_tail_chars}) or {}).get("text", "")
    return out


@mcp.tool()
def job_output(job_id: int, last_chars: Annotated[int, Field(description="How many trailing characters of the log to return.", ge=100, le=100000)] = 6000) -> dict:
    """The tail of a job's combined stdout/stderr log (works while it runs and after it ended)."""
    r = _call({"op": "tail", "id": job_id, "bytes": last_chars})
    return r if not r.get("ok") else {"ok": True, "job_id": job_id, "text": r["text"]}


@mcp.tool()
def wait_for_job(
    job_id: Annotated[int, Field(description="Job id to wait for.")],
    timeout_s: Annotated[int, Field(description="Maximum seconds to block (1-1500). If the job is still going, returns finished=false: call again or do other work.", ge=1, le=1500)] = 300,
) -> dict:
    """Block until the job ends or timeout_s passes. Returns finished=true with the final state and measurements, or finished=false with the current state.
    For long jobs prefer starting `aijob wait <id>` as a BACKGROUND shell command so you are woken when it ends, and keep working meanwhile."""
    t0 = time.time()
    while True:
        r = _call({"op": "get", "id": job_id})
        if not r.get("ok"):
            return r
        j = r["job"]
        if j["state"] in ("done", "failed", "cancelled", "lost"):
            return {"ok": True, "finished": True, "success": j["state"] == "done", "job": _brief(j)}
        if time.time() - t0 >= timeout_s:
            return {"ok": True, "finished": False, "job": _brief(j), "note": "still not finished after %d s" % timeout_s}
        time.sleep(2.0)


@mcp.tool()
def move_job(job_id: int, to: Annotated[str, Field(description="'top' (run next), 'up', 'down', 'bottom', or a 1-based queue position like '3'.")]) -> dict:
    """Change the position of a WAITING job in the queue. The owner's manual order is respected; only do this when asked or when your own urgent job must go first."""
    return _call({"op": "move", "ids": [job_id], "to": to if to in ("top", "bottom", "up", "down") else int(to)})


@mcp.tool()
def rerun_job(job_id: Annotated[int, Field(description="A finished (or any earlier) job id to repeat.")],
              requester: Annotated[str | None, Field(description="Your agent name, shown in the queue.")] = None) -> dict:
    """Queue the SAME job again (same type, parameters and name) with a fresh output folder. Use it to repeat a past job instead of rebuilding its parameters."""
    r = _call({"op": "rerun", "id": job_id, "requester": requester or REQUESTER}, start=True)
    return r if not r.get("ok") else {"ok": True, "job_id": r["id"], "next_step": "wait_for_job(job_id)"}


@mcp.tool()
def cancel_job(job_id: int) -> dict:
    """Cancel a waiting job, or kill a running one (its process tree is terminated). Only cancel your own jobs."""
    return _call({"op": "cancel", "id": job_id})


@mcp.tool()
def hold_job(job_id: int) -> dict:
    """Pause one job: a waiting job is held (will not start), a running job is suspended (frozen, memory stays used)."""
    return _call({"op": "job_pause", "id": job_id})


@mcp.tool()
def release_job(job_id: int) -> dict:
    """Undo hold_job: let a held job start, or resume a suspended one."""
    return _call({"op": "job_resume", "id": job_id})


@mcp.tool()
def pause_queue(suspend_running: Annotated[bool, Field(description="Also freeze the jobs that are running now.")] = False) -> dict:
    """Stop starting new jobs (owner request only, e.g. 'pause the AI'). resume_queue undoes it."""
    return _call({"op": "pause", "suspend": suspend_running})


@mcp.tool()
def resume_queue() -> dict:
    """Start jobs again after pause_queue."""
    return _call({"op": "resume"})


@mcp.tool()
def set_playing_mode(on: bool) -> dict:
    """The owner is playing a game or recording: GPU jobs wait and running GPU jobs are frozen until turned off. Only change it when the owner says so."""
    return _call({"op": "playing", "on": on})


@mcp.tool()
def get_limits() -> dict:
    """The soft limits: ram_gb / vram_gb (budget for all running jobs together), max_jobs, reserve_ram_gb (must stay free), min_commit_free_gb, and the safety-brake thresholds."""
    r = _call({"op": "limits"})
    return r if not r.get("ok") else {"ok": True, "limits": r["limits"]}


@mcp.tool()
def set_limits(
    ram_gb: Annotated[float | None, Field(description="Budget in GB for the sum of running jobs' RAM.")] = None,
    vram_gb: Annotated[float | None, Field(description="Budget in GB of GPU memory for jobs (the card has 16).")] = None,
    max_jobs: int | None = None,
    reserve_ram_gb: Annotated[float | None, Field(description="RAM that must stay free for the rest of the computer.")] = None,
) -> dict:
    """Change the soft limits at runtime. Only when the owner asks; the defaults were chosen for this 64 GB / 16 GB machine."""
    s = {k: v for k, v in (("ram_gb", ram_gb), ("vram_gb", vram_gb), ("max_jobs", max_jobs), ("reserve_ram_gb", reserve_ram_gb)) if v is not None}
    r = _call({"op": "limits", "set": s})
    return r if not r.get("ok") else {"ok": True, "limits": r["limits"]}


@mcp.tool()
def resources() -> dict:
    """Live computer numbers: free RAM, free commit, GPU memory used/total, GPU load, CPU %, disk busy %, and whether another program holds the shared GPU lock."""
    s = _call({"op": "state"})
    if not s.get("ok"):
        return s
    sy = s["sys"]
    return {"ok": True, "ram_free_gb": round(sy["ram_avail"], 1), "ram_total_gb": round(sy["ram_total"], 1), "commit_free_gb": round(sy["commit_avail"], 1),
            "gpu_used_gb": round(sy["gpu_used"], 1), "gpu_total_gb": round(sy["gpu_total"], 1), "gpu_util_pct": round(sy["gpu_util"]), "cpu_pct": round(sy["cpu"]),
            "disk_busy_pct": round(sy["disk"]), "gpu_lock": s["lock"], "gpu_lock_holder": s["lock_holder"], "status": s["status"]}


@mcp.tool()
def job_history(limit: Annotated[int, Field(ge=1, le=100)] = 15) -> dict:
    """Recently finished jobs with duration and measured peak RAM / commit / VRAM (use these numbers to plan batch sizes)."""
    r = _call({"op": "history", "limit": limit})
    return r if not r.get("ok") else {"ok": True, "jobs": [_brief(j) for j in r["jobs"]]}


@mcp.tool()
def hardware_profile() -> dict:
    """What this computer can do: graphics card name and VRAM, RAM, free space on every drive, installed tools (Blender, ComfyUI, Python, git, ffmpeg) and the broker's
    limits. Use this to judge which models fit. NEVER run a shell command (Get-PSDrive, nvidia-smi ...) to look at the machine: this tool needs no approval."""
    return _call({"op": "hardware"}, timeout=20)


@mcp.tool()
def list_model_packs(categories: list[str] | None = None) -> dict:
    """The model packs this program can run (categories: image, 3d, audio, game), for THIS computer: fit (ok / tight / no), installed or not, the download size still needed,
    licence, source page and which job types it enables. Use it before recommending or installing models; it needs no approval."""
    return _call({"op": "packs", "categories": categories}, timeout=30)


@mcp.tool()
def install_model_pack(pack_ids: list[str]) -> dict:
    """Queue the downloads of the given packs (ids from list_model_packs) as `download` jobs. Files come only from the verified official sources of the catalog and are kept only
    when their size and SHA-256 match. Packs that cannot be downloaded automatically are returned in `manual`. The owner approves according to his permission level."""
    return _call({"op": "install_packs", "ids": pack_ids, "requester": REQUESTER}, timeout=60)


# The permission handler exists only for the assistant inside the AI Broker window (the window starts it with AIBROKER_ASSISTANT=1); other agents never see it.
if os.environ.get("AIBROKER_ASSISTANT") == "1":
    import json

    @mcp.tool(structured_output=False)
    def approve(tool_name: str, input: dict, tool_use_id: str = "") -> str:
        """INTERNAL: Claude Code asks here whether a tool call may run. The broker applies the owner's permission level and, when needed, shows a question in the window and
        waits for the owner's click. Not for agents to call."""
        r = _call({"op": "perm_ask", "tool": tool_name, "input": input}, timeout=10)
        if not r.get("ok"):
            return json.dumps({"behavior": "deny", "message": "The broker service cannot be reached, so nothing can be approved right now."})
        pid, state, msg = r["id"], r["state"], r.get("message", "")
        t0 = time.time()
        while state == "pending" and time.time() - t0 < 900:           # the owner has up to 15 minutes to answer
            time.sleep(0.6)
            g = _call({"op": "perm_get", "id": pid}, timeout=10)
            if not g.get("ok"):
                break
            state, msg = g["state"], g.get("message", "")
        if state == "allow":
            return json.dumps({"behavior": "allow", "updatedInput": input})
        return json.dumps({"behavior": "deny", "message": msg or "The owner did not approve this action. Continue without it, or suggest an alternative."})


def main():
    mcp.run("stdio")


if __name__ == "__main__":
    main()
