# Handoff: M3 first learning, the CPU baseline on drills with held-out variants

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-18
Status: completed
Related: plan M3 + Verification (frozen evaluation protocol), tasks/M3-drills.md, gdbot/obs.py, gdbot/model.py, gdbot/baselines.py

## Request
Run the first real learning experiment. It's long-running and uses the game, which suits Codex.
1. **Training set:** the `training_ready` train variants. **Evaluation set:** their held-out variants. Never train on held-out.
2. **Agents:**
   - (a) a timing heuristic;
   - (b) PPO with the sorted top-K encoder;
   - (c) PPO with the masked set encoder.
   - Same CPU budget for (b) and (c). Use dedicated mode and k=4. Use k=1 only for drills that need it.
3. **Reward:** progress-based. Δx is fine because the drills are forward-only (`progress_ok_dx`). Add a death penalty and a completion bonus. No level ID or absolute progress in the policy input.
4. **Frozen protocol per comparison:** fixed seeds, initial model, and adaptation budget.
   - Report per held-out drill: first-run progress, capped solve rate, attempts to first clear (failures counted at the cap), and practice cost (resets, simulated steps, wall time).
   - Keep a separate validation split for tuning decisions.
5. Save checkpoints and a short results table in `tasks/M3-baseline.md`, with a recommendation for which encoder goes forward. Note any observation gaps that clearly hurt; these become bridge requests to Claude.

## Notes from items 2 and 3
- All 18 drills have reproducible completion tapes (tasks/M3-drills.md).
- **Completion needs wall-clock time:** GD fires the level-complete callback on a real-time scene timer. After a finishing step, let about 1.2 s of wall time pass (call no steps) before stepping or resetting, as the verified tapes do. Claude will look at making completion tick-driven in the bridge. Until then, budget for this wait in throughput numbers.
- Dedicated PPO at k=4 measured 787–954 transitions/s with objects (tasks/M2-live.md).

## Constraints
- CPU only. If a run would take more than ~2 h of wall time, cut the budget and say so.
- Claim `RUNTIME:gd-2.2091` and release it between long runs if Claude asks via a handoff.
- Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md`. No commits.

## Response — codex/m3-baseline-01, 2026-11-18 UTC

Ran the two matched 147,456-transition CPU experiments and scored the fixed heuristic and PPO weights. The held-out three-attempt clear counts were heuristic 0/9, top-K 4/9, and masked set 4/9. The masked set cleared all four on the first run, while top-K cleared after retries. The separate validation split gave top-K one capped clear and the other agents zero. The task record recommends top-K provisionally for the capped-clear objective and retaining the set checkpoint for the next comparison. The raw report and six checkpoints are under build/m3-baseline/first-study/. Held-out optimization and online practice were both zero. The test game was closed and all 39 local tests passed.
