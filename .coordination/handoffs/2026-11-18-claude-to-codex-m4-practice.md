# Handoff: M4 practice, start positions and checkpoints in the training loop ("drill the hard part")

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-18
Status: pending (bridge side verified live 2026-11-18)
Related: plan Decision 5 + M4; docs/PROTOCOL.md (practice ops); tasks/M3-scale.md (use the chosen encoder)

## Request
Make training resemble how players improve: drill the sections where the agent dies, then do full runs from 0%.
1. **Start positions (Python only, no bridge work):**
   - Add `with_startpos(level, x, mode, speed, gravity, mini)` to `gdbot/levels/levelstring.py`, inserting GD's start-position object (look up the id/keys and document the source).
   - A drill variant with a start position loads as its own `level_string`.
   - Verify live: the player spawns at x with the requested mode/speed/gravity.
   - Note: GD start positions don't replay earlier triggers, so use them only for sections whose preceding trigger state doesn't matter. Flag drills with triggers.
2. **Checkpoints (bridge ops, verified by Claude):**
   - `set_practice {enabled}`
   - `checkpoint_create` → `{checkpoint_id, tick, x, count}`
   - `checkpoint_pop`
   - `reset {start: {kind: "checkpoint"}}` restores the newest bot checkpoint. To restore an older one, pop the newer ones first.
   - `reset {kind: "zero"}` turns practice off and is the only way a run counts as a full clear.
   - Practice auto-checkpoints are blocked while the bot is in control.
3. **Practice curriculum** (`gdbot/curriculum.py`):
   - Death-hotspot sampling: keep per-level death-x histograms and start practice episodes just before hotspots, via checkpoints or start positions.
   - Reverse curriculum near the end.
   - A gate: periodic full runs from 0%; a level is "beaten" only on a clean full run.
   - Track practice cost: resets, ticks, wall time.
4. **Measure the point of M4:**
   - On held-out drills, compare attempts-to-first-clear and practice cost **with** vs **without** the practice curriculum.
   - Use the same frozen protocol as M3, with the encoder chosen in M3-scale.
   - Write `tasks/M4-practice.md`.

## Files / claims
- Claim `RUNTIME:gd-2.2091` plus `gdbot/`, `tests/`, `tools/m4/`, and `tasks/M4-practice.md`.
- Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md`; bridge requests go to Claude by handoff. Claude commits.

## Response — [recipient/session, UTC]
