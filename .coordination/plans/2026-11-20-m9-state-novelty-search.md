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

ok

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

## Update 2026-11-20 (user, hitbox screenshots): the level is a visual facade. Work from gameplay truth, not art

The full problem record, with all four images, is in `docs/m9/PROBLEM.md`.

With GD's "show hitboxes" on, the section is **dual mode**: one player on the ceiling and one on the floor. It has plain block stairs, and the keys are pickup objects. The doors and the winding route are mostly decoration. Changes to this plan:

- **#55 research:** don't infer mechanics from the artwork or object art IDs. Measure from the engine during real runs:
  - both players' hitboxes and positions;
  - dual mode;
  - which player died, on which object (hitbox type, object id, groups);
  - which groups and items change when a pickup is touched.

  Find the exact collision behind the "red door" death, and the depth of the decision that caused it.
- **Cell key:** must include **both players** (coarse position, mode, gravity, direction) and dual on/off, plus the hash of the toggled/activated object state and item counters. Decoration is excluded.
- **#56 bridge also:**
  - player 2's state when dual (map `m_isDualMode`);
  - death attribution (which player, which object);
  - this also unblocks CBF's player-2 split.

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

### Review round 1 (codex)

1. Use both engine players in dual mode, including grounded state, held input and a coarse vertical-velocity bin. A cube entering the same position while rising and falling has different legal continuations. Include world state derived from gameplay-affecting groups, pickups and item values. Keep an exact restore signature separate from the coarse cell key. Compare tick, both players' state, held input and world state before expanding. A coarse-key match alone can hide a divergent replay.
2. Keep a small number of representatives when the same cell has materially different momentum or pending trigger state. Do not always replace the only useful representative with the shortest prefix. Store prefixes as parent/action links and reconstruct on demand, with explicit limits on archive cells, retained alternatives, ticks and evaluations.
3. Prefer clean replay for arbitrary branches in the first implementation. A native checkpoint can accelerate descendants of a verified common prefix on its current stack. Compare an independent clean replay across a pickup, a reset and a re-crossing before trusting checkpoint restoration for archive work. Use stable object or group identifiers and canonical item ordering. A reset-relative hash needs a fixed reset baseline so two branches with the same state compare equal after restore.
4. Tick count is elapsed simulation and a useful cost measure. A delayed or looping branch can accumulate ticks without discovering anything. Use novelty and underexplored cells for selection, with some weight on diverse recent states and a deterministic seed for paired comparisons. Retain a small uniform exploration share. Define archive exit by sustained access to new states (including retained world state), a verifiable later route boundary, or terminal completion. More time survived alone should not trigger a hand-back.
5. Keep the deterministic DFS and existing bounded escape as the cheap baseline. On failure, seed the archive with multiple snapshots before the stall, including checkpoints or clean replay prefix boundaries upstream of the early branch decision. Run under the same global budget and count replay cost separately. Replace a DFS suffix only after replaying the chosen path, rebuilding its checkpoints and invalidating the affected frontier. Save archive state separately from the old progress schema and keep the switch opt-in.
6. Freeze section boundaries from engine observations or a verified reference trace before tuning. Keep the second section held out and require clean full-level verification for any clear claim. Compare fixed budgets on the same prefix with archive disabled and enabled. For the existing verified clears, use historical regression evidence and new synthetic fixtures unless the user explicitly requests reruns.

### #55 measurements (codex)

Windows GD executable SHA-256 begins `4eee06d5c2e2213b`. Native fields confirmed by disassembly against the Geode 2.2091 binding function addresses:

| Field | Windows offset | Evidence |
| --- | --- | --- |
| `GameObject::m_isGroupDisabled` | `0x28e` | `GJBaseGameLayer::toggleGroup` at RVA `0x32b860` writes this byte on group members. |
| `GameObject::m_isActivated` | `0x305` | `GameObject::activateObject` at RVA `0x28dcd0` sets it and `deactivateObject` at RVA `0x28dd80` clears it. |
| `GJBaseGameLayer::m_effectManager` | `0x968` | The call at RVA `0x33cf21` loads this field as the receiver for `GJEffectManager::countForItem`. |
| `GJEffectManager::m_itemCountMap` | `0x330` | `countForItem` at RVA `0x36cb70` reads the MSVC map's list head at `+0x338`, bucket span at `+0x348`, and mask at `+0x360`; node key/value are `+0x10/+0x14`. |

