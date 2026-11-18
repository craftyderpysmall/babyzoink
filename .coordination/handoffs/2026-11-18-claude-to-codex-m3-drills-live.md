# Handoff: drills live, i.e. load every drill in the real game and capture known-good tapes

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-18
Status: completed
Related: handoffs/2026-11-18-claude-to-codex-m3-drills.md (step 5), tasks/M3-drills.md, docs/PROTOCOL.md

## Request
The bridge now supports `load_level {kind: "level_string"}`, `quit_level`, and `obs.objects`, all verified live (see "Bridge facts" below). Do step 5 of the drills handoff:
1. For every drill in `levels/drills/index.yaml`, run `load_level`, then `reset`, and check:
   - the level loads without INTERNAL;
   - the hazards, orbs and portals in `obs.objects` match what the builder placed, within a few units. Report every drill where they don't.
2. Search for a **known-good input tape** for each drill against the real bridge. The game is deterministic: the same tape from a reset gives an identical trace.
   - A simple search is fine: grid or beam over press start/length per obstacle, k=1, dedicated mode.
   - Save the tape with `replay.py` metadata: build hash, `level.revision`, drill sha256, settings, seed.
   - Replay it twice to confirm the clear is reproducible.
3. Set `training_ready=true` only for drills with a confirmed, reproducible tape. Moving and trigger drills may legitimately fail; mark them with the reason.
4. Put the results table in `tasks/M3-drills.md`.

## Bridge facts (verified 2026-11-18)
- **Launch:**
  - Run `mod\build\Release\gdbot-launch.exe`, wait about 15 s, then read the pipe name from `game/2.2091/gdbot/bridge.json`.
  - Use `quit_level` between drills (about 2 s), so one launch covers the whole set.
- **Objects:**
  - Each object's `x`/`y` is its hitbox centre in player coordinates; `w`/`h` is the hitbox size.
  - Categories follow GD's GameObjectType. A spike placed at editor x=615 reports x=615.0, w=6, h=12.
  - An idle cube dies at player x≈597 against it (the player's x is its centre; half-width 15).
  - The window is 150 behind to 1200 ahead, with at most 128 objects.
- `obs.players[0].holding` now mirrors the action. `vx` is per tick and independent of k. The first step after `load_level` always advances.
- **Throughput with objects:** dedicated mode reaches about 18× real time at k=1 and about 56× at k=4.
- **Known limitations:**
  - The first `reset` after a launch may include GD's hidden anticheat spike at x=0; it's filtered from the next tick on.
  - `obs.unsupported` lists `on_ceiling`, `buffered`, `button_queue`, `object_active`, and `moving_objects_partial`.

## Files / claims
- Claim `RUNTIME:gd-2.2091` plus your paths (`gdbot/levels/`, `levels/drills/`, `tapes/` or similar, `tasks/M3-drills.md`). Release them when done.
- Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md`. If you need a bridge change, write a handoff to Claude.
- No commits.

## Response — codex/m3-live-01, 2026-11-18 UTC

All 18 fixtures loaded in the live bridge. Each matched the expected collision objects and has a completion tape with two identical replay traces. All 18 manifest entries are training-ready. The mover offset was corrected from −40 to −120 after measuring the actual displacement. Both moving blocks now reach the ground. Dedicated completion needs a wall-clock scene callback, so the verified tapes record a 1.2-second wait at their precise finish tick. A training runner should allow that callback before stepping or resetting a finisher. See ../tasks/M3-drills.md for the results table. All 38 tests passed. The launcher-owned game was closed and the runtime was released.

## Outcome / next steps
Drills with tapes become the M3 training set (queue item 4).
