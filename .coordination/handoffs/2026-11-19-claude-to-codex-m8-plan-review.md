# Handoff: review M8 plan (human view + CBF), round 1

From: claude/coord-03
To: codex
Created: 2026-11-19
Status: pending

The user asked for a new milestone and wants both agents to agree on the plan and cover each other's blind spots. Please critique `.coordination/plans/2026-11-19-m8-human-view-and-cbf.md`. Test the assumptions, name risks, and propose alternatives. Don't just agree. In particular, answer the plan's three questions:
1. Startpos dependencies.
2. Whether 1x should show the live search or a replay.
3. What "first launch" means for the default reset.

Also say whether the C0 go/no-go for CBF is the right gate.

Add a "Review round 1 (codex)" section to the plan. Don't implement anything yet. Queue row #45. Priority: before #31/#32 if you're between runs, since the user is waiting on agreement.

Update (claude, after the user's reply): CBF is now a firm requirement. The user wants input finer than 240/s, so C0 is a measurement, not a gate. The overlay front end is Claude's by user request. See "User decisions" in the plan. Review the rest as before.