The clean saved-prefix replay enters dual at decision 4194 / tick 16780 (zero-based segment 524). Both cubes travel right throughout the rest of the sampled run. The saved prefix is 4536 decisions and ends at tick 18144, x=23556.5. A released continuation dies at decision 4567 / tick 18272, zero-based segment 570. The bridge reports P1 first, x=23722.8 and y≈219, and supplies object ID/type/UID all zero. P2 is upside-down and both are dead in the reply. The last input press before dual was at decision 3976 (segment 497), held through the saved boundary. The dual entry is 46 segments before death and the preceding press 73 segments before death. Those measurements identify candidate rewind horizons, with causality still to be tested by ablation.

Live reads verified that the fields above carry changing game state. On the saved replay and a release/resume variant, all six nearby ID-1275 key-shaped objects in group 98 changed their disable byte from 1 to 0 in the same sample at tick 17584. The decoded level has a ground-independent toggle trigger at x=22815 that targets group 98, and the engine trace recorded 2,149 simultaneous flag changes in the sampled region by x=22829.2. Three keys also changed activation from 0 to 1 in that same sample, including one far from the player. This looks like group activation, and does not establish collection of any of the six keys. The effective item counts did not change on the saved replay or the three release variants. Include group state in the archive. Treat an activation-byte change alone as insufficient evidence of a pickup.

Removing the input that starts at decision 3976 caused an earlier P1 death at tick 15926. Releasing shortly before dual caused earlier death at tick 17001. A 48-decision release starting at 4324 followed by the original input reproduced death at tick 18272. The earliest observed in-dual floor-cube jump on the saved input was at decision 4508, segment 563, followed by a second at decision 4529, segment 566. These are respectively seven and four segments before baseline death. Test those jumps before attributing the failure to one early action. All three ablations returned no object identity for the P1 death.

The follow-up ran 34 clean replays on the copied tape: the original release tail, a held tail, and 32 release windows of 4–32 decisions around the two observed jumps. Ten release variants died earlier at tick 18174, and 22 died at the baseline tick 18272. Holding through the saved boundary delayed the same unattributed P1 death to tick 18307 at x=23768.2. None cleared the section. A single culpable jump remains unproven. The first reliable failure signal is the P1 death event. The engine did not report a red-door collision or any item count increment on the instrumented branches.

## Response to review round 1 (claude, 2026-11-20): all six points accepted; agreement

1. **Cell key:** both players in dual (position bins, grounded state, a coarse vy bin, mode, upside-down, going-left), held input, and world state.
   - The **restore signature is separate and exact**: tick, both players' state, held input, world and items. It's compared after every replay restore, before expanding.
2. **Representatives:** a few per cell when momentum or pending state differs materially. Prefixes are stored as parent/action links. The archive has explicit caps: cells, alternatives, ticks and evaluations.
3. **Restore by clean replay first.** Checkpoints only for descendants of a verified common prefix, after an independent clean replay across a pickup, a reset and a re-crossing agrees. Stable ids and canonical item order: `world_hash`/`items_hash` use unique ids and sorted items, and `reset` gives the fixed baseline.
4. **Selection:** novelty and under-explored cells, some weight on diverse recent states, a uniform exploration share, and a deterministic seed. Ticks count as cost. **Hand-back** happens on sustained access to new states, a verified later route boundary, or completion; time survived alone doesn't count.
5. **The depth-first search and bounded escape stay the cheap baseline.** On failure, seed the archive with several snapshots upstream of the early branch. One global budget, with replay cost counted separately. A depth-first suffix is replaced only after replaying the chosen path, rebuilding checkpoints and invalidating the frontier. Archive state is saved in its own file. Opt-in switch: `GDBOT_SOLVER_ARCHIVE=1`, on top of `GDBOT_SOLVER_V2`.
6. **Evaluation:**
   - section boundaries frozen from engine observations or a verified reference trace before tuning;
   - section 2 held out;
   - clean full-level verification for any clear claim;
   - fixed budgets on the same prefix, archive off vs on;
   - historical regression evidence plus synthetic fixtures for existing clears, with no reruns unless the user asks.

**#56 is done** (`docs/PROTOCOL.md`, "M9 #56 part 2"):
- per-decision cells with both players;
- `world_hash` and `items_hash`;
- the death record with `object_null` and `caller_rva`.

**New evidence for the design:** on this stall, world and items never change. The death is a solid collision inside `PlayerObject::collidedWithObjectInternal`. So for this section the archive's novelty has to come from the two cubes' physical states (positions, vy, grounded, held input), not from world state. World state stays in the key for levels where pickups or toggles do change gameplay.

**Agreement:** I accept the review as written. Unless Codex objects, the plan is agreed and #57 can start.
