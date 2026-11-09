# AI Broker: progress tracker

Kept up to date while working (what is done, what is open, what is NOT verified). Newest items last in each section. `[x]` done and checked, `[~]` in progress, `[ ]` open.

## Owner requests

| # | Request (owner, 2026-11-09) | Status |
|---|---|---|
| 1 | One window, queue, resources, per-model output folders, chat per model, Claude built in (no terminal) | [x] done earlier (commits up to `1d8b930`) |
| 2 | Professional dark IDE-like look, explanation on every model page | [x] done; model pages without an interface route requests to Claude |
| 3 | Keep the current logo ("we stay with our logo") | [x] decided, nothing to do |
| 4 | Hebrew text in chat is "crooked" when a paragraph starts with an English name; learn from Terminal Grid | [~] `rtltext.py` + `MessageView` (direction per paragraph by majority script) written, tested in isolation; being wired into the assistant chat |
| 5 | Claude's messages should start from the right (not the left) | [~] `aligned_start()` written, not yet checked in the live window |
| 6 | Approval cards must say in plain Hebrew what the action does (no raw JSON) | [~] `permissions.py` (classifier + Hebrew descriptions, 66 unit checks pass) done; card UI pending |
| 7 | Owner chooses the permission level (careful / normal / free), not asked "every second" | [~] daemon ops done (`perm_ask`, `perm_get`, `perm_answer`, `assistant_level`); MCP `approve` tool, Worker flag and GUI selector pending |
| 8 | Space planning: side panels and the empty queue take too much room, the important middle too little | [ ] |
| 9 | Settings (gear icon) instead of "Advanced", with a language choice: Hebrew and English | [ ] |
| 10 | Whole UI available in English (RTL/LTR switch) | [ ] |
| 11 | GitHub documentation in English (README, docs); Hebrew README as a separate file | [ ] (push to GitHub only after the owner says so) |
| 12 | First-run setup wizard: pick model kinds, hardware check, recommended models, download, finish; connect Claude Code | [ ] idea accepted; `hardware_profile` (daemon op + `aibroker/hardware.py`) is the first piece and is done |
| 13 | Keep a file that tracks what is done and what is not | [x] this file |

## Done (checked)
- Tests no longer touch the owner's data (`tests/sandbox.py`: throw-away data folder and Qt settings; refuse to run without the real service).
- Empty start cards float in the middle of the page (screenshot checked in the live window).
- Permission classifier: 66 unit checks (`tests/test_permissions.py`).
- Hardware profile: GPU, VRAM, RAM, disks, installed tools in about 0.2 s (`aibroker/hardware.py`).
- Verified with a real `claude -p` call: `--permission-prompt-tool` lets the broker answer or hold a permission request in the same turn (no turn restart). The tool must return a plain text block (`structured_output=False`).

## Not verified yet (say so to the owner)
- Real Claude run through the new approval flow inside the window (only the throw-away probe in the scratchpad was run).
- English UI, settings dialog, setup wizard: not started.
- Windows login autostart (real login), macOS/Linux: Windows only for now.

## Decisions
- Direction of a paragraph comes from the majority script (Hebrew share of letters >= 30 percent), not the first letter (Terminal Grid design rule 10).
- Permission levels: `careful` (asks for every shell command), `normal` (default: read-only commands run, changes ask), `free` (changes run; deletes and stopping programs still ask; formatting, registry, system and Claude's own settings are blocked at every level).
- Downloads of models in the wizard are jobs in the same queue, from pinned official URLs with checksums, only after the owner ticks them.
