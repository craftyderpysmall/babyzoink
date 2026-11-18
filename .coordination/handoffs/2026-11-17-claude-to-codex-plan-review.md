# Handoff: Critical review of GD learning bot plan

From: claude/plan-01
To: codex
Created: 2026-11-18T05:37Z
Status: completed
Related plan/task: .coordination/plans/2026-11-17-gd-learning-bot.md

## Request

Critically review the plan, review round 1. Test its assumptions, find risks, and suggest alternatives; don't just agree. Write your review in the plan's "Review round 1" section. Do not implement anything yet.

## Context and evidence

- The repo is empty except for the coordination scaffolding.
- The user made the main decisions in a Q&A with Claude:
  - Custom injected DLL, not Geode.
  - State-based observation, no pixels.
  - CPU only.
  - Curriculum plus few-shot held-out evaluation.
  - Both start positions and practice checkpoints.
  - Two run modes, dedicated and background.
  - GD 2.209.
- The user wants **up-to-date version info**. GD 2.209 released on 2026-10-15 and 2.2091 around 2026-10-18. Geode reportedly broke on 2.2091. Please re-verify this when you review.

## Files involved / active claims

- Edit only the plan file's review section. Claim it in CLAIMS.md first.

## Questions or decisions needed

Focus on:
1. How feasible it is to find function signatures/offsets for 2.209x without Geode bindings.
2. Whether the state-only observation design generalizes to unseen levels.
3. Whether lockstep stepping is deterministic with 240 tps physics.
4. Whether CPU throughput can reach ~10x real time.
5. The choice of SB3 PPO.
6. Whether levelgen is worth building.

Also see "Risks, assumptions, and open questions" in the plan.

## Response — codex/gd-review-01, 2026-11-18T05:40Z

The review was recorded in the plan's "Review round 1" section. (Claude noted this; Codex didn't update this handoff.)

## Outcome / next steps

After the review, Claude (or any agent) responds point by point in the plan. If agreement isn't reached after two rounds, the options go to the user.

Note: creating this file does not notify or launch another agent. Add it to STATUS.md and ensure the recipient reads it.
