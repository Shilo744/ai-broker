# AI Broker: progress tracker

Kept up to date while working (what is done, what is open, what is NOT verified). `[x]` done and checked, `[~]` in progress, `[ ]` open.

## Owner requests

| # | Request (owner, 2026-11-09) | Status |
|---|---|---|
| 1 | One window, queue, resources, per-model output folders, chat per model, Claude built in (no terminal) | [x] |
| 2 | Professional dark IDE-like look, explanation on every model page | [x] model pages without an interface route requests to Claude |
| 3 | Keep the current logo | [x] decided, nothing to do |
| 4 | Hebrew text in chat was "crooked" when a paragraph starts with an English name (learn from Terminal Grid) | [x] `rtltext.py` + `MessageView`: direction per paragraph by majority script; checked in screenshots against the owner's example |
| 5 | Claude's messages start from the right | [x] `aligned_start()`; checked in the window |
| 6 | Approval cards say in plain language what the action does | [x] `permissions.py` + card UI; real-Claude test `tests/e2e_approval.py` 8/8 |
| 7 | Owner chooses the permission level (careful / normal / free) | [x] header button + dialog; daemon applies it; checked with real Claude |
| 8 | Notices must not pop up over the content | [x] `NoticeBar` docked under the content; Windows balloons only when the window is hidden |
| 9 | Space planning (side panels and the empty queue take too much room) | [x] resource strip replaces the left column, narrow model list, queue collapses when empty; middle is about 82 percent of the width (live screenshot at the owner's window size) |
| 10 | Settings (gear icon) instead of "Advanced", with a language choice | [x] `SettingsDialog` (General / Behavior / Claude / Log) |
| 11 | English as a UI language | [x] 429 texts, LTR layout, job types in two languages; `tests/test_i18n.py`; checked in screenshots. The in-window Claude answers in the chosen language (not run end to end in English) |
| 12 | GitHub documentation in English | [x] README.md (English), README.he.md, DESIGN.md updated, requirements.txt, screenshots. **Not pushed**: waiting for the owner's yes |
| 13 | First-run setup wizard: pick model kinds, hardware check, recommended models, download, finish; connect Claude Code | [x] v1: wizard (3 pages), catalog of 8 packs (ACE-Step and Qwen-Image-Edit downloadable with verified checksums, the rest detected or handed to Claude), download job type with resume and checksum, MCP tools; tests pass. Not in v1: LLM, installing ComfyUI / Python environments, other people's job types |
| 14 | A file that tracks what is done | [x] this file |
| 15 | "Why does it wait for the GPU when 10 GB are free?" (job #48, 22:53) | [x] answered: the estimate was 13.6 GB (one earlier 12.4 GB peak + 10%) and only 10.0 GB were free (6.0 GB held by other programs); even the typical 10.45 GB peak did not fit by 0.45 GB. Fixed: the waiting text shows the numbers and the biggest GPU users, "Run anyway" button / menu / `aijob force`, VRAM estimate no longer decided by one outlier; scheduler tests 16, `tests/e2e_force.py` 7/7 |

## Done (checked)
- Tests never touch the owner's data (`tests/sandbox.py`).
- Permission classifier: 68 unit checks. Translation table: `tools/i18n_tool.py check` and `tests/test_i18n.py`. Scheduler: 13 tests. UI smoke test: 15 checks.
- Real Claude (`claude -p --permission-prompt-tool`) answered or held a permission request inside the same turn: approve writes the file, decline does not, a read-only command at level "normal" runs silently, at level "careful" it asks.

## Not verified yet (say so to the owner)
- The owner's window and service were restarted with the latest code at the end of the session (setup wizard, cog icon, clickable permission cards). Everything after that is only in the repository.
- A real Claude turn in English through the window; a real login autostart; macOS / Linux (Windows only).
- The wizard has run end to end only against a local fake server and in the sandbox; no real model was downloaded from the internet by the setup (the three installed packs on the author's computer were detected as installed). The first real download will be the owner's own click.

## Decisions
- Direction of a paragraph comes from the majority script (Hebrew share of letters >= 30 percent), not the first letter.
- Permission levels: `careful`, `normal` (default), `free`; blocked actions at every level.
- Language is saved in the broker's `config.json` (`lang`) and a change reopens the window. Hebrew is the source language of the code strings.
- Wizard downloads will be jobs in the same queue, from pinned official URLs with checksums, only after the owner ticks them.
- The license of the repository is not chosen: the owner decides (suggested default MIT).
