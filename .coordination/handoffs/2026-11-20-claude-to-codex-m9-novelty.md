# Handoff: M9 state-novelty search. Review the plan, research (#52), then the solver (#54)

From: claude
To: codex
Created: 2026-11-20
Status: pending

The user found that Because I Loved Her (online:26791333) is a non-linear key/door puzzle with direction reversals. The bot jumps at the section start and dies at the red door, because it never took the red key. The user wants a **broad** fix, not one specific to this level. The next section of the same level is another key puzzle, and it's the held-out test.

Plan: `.coordination/plans/2026-11-20-m9-state-novelty-search.md`. In short: an archive search in the Go-Explore style, keyed by position, mode, direction and a world-state signature (keys, doors, toggles), used as the fallback when the depth-first search stalls, with progress measured by time instead of x.

Please:
1. **Review round 1.** Add a "Review round 1 (codex)" section to the plan. Challenge the cell definition, the restore method (prefix replay from 0% vs checkpoints, given world state), the selection weights, and the integration with the stall escape and #38/#39/#51.
2. **#52 research** (claim slot 1 or 3; launch with `GDBOT_DEBUG=1` so `debug_peek` works). The plan lists the questions. The key outputs:
   - the GameObject offsets of `m_isGroupDisabled` and `m_isActivated`;
   - where item counters live;
   - which of these change when a key is collected;
   - the segment distance between the bad jump and the death.

   Put offsets in the plan; I'll expose them in the bridge (#53).
3. **#54 solver**, after #52 and agreement. Build it behind `GDBOT_SOLVER_ARCHIVE=1`, because #19's worker re-imports `tools/m5c/solver.py` on every recycle.

#19 is paused by the user. Its saved prefix for this level is `build/m6-scale/solutions/online_26791333.progress.json`; work on copies. `tools/m6/watch.py --slot N --level online:26791333 --only stall` shows the failure at 1x.

Don't edit `mod/`. Bridge changes go through Claude.
