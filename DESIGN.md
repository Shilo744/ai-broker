# AI Broker - design (one page)

**What:** one background service (the *broker*) that every agent uses to start local AI/GPU jobs (ComfyUI Qwen/Z-Image, TripoSG, Step1X-3D, Blender, ACE-Step/MOSS, hidden Godot runs), plus a desktop GUI and a CLI that are only *clients*. Closing the window or the terminal never stops the queue.

**Why:** 2026-11-09, 22 TripoSG shapes + Step1X + Qwen + Blender at once -> commit 109 GB, RAM 100 %, SSD 100 %, PC stuttering. The fix is not "one job at a time" but "as many as fit".

## Limits (soft, editable while running)
`config.json` (also GUI sliders and `aijob limits`): `ram_gb` (budget for the sum of running jobs, default 46 of 64), `vram_gb` (default 14 of 16), `max_jobs` (4), `reserve_ram_gb` (6, must stay free after a start), `min_commit_free_gb` (20). Safety brake: free RAM < `hard_free_ram_gb` (2.5) or free commit < 8 GB => no starts, and the youngest running job is *suspended* (not killed) until memory recovers.

## Job spec
A job = `type` + params + requester. Types live in `jobtypes/*.json` (title, group, class gpu/cpu, `model` key for affinity, `est` {ram, vram, commit}, `max_parallel`, `params` with defaults, `cmd` template, env). `aijob submit <type> k=v ...` resolves the command at submit time and stores it. `custom` type = any command after `--` with explicit estimates. Estimates: spec override > **learned** (90th percentile of the last 10 successful runs of the same `est_key`, x1.1, from History) > type default (flagged "default" in the queue until measured).

## Scheduling rule (every second)
Walk the queue in order. Start a job when ALL hold: not paused / not "playing" (GPU jobs) / dependency done; sum(running RAM) + job <= `ram_gb` (running = max(estimate, live working set)); same for VRAM (+ whatever other programs, e.g. the game, already use: measured, not guessed); running < `max_jobs`; type `max_parallel`; free RAM and commit after the job's still-unloaded part >= reserve; no foreign GPU lock. Jobs that do not fit are skipped (backfill: a small Blender run slips past a waiting Qwen) unless the head of the queue has waited 15 min - then nothing overtakes it.
**Affinity:** jobs whose `model` is already loaded (running, or finished < 3 min ago) are lifted ahead of other-model jobs inside the first 8 queue slots, never past a job the owner moved by hand (those are "pinned"). Real model reuse needs batch jobs (one process, many items): the Qwen and TripoSG runners accept a list.
**Legacy lock:** the broker holds `.../3D maker/characters/.gpu.lock` while any GPU job runs (so char_forge / old scripts wait) and does not start GPU jobs while a foreign holder has it. Godot visual runs take the lock themselves (`self_lock`).

## Claude integration (first-class)
**MCP server** (`aibroker/mcp_server.py`, stdio, Python `mcp` SDK, MIT): `list_job_types`, `submit_job`, `queue_status`, `job_status`, `job_output`, `job_history`, `wait_for_job` (blocking, max 1500 s, repeatable), `move_job`, `hold_job`, `release_job`, `cancel_job`, `resources`, `get_limits`, and the owner-only `pause_queue`, `resume_queue`, `set_playing_mode`, `set_limits`. Every tool and parameter is documented in its schema and the server sends usage instructions, so Claude needs no prior knowledge (tested with a fresh `claude -p`). **Skill** `skill/ai-broker/SKILL.md`: when to submit, how to give estimates, never start heavy jobs directly, how to be notified (`aijob wait` in the background). `register.bat` / `unregister.bat` / `mcp.json` prepare the registration; nothing edits the owner's Claude settings or any CLAUDE.md by itself.

## Independence
Own folder and repo; no imports from the games. Project-specific job types and paths live in `adapters/<name>/` (jobtypes + vars), generic ones in `jobtypes/`.

