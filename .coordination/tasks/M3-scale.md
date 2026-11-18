# Task: Select an encoder from the scaled M3 study

Status: done (results below)
Agent/session: codex/m3-scale-01
Related handoff: ../handoffs/2026-11-18-claude-to-codex-m3-scale.md

## Frozen protocol

- Run the sorted top-K and masked-set PPO encoders at seeds 1207, 2357, and 3907. For each paired seed both encoders follow the same four shuffled passes over the nine training drills. Each visit is 27,648 transitions, for 995,328 transitions per model and 5,971,968 total.
- Run on CPU with two Torch threads, dedicated game pacing, and k=4. All previously problematic held-out drills cleared on this cadence in the earlier phase tests. Use the latest bridge's tick-driven completion with no wall-clock finish wait.
- Verify the new buffered field live and through each policy encoder before training. Both encoders already include this feature in the shared player vector.
- Use nine new validation layouts at seeds 4100–4108, spanning every family. Freeze the existing held-out revisions. No optimizations or online practice use validation or held-out levels.
- Evaluate validation at 25%, 50%, 75%, and 100% of each budget. Evaluate held-out only at 100%. Each score uses a fixed deterministic first attempt plus up to two fixed-seed stochastic retries. Count failures at the three-attempt cap.

The runner is tools/m3/scale.py. Artifacts, per-attempt results, and resumable quarter checkpoints are under build/m3-scale/paired-study/. The report records the exact native bridge SHA-256 and each fixture's payload hash. The study resumes at a completed training quarter, with validation rerun if it was interrupted.

The active test game is the launcher-owned PID 25208. Its runner writes progress to build/m3-scale/paired-study/report.json after every training block. The launcher wrapper closes this game after the runner exits. All nine validation designs have a live k=4 completion witness, and the orb preflight confirmed that both encoders distinguish pending input at tick 1055. All 42 local tests passed.

The first 248,832-transition checkpoint took 349 seconds and scored all nine validation fixtures. That projects about 2.3 hours of training for the six runs before validation and final evaluation overhead, so the full transition budget is in use. Quarter two started from that checkpoint successfully.

The active shell session is 25025. While it runs, use report.json to follow completed quarters and keep the runtime claim. Once complete is true, verify all six runs and their four checkpoints, summarize the final metrics and validation curves, write the response and queue result, and release the claim after the owned game closes. If the process stops unexpectedly before completion, inspect its exit or logs before resuming the existing output directory from its last completed quarter.

## Results — finished 2026-11-18 14:40; written up by claude/plan-01 (Codex ran out of credits before the write-up)

The runner completed all 6 runs × 4 quarters (`report.json` `complete: true`); the game closed itself. Aggregated from `build/m3-scale/paired-study/report.json`.

**Held-out drills cleared within 3 tries, after 100% of the budget (out of 9):**

| Encoder | seed 1207 | seed 2357 | seed 3907 | mean | first-try clears (mean) | mean first-run progress |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| top-K | 4 | 4 | 0 | 2.7 | 2.3 | 44.3% |
| masked set | 4 | 2 | 3 | 3.0 | 1.0 | 27.7% |

**Validation clears within 3 tries, at 25 / 50 / 75 / 100% of the budget:**

| Run | 25% | 50% | 75% | 100% |
| --- | --- | --- | --- | --- |
| top-K 1207 | 3 | 5 | 3 | 3 |
| top-K 2357 | 5 | 3 | 0 | 3 |
| top-K 3907 | 4 | 3 | 0 | 0 |
| set 1207 | 3 | 3 | 3 | 3 |
| set 2357 | 1 | 3 | 3 | 4 |
| set 3907 | 3 | 3 | 5 | 2 |

**Findings**
- **More training did not help.** The 1M-transition runs are no better than the first 147k-transition study, which scored 4/9 for both encoders. Validation scores swing between quarters, with no upward trend.
- **Some runs collapse.** Top-K seed 3907 ended at 0/9 on both validation and held-out. Set seeds 2357 and 3907 fell to about 20% first-run progress by the end.
- **There's a ceiling around 3/9.** The same easier families clear each time; the timing-heavy spike families mostly don't. Phase tests showed all of these are solvable at k=4, so this isn't a cadence limit.

**Recommendation:** the encoder choice is effectively a tie. Take **top-K provisionally**: it's simpler and cheaper, with better first-try and first-run numbers. The bottleneck is the **training recipe**, not the encoder: PPO isn't turning more experience into better timing, and it's unstable. Next steps, in this order:
1. **Imitation warm start** from the 18 verified completion tapes (behaviour cloning on the train variants only), then PPO fine-tuning.
2. **M4 practice:** drill death hotspots from checkpoints instead of always restarting from 0%.
3. **Stability:** lower learning rate / clip range, more entropy early, observation normalisation checks, and a per-family curriculum.
