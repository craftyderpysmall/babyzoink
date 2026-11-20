# Handoff: M9 state-novelty search. Review the plan, research (#55), then the solver (#57)

From: claude
To: codex
Created: 2026-11-20
Status: pending

The user found that Because I Loved Her (online:26791333) is a non-linear key/door puzzle with direction reversals. The bot jumps at the section start and dies at the red door, because it never took the red key. The user wants a **broad** fix, not one specific to this level. The next section of the same level is another key puzzle, and it's the held-out test.

Plan: `.coordination/plans/2026-11-20-m9-state-novelty-search.md`. In short: an archive search in the Go-Explore style, keyed by position, mode, direction and a world-state signature (keys, doors, toggles), used as the fallback when the depth-first search stalls, with progress measured by time instead of x.

Please:
1. **Review round 1.** Add a "Review round 1 (codex)" section to the plan. Challenge the cell definition, the restore method (prefix replay from 0% vs checkpoints, given world state), the selection weights, and the integration with the stall escape and #38/#39/#51.
2. **#55 research** (claim slot 1 or 3; launch with `GDBOT_DEBUG=1` so `debug_peek` works). The plan lists the questions. The key outputs:
   - the GameObject offsets of `m_isGroupDisabled` and `m_isActivated`;
   - where item counters live;
   - which of these change when a key is collected;
   - the segment distance between the bad jump and the death.

   Put offsets in the plan; I'll expose them in the bridge (#56).
3. **#57 solver**, after #55 and agreement. Build it behind `GDBOT_SOLVER_ARCHIVE=1`, because #19's worker re-imports `tools/m5c/solver.py` on every recycle.

#19 is paused by the user. Its saved prefix for this level is `build/m6-scale/solutions/online_26791333.progress.json`; work on copies. `tools/m6/watch.py --slot N --level online:26791333 --only stall` shows the failure at 1x.

**Update (user):** the level is a visual facade. With hitboxes shown, it's dual mode, with plain block stairs and key pickups; the doors and the winding route are decoration. Read `docs/m9/PROBLEM.md` (with all four images) and the plan's update section. Research from engine truth (both players, death attribution, toggled groups and items during real runs), never from the art.

Don't edit `mod/`. Bridge changes go through Claude.

## Update from Claude (#56 part 1 is in the new bridge, mod/build/Release)

These are available now for your #55 research:
- `dual` and `player2` in replies and obs;
- `death = {player, object_id, object_type, uid, x, y, tick}`;
- `going_left`;
- `debug_peek target=player2`.

What I already found on the stall:
- dual mode turns on at decision ~4,224;
- the bot's paths die as **player 1 at x≈23,723-23,768, with no object** (`destroyPlayer(player, nullptr)`). That's a side or crush collision with a solid, not a hazard.

Still needed from you: the offsets for the GameObject group-disabled/activated flags and the item counters (for `world_hash`, #56 part 2). The CBF dual split is wired too (player 2 split in dual mode, as upstream); please include a dual fixture in #47.
