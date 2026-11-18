# Task: M3 recipe fix: imitation warm start, then PPO

Status: paused. The run was stopped by Claude Code because the laptop ran low on memory; it needs the user's OK to restart.
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
