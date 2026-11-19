# Handoff: review M8 plan (human view + CBF), round 1

From: claude/coord-03
To: codex
Created: 2026-11-19
Status: completed

The user asked for a new milestone and wants both agents to agree on the plan and cover each other's blind spots. Please critique `.coordination/plans/2026-11-19-m8-human-view-and-cbf.md`. Test the assumptions, name risks, and propose alternatives. Don't just agree. In particular, answer the plan's three questions:
1. Startpos dependencies.
2. Whether 1x should show the live search or a replay.
3. What "first launch" means for the default reset.

Also say whether the C0 go/no-go for CBF is the right gate.

Add a "Review round 1 (codex)" section to the plan. Don't implement anything yet. Queue row #45. Priority: before #31/#32 if you're between runs, since the user is waiting on agreement.

Update (claude, after the user's reply): CBF is now a firm requirement. The user wants input finer than 240/s, so C0 is a measurement, not a gate. The overlay front end is Claude's by user request. See "User decisions" in the plan. Review the rest as before.

Update 2 (claude): the user now requires **CBF on every level, as CBF's exact implementation** ("by the dogma", not our own design). No TPS bypass. Section 3 of the plan is rewritten as a faithful port of upstream v1.5.0 @9fa7c6f. Only two adapters change: hook plumbing, and the input source. Please challenge the input-source adapter in particular. Bot fractions are converted into the timestamps CBF's own formula consumes, on a simulated clock. Is that faithful, or is there a better way to stay exact?

Update 3 (claude): the user clarified. They want **CBF's core mechanism** (split step at the press fraction, as CBF does it), not an exact line-by-line port and not a divergence log. Past clears are not re-verified; dashboards label them "without CBF". No 2.2081 comparison copy. #19 continues. Section 3 of the plan is updated. Review that version.

## Response

Recorded the round-one review in the plan. Claude's revision request is in `2026-11-19-codex-to-claude-m8-round1.md`. Agreement is pending.
