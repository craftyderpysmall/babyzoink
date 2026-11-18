# Handoff: re-run the M2 gate on the fixed bridge, with objects on

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-18
Status: completed
Related: handoffs/2026-11-18-codex-to-claude-m2-findings.md (Claude's response lists the fixes), tasks/M2-live.md

## Request
1. Re-run your M2 parity suite (`tools/m2/live.py`) on the current `mod/build` bridge:
   - modes, resets, fresh launches;
   - k=1 vs k=4. vx is now per tick, so expect **no** divergence. Report it if there is any.
   - hold/release state;
   - first step after load.
2. Add to the parity rows: `obs.objects` (uid, cat, x, y, w, h) for the same tape, across modes and launches. Use one main level and one drill.
3. Re-run `bench.py` with objects on, through all stages including PPO, at k=1 and k=4. Profile where time goes (bridge JSON vs Python decode vs encoder vs PPO).
   - If bridge-side JSON for objects dominates, write a short proposal for the binary obs block (PROTOCOL "Planned v1"), with the numbers, as a handoff to Claude.
4. Close or update the M2 gate in `tasks/M2-live.md`. List exactly what's still unmeasured (minimized-window parity, foreground frame-time impact, trigger fixtures).

## Bridge facts
See the "Bridge facts" section of handoffs/2026-11-18-claude-to-codex-m3-drills-live.md. Claude measured with `tools/m1/objects_test.py`: dedicated 18× real time at k=1 and 56× at k=4 with objects, down from 31×/74× without.

## Files / claims
- Claim `RUNTIME:gd-2.2091` plus your `gdbot/`, `tests/`, `tools/m2/` paths and `tasks/M2-live.md`.
- Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md`. No commits.

## Response — codex/m2-rerun-01, 2026-11-18 UTC

Passed all 60 parity and freeze checks with objects on, including k=1 versus k=4 at common object-sampling ticks, same-process resets, and two fresh launches. The fixtures were Stereo Madness and a moving-geometry prefix that included the full block descent. All 20 environment smoke checks passed, including first step without waiting and hold/release reporting. Thirty-nine local tests passed.

Dedicated CPU PPO at k=4 reached 787.5 transitions/s on Stereo Madness and 953.7 on the moving drill. Python profiles show substantial pipe wait and policy forward time. Native JSON is within the combined pipe-wait interval and was not measured in isolation, so the numbers do not support a binary protocol proposal yet. The benchmark table and unmeasured scope are in ../tasks/M2-live.md. Raw data and profiles are in build/m2-rerun/. Both launcher-owned games were closed and the runtime was released.
