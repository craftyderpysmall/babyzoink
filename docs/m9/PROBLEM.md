# M9 problem record: the search fails on non-linear-looking levels (Because I Loved Her)

Recorded 2026-11-20 by Claude from the user's findings and screenshots. Related: plan `.coordination/plans/2026-11-20-m9-state-novelty-search.md`; queue rows #55 (research), #56 (bridge), #57 (solver).

## Level and stall

- **Level:** *Because I Loved Her*, online id **26791333**, in the M6 online training pool (`build/m6-scale/online/26791333.json`).
- **Where M6 #19 stalls:**
  - segment ~567, x ≈ 23,557, after 3,527 of 9,000 evaluations;
  - the stall escape ("random continuations 1-8 segments back") failed repeatedly there.
  - Saved prefix: `build/m6-scale/solutions/online_26791333.progress.json`.
- **Watch it at 1x:** `tools/m6/watch.py --slot N --level online:26791333 --only stall`.

## What the level looks like (the user's annotated screenshots)

| Image | What it shows |
| --- | --- |
| [1-intended-path.png](1-intended-path.png) | **The user's path.** The section starts at the arrow block (light-green box). Don't jump; drop down and right; take the **blue key**; pass the blue door; take the **yellow key**, which reverses direction; go left and up through the yellow door; take the **red key**, which reverses again; pass the start point again; *now* jump; go up the stairs and through the **red door** (pink block behind it). |
| [2-bot-path.png](2-bot-path.png) | **What babyzoink does.** It jumps immediately at the start, rides the stairs up, and dies at the red door. |
| [3-hitboxes-62pct.png](3-hitboxes-62pct.png) | **The same section with GD's "show hitboxes" (62%).** Two player hitboxes, one on the ceiling and one on the floor blocks, so **dual mode**. Plain block stairs, the screen ceiling, and key objects. |
| [4-hitboxes-65pct.png](4-hitboxes-65pct.png) | The same at 65%. The ceiling player's trail arcs after a click (1 CPS). The floor player rides plain block stairs. One key is still visible. |

## The user's key observation

**The level is a visual facade.** The keys, doors and the winding back-and-forth route are mostly decoration. The real hitboxes are much simpler: two players in dual mode, plain block stairs, and pickups that probably toggle groups. The user says this is common in "cool non-linear-looking" GD levels.

**Consequence: never reason from the art.** Reason from collision, both players, and the game state that actually changes.

## Why the current search fails (structural)

1. **Myopic acceptance.** A segment is committed when some simple follow-up survives ~40 decisions. The early jump survives that long; its consequence comes later.
2. **Shallow revision.** Depth-first backtracking revises about 1 segment within budget, and the stall escape 1-8. The wrong decision can be 20+ segments before the death.
3. **x as progress.** Stall detection, probe margins and the escape test treat "further right" as progress. Routes that reverse direction, and situations that repeat a position in a different game state, look identical.
4. **Player 2 is invisible to the bot.** Observations, death attribution and the CBF split all centre on player 1 (`m_isDualMode` isn't even mapped). In dual sections, the search can't tell which player died or where player 2 is.
5. **The game state isn't in the search state.** Pickups that toggle groups or items change what's solid later, but the solver's notion of "where am I" doesn't include them.

## Direction of the fix (to be agreed in the plan; broad, not level-specific)

- **Search that explores new situations (Go-Explore-style archive) as the stall fallback.**
  - Situation = both players' coarse position, mode, gravity and direction; dual on/off; a hash of the real toggled/activated object state and item counters.
  - Restore by exact replay. Measure progress by level time, not x.
- **Gameplay truth from the engine, not the art:**
  - report player 2 and dual mode;
  - which player died, and on which object (hitbox type, object id, group);
  - which groups and items changed when a pickup was touched.
- **Acceptance:**
  - this section **and the next section** of the same level (another key puzzle, held out) pass without level-specific code;
  - no regression on the existing verified clears.

## Outcome (2026-11-20)

The level is **cleared and verified from 0%** by the solver with the archive fallback, with no level-specific code. Details are in the plan's "#57 live validation result".