## Output folders and the two ways in
Every job gets `output/<model type>/<date>_<name>/` (ASCII slug), created by the broker, also exported as `{outdir}` / `AIBROKER_OUTDIR`; the broker writes `result.json` (job id, seconds, peaks, command) and `job.log` there. The window's main area is Models (per-type output browser with thumbnails, open folder, re-run) + Queue/History + Resources. The owner submits with a minimal dialog (type, input file or drop, name; advanced folded) and re-runs from History or from a file's menu; Claude uses MCP/CLI (`submit_job`, `rerun_job`). Both create the same job in the same queue.

## Built-in assistant (Claude inside the window)
First entry of the model list: a normal chat with Claude. Each message runs Claude Code **headless and hidden** (`claude -p --output-format stream-json --resume`, no terminal anywhere) with the broker's MCP tools and `skill/ai-broker/AGENT_PROMPT.md` (session-only flags, no settings edited). It can read the queue, resources, history and outputs, run jobs, search the web and keep `docs/MODELS.md` / `DOWNLOADS.md`. Anything else (pause the queue, run a shell command such as a download) is denied by Claude Code, comes back as `permission_denials`, and the window asks Approve / Decline in the chat; an approved action is allowed for the next turn only (the exact command). Model: Haiku by default, Sonnet or the account default selectable. Uses the owner's Claude plan quota.

## Look and feel
IDE-style dark theme (`aibroker/theme.py`: neutral greys, one blue accent, 4-6 px radii, own thin line icons drawn from an SVG set, 10.5 pt text with Ctrl +/- zoom) and a small design kit (`aibroker/kit.py`: tool-window headers, gauges with a two-minute history graph, status chips, toasts, the model-list painter with running/waiting/result pills, the status-bar background-task indicator, a wrapping layout and the Ctrl+K command palette). Logo: a rounded hexagon holding a geometric B with an orange middle bar (`assets/`). UX: messages with who/when headers, failure reasons shown in the answer, "send to another model", paste/drop/recall, persisted layout, service-down recovery button.

## Control
Owner: drag rows / right-click run next, up, down, pause, cancel; Pause all (queue only, or also suspend running); big **I am playing / recording** toggle (no GPU starts, running GPU jobs suspended, resumes on off). `PAUSE_AI.bat` / `RESUME_AI.bat` / `PLAYING_ON.bat` / `PLAYING_OFF.bat`.

## Notification
An external process cannot message a Claude session. The requester runs `aijob wait <id> [<id>...]` as a **background command**; it polls the broker, prints one summary line (state, exit code, seconds, peak RAM) and exits (0 ok, 1 failed, 2 cancelled, 3 timeout), which wakes the agent. Optional Windows toast (`"toast": true`) and a tray balloon from the GUI.

## Logging
Per job: start/end, seconds, peak working set (polled process tree), peak commit (Windows Job Object `PeakJobMemoryUsed`), peak VRAM (PDH GPU Process Memory counter), free RAM at start. SQLite in `%LOCALAPPDATA%\ai-broker`; job output in `logs\<id>.log`.

## GUI stack
Two views in the same app: the default dark "professional" dock layout (Job Library / Queue / Resources / Log-Output-History, bigger text, an icon per model type, grouped) and a SIMPLE Hebrew card view (big pictures, plain sentences), switchable from the menu. Python 3.12 + **PySide6 (Qt 6, LGPL-3, used unmodified as a pip dependency, internal tool, never redistributed)** + psutil (BSD). Why: real native dockable tool windows (QDockWidget), tray, tables with drag-drop, theming with one stylesheet, runs next to the Python job code the lab already uses; no Electron/web page. Dark IDE look (Darcula-like).

## It will NOT
Run on a network (localhost only, no auth: any process of this user can submit); kill processes it did not start; manage the game's or the owner's own programs; schedule time-of-day jobs; start itself at login (owner decides); change CLAUDE.md or any agent rules; resume a job after a *broker* crash (running jobs survive, but their exit code is then unknown -> state `lost`); give true VRAM isolation (it plans from estimates and measurements, the driver can still page).
