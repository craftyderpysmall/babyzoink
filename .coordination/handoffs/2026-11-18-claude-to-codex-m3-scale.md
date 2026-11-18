# Handoff: M3 at scale, with seeds and a larger budget, to pick the encoder

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-18
Status: pending; starts after the diagnose item (queue #5) is done
Related: tasks/M3-baseline.md, handoffs/2026-11-18-claude-to-codex-m3-diagnose.md

## Request
Turn the provisional M3 result into a decision.
1. Apply any fixes from the diagnosis (cadence, input semantics, encoding).
2. Generate **new validation layouts** (at least 9, all families, fresh seeds) and keep the held-out set frozen.
3. Train both encoders with **3 model seeds each**. The budget is about 1M transitions per run. The first study ran 147k in about 4 min, so this is roughly 30 min per run. Cut the budget if the total would exceed about 4 h of wall time, and report the cut.
4. Report per encoder the mean ± spread over seeds of: held-out first-run progress, capped clears within 3 tries, attempts to first clear, and validation clears. Include learning curves at 25/50/75/100% of the budget.
5. Recommend one encoder for M4/M5, with the evidence. If it's still a tie, say so and recommend the cheaper one.

## Bridge update (2026-11-18, Claude)
**Completion is now tick-driven.** `terminal: "complete"` arrives on the tick the player crosses the level end, with no wall-clock wait. **Drop the 1.2 s finish wait.** It now arrives about 11 ticks *before* the `finish_wait` tick recorded in the drill tapes. The tapes' edges are still valid; only the finish tick moves earlier. Verified with `tools/m1/completion_test.py` on two drills.

## Files / claims
- Claim `RUNTIME:gd-2.2091` for the duration, plus your paths. Checkpoints stay under `build/` (gitignored).
- Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md`. Claude commits; you don't.

## Response — [recipient/session, UTC]
