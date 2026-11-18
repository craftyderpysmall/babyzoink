# Handoff: make the trainer follow the user's dedicated/background toggle

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-18
Status: pending; waiting for Claude's live test of the bridge side (it needs the game runtime)
Related: docs/PROTOCOL.md (run modes), tools/mode.ps1

## Request
The user wants one switch between "use as much CPU as possible" and "run politely in the background while I use the PC". The bridge side is done:
- **Ways to switch:** the hotkey Ctrl+Alt+B, or `tools\mode.ps1 dedicated|background|auto`, which writes `game/2.2091/gdbot/mode.txt`.
- **User choice wins:** a user choice overrides the client's `set_mode`. It persists until the user sets `auto`. `set_mode` replies include `overridden_by_user: true` when that happens.
- **What GD does:** in background, GD drops to below-normal priority, 4 hardware threads and 6 ms request bursts. In dedicated it uses all threads, normal priority and 12 ms bursts.
- **Mode reporting:** every `step` and `hello` reply now includes `"mode"`.

Make the Python side follow it:
1. In the env/trainer, read `mode` from step replies. On a change:
   - **background:** `torch.set_num_threads(2)`, set the Python process to BELOW_NORMAL priority (`psutil` or ctypes `SetPriorityClass`), and limit its affinity to the same 4 highest-numbered hardware threads as GD.
   - **dedicated:** `torch.set_num_threads(<physical cores>)`, normal priority, all threads.
   - Log each switch with its timestamp.
2. Keep training results unaffected. Modes change pacing only. Add a test that a short fixed-seed run gives the same transitions under both modes (dedicated vs background mid-run).
3. Measure transitions/s in each mode (dedicated vs background), and in background the CPU share left for the user (total CPU % with training paused vs active). Record both in `tasks/M2-live.md` under "Run modes".

## Files / claims
- Claim `RUNTIME:gd-2.2091` plus `gdbot/`, `tests/`, and `tasks/M2-live.md`.
- Don't edit `mod/`, `injector/`, `docs/PROTOCOL.md`, or `tools/mode.ps1`. Claude commits.

## Response — [recipient/session, UTC]
