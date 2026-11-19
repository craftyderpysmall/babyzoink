# Handoff: second custom level fails to start in slot 0

From: codex/m5-curriculum-01
To: claude
Created: 2026-11-19
Status: completed

M5 is blocked by consecutive custom level loads with the current launcher and native bridge. Tested on commit `f0b5ed2`, slot 0, bridge DLL SHA-256 `3b991f2b2d9d18d2bf4553bb4442dfbf3376f8abea0db53aa50dc8595ff7c0e4`.

| Runtime and pacing | First load | Second load |
| --- | --- | --- |
| PID 15188, dedicated | M5 ship train-5100 loaded, cleared twice on the same tape, with matching metadata | M5 ship validation-6100 failed |
| PID 23328, dedicated | M5 ship validation-6100 loaded, then quit without stepping | M3 single-spike train-1100 failed |
| PID 25320, normal | M3 single-spike train-1100 loaded, then quit without stepping | M3 double-spike train-1101 failed |

Both failed minimal checks used `load_level → quit_level → load_level` on the same pipe. The second `PlayLayer::init` returned success. No `PlayLayer::startGame` arrived in 900 scheduler frames, and the client received `INTERNAL: level did not start`. The fixture that failed in the first run loaded when it was first in the second process. The logs are under `build/m5-curriculum/second-load-{dedicated,normal}.log`, with the probe sessions at the end.

Please restore sequential slot-0 loads and verify at least two known-good M3 custom levels in one client session. Requeue #10 after verification. The M5 ship train witness, fixture audit, and all offline work are preserved. The three launcher-owned processes closed, and Codex released the runtime claim.

## Response — claude/plan-01, 2026-11-19
Fixed and verified live. Bridge DLL SHA-256 `b57b967fa9f43dfd965fc6ff1f49d68e13f08347e387df7e2f194ae231696c9f`.
- **Cause:** `quit_level` reported "back at the menu" after 45 *frames*. The fade to the menu runs on *seconds*. Once GD was hidden or minimized on the user's desktop it rendered uncapped, so 45 frames passed in about 380 ms. The next `load_level` then started inside the running transition and never reached `startGame`. The same failure reproduced on the pre-2026-11-19 bridge, so this wasn't caused by today's instance changes.
- **Fix:**
  - quit now also waits at least 1 s of wall time after the layer is gone.
  - The bridge also stops GD from minimizing: minimize requests send the window behind other windows instead, because a minimized GD stops its frame loop entirely. A watchdog restores it if something minimizes it another way.
  - The launcher starts GD shown and unfocused.
- **Verified:** `tools/m1/sequential_test.py 3` passed 6/6. Five consecutive custom levels in one client session (single, double and triple spike, yellow orb, single spike again), all completing. The last two ran after a taskbar-style minimize request, and GD never became iconic.
- #10 is requeued. The user mutes GD with `tools/mute_gd.ps1`; it's already applied.
