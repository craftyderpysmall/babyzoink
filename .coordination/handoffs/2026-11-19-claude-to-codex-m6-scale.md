# Handoff: next milestones: finish the open addenda, then M6 (search-teacher data at scale), DAgger, and the "fewer attempts" curve

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: pending
Related: handoffs/2026-11-19-claude-to-codex-site-performance.md, handoffs/2026-11-19-claude-to-codex-dryout.md, tasks/M5c-search-teacher.md, build/m5c-expert/

## Why
Your #17 results tell us what's next:
- **Triple spike:** one search-teacher demo of its train layout took held-out triple spike from 10% to a clear. Search demos work on the content they cover.
- **Online levels:** three official clears moved the frozen online set only from 4.8% to 5.1%. That's far too little data to generalize.

So the bottleneck is **coverage**: how many and how varied the solved levels are. A second bottleneck is **distribution shift**. Cloning only expert trajectories never shows the policy how to recover from its own mistakes.

## Work, in order (each a unit; keep task records current)

### A. Finish the two open addenda (small)
1. **`handoffs/2026-11-19-claude-to-codex-site-performance.md`:** the user asked for the per-mode performance summary on the site's front page, as frontend placeholders now. Redeploy to https://babyzoink.craftyderpysmall.chatgpt.site.
2. **`handoffs/2026-11-19-claude-to-codex-dryout.md`:** the solver stalls on Dry Out at x≈1,370; diagnose and fix it. Base After Base is being solved by Claude in slot 0; check `build/m5c/main_5.json` and CLAIMS before touching it.

### B. M6: search-teacher data at scale (the main milestone)
1. **Training pool (record it in `tasks/M6-scale.md`):**
   - ~60 downloaded online levels at Easy–Insane non-demon, plus later easy demons. They must be **disjoint from the frozen 10 held-out** and spread across modes, eras and lengths. Use `python -m gdbot.levels.online`.
   - Plus every drill variant you can generate (all 18 families; more seeds per family).
2. **Solve them** with `tools/m5c/solver.py` across parallel slots (1–3), as RAM allows. Check free memory before each extra slot; the machine has 13.8 GB and a run was killed at 2.2 GB free.
   - Track solve rate, evaluations and wall time per level.
   - Fix solver gaps as they show up. Dry Out shows there are some: finer `k`, wider candidates, deeper backtracking.
3. **Expert iteration with a scaling curve:** clone on 10, 20, 40 and all solved training levels (same seed, then 3 seeds). Score zero-shot on the frozen online held-out and on official 1–5. **The headline result is held-out first-run progress and clears vs number of solved training levels.**
4. **Log everything:** attempts in the ledger, section telemetry for the mode ratings, and `docs/progress.json` rows.

### C. DAgger with the search teacher (distribution shift)
- Run the cloned policy on training levels. Wherever it dies, or every N decisions, label the states it actually visits with the teacher's action: restore a checkpoint there (with the warm-up rule) and use the solver's first committed input from that state.
- Aggregate those labels and re-clone. Compare against plain expert iteration at equal teacher cost.

### D. The "fewer attempts" curve (the project's core claim)
- **Policy-guided search:** order the solver's segment candidates by the cloned policy's action probabilities.
- For each generation, solve a fixed set of **new** levels and record the search evaluations (practice attempts) and normal attempts needed to the first clear.
- The claim holds if evaluations per level fall across generations on unseen levels.
- Put the curve on the site's placeholder chart and in the attempts ledger.

## Constraints
- **Coordination:** you coordinate and commit while Claude is away. Pull with `git pull --rebase --autostash` first; single branch `main`.
- **Game slots:** claim `RUNTIME:gd-2.2091/slot<N>` per slot. Slot 0 is Claude's until its claim is released.
- **Resumability:** keep every long runner resumable.
- **Data use:** held-out levels never supply demos or selection.

## Response — [recipient/session, UTC]
