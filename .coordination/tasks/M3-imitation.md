# Task: M3 recipe fix: imitation warm start, then PPO

Status: done (restarted after the low-memory stop and completed 2026-11-18)
Agent/session: claude/plan-01 (Codex out of credits)
Related handoff: ../handoffs/2026-11-18-claude-to-codex-m3-imitation.md
Runner: tools/m3/imitation.py, output in build/m3-imitation/ (report.json, topk-1207-bc.zip)

## Done so far
- **Demonstrations:** all 9 train-drill tapes replay to completion on the policy's own k=4 grid (phase 0). That gives about 8,850 decisions with 2–6 presses per drill. No validation or held-out tapes were used.
- **Behaviour cloning, seed 1207:** 60 epochs, class-balanced cross-entropy. Final accuracy is 97.5% and recall on the rare presses is 100%.
- **BC-only results, seed 1207** (frozen protocol, 3-attempt cap):
  - **held-out: 6/9 cleared, all on the first try.** Single spike, double spike, yellow orb, gravity, speed and moving geometry. Every PPO run had failed single/double spike and the orb.
  - validation: 5/9 cleared, all first try.
  - not cleared: triple spike (about 12%), block steps (39–69%), pillar gaps (about 26%).
  - For comparison, the scaled PPO study had held-out clears within 3 tries of top-K 4/4/0 and set 4/2/3.

## Where it stopped
- The PPO fine-tune of seed 1207 had reached 138,240 of 248,832 transitions. It isn't checkpointed mid-way, so that is lost.
- Seeds 2357 and 3907 have not started.
- **Resume:** relaunch GD and rerun the same command. The runner re-collects the demos (deterministic), skips nothing already scored for the finished BC evaluation, and restarts seed 1207 from BC.
- **Memory:** about 3 GB free of 13.8 GB with GD closed. Close other heavy apps first (ChatGPT desktop, Chrome, Steam).

## Final results (complete run, 3 seeds, top-K encoder, frozen protocol)

| | held-out clears within 3 tries (1207 / 2357 / 3907) | mean | first-try mean | first-run progress |
| --- | --- | ---: | ---: | ---: |
| **BC only** | 6 / 7 / 6 | **6.3/9** | 6.0/9 | 73.1% |
| BC → PPO (lr 1e-4, clip 0.1, 249k transitions) | 6 / 5 / 2 | 4.3/9 | 4.3/9 | 57.7% |
| Scaled PPO baseline (tasks/M3-scale.md) | 4 / 4 / 0 | 2.7/9 | 2.3/9 | 44.3% |

Validation, BC only: 6/9, 7/9, 6/9 (BC → PPO: 5, 6, 0).

**Findings**
- **Imitation from 9 train-drill demos more than doubles the held-out clear rate**, and it is stable across seeds. It solves single spike, double spike and yellow orb on every seed; every PPO run had failed those.
- **PPO fine-tuning hurts.** It erodes the cloned timing; seed 3907 fell from 6/9 to 2/9 held-out and 0/9 validation.
- **Triple spike is never cleared** by any agent (about 12% first-run progress). It's a systematic gap; check its demo vs held-out spacing, and whether three presses in a row need history or buffered handling.
- Block steps and pillar gaps clear for some seeds only.

**Recommendation:** imitation becomes the default recipe. Drop PPO fine-tuning in this form. Improve through more demonstrations instead: **self-imitation**, where clears the agent itself achieves (full runs or checkpoint-drilled sections) are added to the demo set, plus DAgger-style relabelling near death points. M4's practice curriculum (queue #7) should build on that.
