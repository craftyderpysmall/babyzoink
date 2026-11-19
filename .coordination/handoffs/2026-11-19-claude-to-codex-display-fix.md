# Handoff (FYI + one small action): the GD display glitches the user reported are fixed

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: completed (done by Claude: slot 1 save patched while it was closed, queue #15)
Related: docs/PROTOCOL.md (windowed display), tools/gd_save.py, evidence below

## What the user saw
- [White top-right quadrant, rest of the screen flashing on open](../evidence/2026-11-19-gd-white-quadrant.png).
- [Game assets and the home screen in black and white](../evidence/2026-11-19-gd-black-and-white.png).

## Cause and fix
- The cause was my runtime fullscreen → windowed switch (`CCEGLView::toggleFullScreen` on the first frame). It left stale GL state, so sprites were untinted and the window flashed. This doesn't affect play: the bot reads hitboxes, not pixels. Earlier telemetry and results stand.
- The fix is GD's own setting `gv_0025=1` (windowed) in the bot's save. GD then starts windowed (640×480) with correct colours, and no switch is needed.
- Verified live with the new bridge `snapshot` op (`{"op":"snapshot"}` writes `snapshot.bmp` from the front buffer into the slot's dir; it never brings the window forward). Results: menu in full colour, drill levels in GD's default blue, and `sequential_test.py` 6/6.
- Saves already patched: slots 0, 2, 3. New slots inherit it from slot 0.

## Action
**Slot 1 is yours and still has the old setting.** When you next close it, run `build/gdbot-venv/Scripts/python.exe tools/gd_save.py 1 set gv_0025 1` before relaunching.
- Without this, the bridge falls back to the runtime switch: it still works, but looks broken, and logs `display: WARNING`.
- Relaunch with `mod/build/Release/gdbot-launch.exe --instance 1` to also pick up the new bridge (per-slot DLL copy, input guard, `snapshot`).
- Never patch a save while its slot is running: GD rewrites the save on a graceful exit.

## Response — [recipient/session, UTC]
