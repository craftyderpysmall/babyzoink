# Handoff: fix the training recipe with an imitation warm start, then PPO

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-18
Status: pending
Related: tasks/M3-scale.md (results + diagnosis), levels/drills/tapes/, tools/m3/scale.py

## Why
The scaled study found that more PPO training did not help. Held-out clears were about 3/9, validation swung between quarters, and some runs collapsed. Phase tests show every drill is solvable at k=4. So the agent isn't learning the timing, and the fix is the training recipe, not the encoder. Use **top-K** (the provisional pick).

## Request
1. **Behaviour cloning:**
   - Replay each **train** drill's verified tape through the live bridge (k=4, the tape's edges quantised to the decision grid, phase 0, which Codex already showed clears).
   - Record (encoded observation, action) pairs. Never use validation or held-out tapes.
   - Train the policy network supervised. Report the train accuracy, and the clear rate when it is replayed deterministically on train drills.
2. **PPO fine-tune from the BC weights:**
   - Use a smaller learning rate and clip range, plus a KL or BC-loss anchor so it doesn't forget, at the same budget as one quarter of the scaled study.
   - Track validation every 25%.
3. **Compare under the frozen M3 protocol** (same validation layouts 4100–4108 and held-out revisions; 3 seeds if time allows):
   - (a) BC only;
   - (b) BC → PPO;
   - (c) the scaled study's top-K numbers as the baseline.
   - Report held-out clears within 3 tries, first-try clears, first-run progress, and stability across quarters.
4. Write `tasks/M3-imitation.md` with a recommendation. If BC → PPO is clearly better, it becomes the default recipe for M4's practice curriculum (queue #7).

## Constraints
- CPU only. Keep total wall time under about 3 h; cut the seeds first and report the cut.
- Claim `RUNTIME:gd-2.2091` plus `gdbot/`, `tools/m3/`, `tests/`, and the task file. Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md`. Claude commits.
- If you run out of budget mid-study, leave the runner resumable and write a short "where it stands" note in the task file (like `tasks/M3-scale.md` did), so Claude can pick it up.

## Response — [recipient/session, UTC]
