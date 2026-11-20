# Plan: M9, state-novelty search for non-linear levels (keys, doors, reversals)

Proposer: claude. Created 2026-11-20. Status: **proposed. Codex review and work requested (#55-#57).**
Requested by the user. They want a broad fix, not one specific to this level.

## Problem (user's screenshots, Because I Loved Her, online:26791333, stall at segment ~567, x≈23,557)

Desktop images `intendedpath.png` and `botpath.png`, described here:
- **Section layout.** From the start (an arrow block), the intended route goes:
  1. Don't jump. Drop down and right, take the blue key, pass the blue door.
  2. Take the yellow key. That **reverses direction** (now moving left).
  3. Go up and back left through the yellow door, take the red key on the far left. That **reverses direction again**.
  4. Pass the start point again, and only now jump: up the staircase, through the red door.
- **What the bot does:** it jumps immediately and dies at the red door, because it has no red key.
- The next section of the level is another key/door puzzle, so it serves as a held-out test.

## Why the solver fails (three structural reasons, not this level's specifics)

1. **Myopic acceptance.** A segment is kept when some simple follow-up survives about 40 decisions. The jump at the start survives that long; the death at the red door comes much later.
2. **Shallow revision.** Depth-first backtracking revises about 1 segment within budget, and the stall escape 1-8. The bad decision is about 20+ segments before the death.
3. **x as progress.** Progress, stall logs and probe margins use x. On a route that goes right, left, then right, passing the start point the second time (now holding the red key) looks identical to the first pass. Nothing in the search state distinguishes "has key" from "no key".

## Proposal: archive-based exploration (Go-Explore-style) as the stall fallback

- **Cell key** (a coarse, discrete description of "where am I, in what situation"):
  - `x // 30`, `y // 30`, game mode, gravity, mini, speed;
  - **direction of travel** (`m_isGoingLeft`);
  - **world-state signature:** a hash of which level objects have been toggled or activated (`GameObject::m_isGroupDisabled` / `m_isActivated` across the level's objects), plus the layer's item counters. Collecting a key or opening a door changes it, so "same place, now holding the key" is a new cell.
- **Archive:** for each cell, the shortest input prefix (decisions) that reaches it, plus visit and attempt counts.
- **Loop:**
  1. Pick a cell, weighted toward few attempts, newly found, and further along by **level time/ticks** (not x).
  2. Restore it by replaying its prefix from 0%. Restores must be exact and deterministic; checkpoints are optional when they're proven exact for world state.
  3. Explore N random or candidate segments from there, recording every new cell or cheaper prefix.
  4. On `complete`, stop and verify with a clean 0% run (unchanged acceptance).
- **Integration:** the existing segment depth-first search stays the default; it's cheap and works on linear levels. When it stalls (no depth progress for `STALL_EVALS` and the escape has failed), it hands over to archive exploration. Archive exploration returns to depth-first search once a new furthest cell is reached. Either mode can finish the level.
- **Replace x-based progress** with level time/ticks, or cell novelty, wherever it decides anything (stall detection, the escape's success test, `stall_probe` margins). Logs may keep x.

## Work split

- **#55 (Codex), research, no solver change:**
  - From the level data of online:26791333: how keys, doors and direction reversals are built (object IDs: pickup/collectible items, toggle/item/count triggers, reverse portals). Which game state changes when a key is taken: item counters, group-disabled flags, or both.
  - With `GDBOT_DEBUG=1` and `debug_peek` on a test slot, confirm the GameObject offsets of `m_isGroupDisabled` and `m_isActivated`, and where the item counters live (GJEffectManager or GJBaseGameLayer `m_persistentItemCountMap`). Use the geode bindings 2.2091 member order anchored on verified fields (`m_uniqueID` 0x39c, `m_objectType` 0x3a0, `m_objectID` 0x40c).
  - Measure: the depth of the bad decision (the segment where the bot jumped) vs the death segment.
- **#56 (Claude), bridge:**
  - `step_seq` and `reset` replies get `state: {going_left, world_hash, items_hash}`, plus an opt-in `cells: true` that returns the state at every decision boundary.
  - Computed cheaply: the hash covers only objects whose toggle/activated flags changed since reset (tracked incrementally where possible).
- **#57 (Codex), solver:**
  - archive exploration as the stall fallback;
  - time-based progress;
  - developed behind a switch (`GDBOT_SOLVER_ARCHIVE=1`) so #19 isn't affected by its per-recycle re-import;
  - benchmarks on a copy of the saved progress.
- **Acceptance:**
  - Because I Loved Her passes section 1 (the red-door puzzle) **and section 2** (another key puzzle, held out) without level-specific code;
  - no regression on Stageix, Skill Gotten Gains and the official 1-3 clears (same verified results, comparable evaluations);
  - total ticks and evaluations reported.

## Review history

- Round 1 requested from Codex (handoff 2026-11-20-claude-to-codex-m9-novelty.md).
