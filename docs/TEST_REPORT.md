# Test report (2026-11-09, build session)

## Three real jobs through the broker (all submitted with `aijob submit`, no manual starts)
| # | Job | Result | Seconds | Peak RAM (working set) | Peak commit | Peak VRAM |
|---|---|---|---|---|---|---|
| 7 | TripoSG shape, fur reference, depth 8 | exit 0, 560,258 faces GLB | 93 | 6.4 GB | 15.4 GB | 6.0 GB |
| 8 | Blender: import 143,124-face mesh, decimate 0.5, export GLB | exit 0, 71,562 faces | 2 | 0.3 GB | 0.4 GB | 0 |
| 9 | Qwen-Image-Edit (Nunchaku fp4): "change the black coat to dark red" | exit 0, picture `shots/real/qwen_red_coat.png` (coat is red, rest identical) | 59 | 33.4 GB | 28.2 GB | 8.7 GB |

Numbers match what the lab measured on the same day (TripoSG 6.8 / 15.9 / 5.7-6.9; ComfyUI Qwen 35 GB). They are now in History and the queue estimate for the same type is "learned from N runs".

## Packing and waiting (log: `docs/test_log_excerpt.txt`)
- 19:05:56 the three jobs were submitted together. 19:05:57 TripoSG and Blender started side by side (2 running); Blender finished in 2 s.
- Qwen (est 36 GB RAM, 9 GB VRAM) waited because TripoSG used VRAM and, afterwards, because **another program's process (the lab's, outside the broker, 6.4 GB VRAM)** held GPU memory: the queue said "VRAM budget: ... used by other programs". When that process ended and the free RAM test passed (free 42 GB, reserve lowered from 6 to 5 GB by me for the test) Qwen started at 19:08:07 and finished at 19:09:06. Screenshot of the waiting state: `shots/real/gui_waiting.png`.
- Packing demo with sleep jobs (est 20, 20, 20, 4 GB): A and D ran, B and C waited with "free RAM would drop below 5 GB" (shot `shots/real/gui_packing.png`).
- The background `aijob wait 7 9` printed both results and exited 0; it survived a broker restart in between ("broker unreachable", then recovered). That woke this session.

## MCP from a real Claude Code
`claude -p ... --mcp-config mcp.json --strict-mcp-config` (a fresh Claude session with no instructions except the MCP tool descriptions) listed the queue, submitted job #10 with `submit_job`, waited with `wait_for_job` and reported state done, exit 0, output "pong". Also `tests/test_mcp.py` (stdio client).

## Other checks
Scheduler rules: 12 unit tests (`tests/test_scheduler.py`) pass: packing, backfill, VRAM counting other programs, max_parallel, paused/playing, brake, reserve, affinity, manual pins, starvation guard, GPU lock. `PAUSE_AI.bat`, `RESUME_AI.bat`, `PLAYING_ON.bat`, `PLAYING_OFF.bat` and `aijob.bat` were run: status changed ACTIVE -> PAUSED -> PLAYING -> ACTIVE.

## NOT verified
- Dragging rows with the mouse, the context menu, the New-job dialog (clicked by hand), the tray icon, Windows toast. (GUI was only screenshotted and viewed.)
- Safety brake in practice (logic unit-tested, memory was never really pushed), emergency suspend, suspend/resume of a running GPU job by "I am playing" (it ran briefly during a .bat test with Qwen running; no failure seen, not examined).
- Step1X, ACE-Step, MOSS, Z-Image, Godot job types (commands resolve, never run; their RAM/VRAM numbers are the lab's or guesses until measured).
- Holding and releasing the shared `.gpu.lock` while a GPU job ran (code exists, not inspected during the run).
- Recovery after a broker crash (state `lost`).
- `register.bat` was not run (owner's decision; it edits the owner's Claude config).
- The simple Hebrew view: screenshotted only; the owner preferred the dark view as default.
