# Handoff: M5 curriculum: drills for every game mode, a generation loop, then official levels

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: pending
Related: plan M5/M6; tasks/M3-imitation.md and tasks/M4-practice.md (the recipe); gdbot/levels/drills.py; gdbot/curriculum.py; tools/m4/practice.py

## Why
So far every drill is cube-only. The recipe that works is behaviour cloning, plus checkpoint practice whose successful sections become new demonstrations (self-imitation; 19/27 → 23/27). M5 widens that to the rest of the game. It also shows the plan's core claim: each generation needs fewer attempts on levels it has never seen.

## Request (in order; steps 1–2 need no game)
1. **New drill families** in `gdbot/levels/drills.py`, using the same layout as before: train, validation and held-out variants from fixed seeds, plus a manifest entry. Add start-position or portal-entry drills for each mode:
   - ship corridors, ball gravity switching, UFO taps, wave corridors, robot variable jump, spider, swing;
   - pads (yellow, pink, blue gravity), orbs (pink, blue, green, black, dash);
   - a mini portal, plus one or two mixed-mode drills that join two modes with a portal.
   - Hold-based modes (ship, wave, swing) need tapes with many edges, so keep the first versions short and forgiving.
   - Look up object IDs and properties for 2.2 objects online. Cite sources in `levels/drills/README.md` like the current table does.
2. **The generation loop** (`gdbot/curriculum.py` + a runner in `tools/m5/`):
   - Generation g = BC on every demonstration archive so far (verified train tapes plus self-generated practice clears from earlier generations).
   - Each generation, run practice (the M4 procedure) on the next unlocked train drills. Successful runs go into the archive.
   - Promotion rule: a family unlocks the next one when its train drill is cleared cleanly from 0.
   - Evaluate each generation on the frozen held-out set: attempts to first clear (with practice, 3-full-attempt cap) and zero-shot first-run progress.
   - Validation layouts only, for any model selection. Held-out never supplies actions or selection.
3. **Live:**
   - Verify each new drill in GD: objects, categories and params as the bridge reports them, completion tapes, `training_ready`. The categories table is `mod/src/control.cpp` `category()`/`params()`. Only the cube/orb/gravity/speed entries have been checked live so far. If a type number is wrong or a field is missing (e.g. dash state, mode-specific velocity), write a `codex-to-claude` handoff instead of working around it.
   - Then run at least 3 generations with 3 seeds. Report the per-generation held-out curve: clears, mean attempts, progress.
4. **Official levels (zero-shot + practice):**
   - Run the newest generation on main levels 1–5 (`load_level` kind `main`): Stereo Madness, Back on Track, Polargeist, Dry Out, Base After Base.
   - Report first-run progress and attempts to first clear with practice (cap 10 full attempts here).
   - No external replays or tapes as demos. Only the bot's own practice clears count.
5. Write `tasks/M5-curriculum.md` with results, cost (ticks, wall time, CPU) and the next bottleneck.

## Out of scope / owned elsewhere
- **Triple spike:** Claude is investigating it now (queue #11). Leave it as-is in the held-out set and don't spend time on it.
- **Parallel GD instances:** Claude is building bridge support (queue #12). Assume one instance for now.

## Constraints
- **The game is shared.**
  - Claude holds `RUNTIME:gd-2.2091` for about the first hour (triple spike + the throughput measurement). Do steps 1–2 first.
  - If the runtime is still claimed when you need it, re-read CLAIMS.md every ~5 min for up to 90 min, then mark the row `blocked: runtime` and stop.
  - Claude won't take the runtime back while your claim is active.
- **Memory:** an earlier run was killed for low RAM. Keep demo archives on disk, load them lazily, and don't keep several models in memory at once.
- **Resumability:** leave runners resumable per generation/seed. If you run low on budget, write a "where it stands" note in the task file.
- CPU only. Use `set_mode dedicated`, which the user's toggle can override. Keep working in background mode, only slower.
- **Claims and files:**
  - Claim `RUNTIME:gd-2.2091` (when live) plus `gdbot/levels/`, `gdbot/curriculum.py`, `levels/drills/`, `tools/m5/`, `tests/`, and `tasks/M5-curriculum.md`.
  - Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md`. Claude commits.

## Response — [recipient/session, UTC]
