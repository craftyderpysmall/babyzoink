# Handoff: why do the simplest held-out drills fail? (single spike, double spike, yellow orb)

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-18
Status: pending
Related: tasks/M3-baseline.md (your first study), levels/drills/, tools/m3/

## Request
Both PPO agents cleared harder held-out drills (gravity, speed, moving geometry) but failed single spike and double spike at about 10% progress, and failed the yellow orb at about 27%. Find the cause before scaling up. Check in this order and stop when one explains it:
1. **Cadence:**
   - Quantise each verified tape to the k=4 decision grid (all four phase offsets) and replay it.
   - If no phase clears single/double spike or the orb, the policy *cannot* succeed at k=4. Report the minimum k that works.
2. **Orb input semantics:**
   - In a controlled trace, compare holding through the orb vs a fresh press while overlapping it vs a press just before entering it.
   - Record when GD actually triggers the orb.
   - If the policy needs "pressed this tick" rather than "held", or needs a buffered-input field, write a handoff to Claude with the exact bridge field you need (`buffered` is currently unsupported).
3. **Observation:**
   - Dump the policy's encoded observation for the held-out single spike at the ticks just before death, and compare with the train variant.
   - Look for distance or scale normalisation, truncation, or the spike being sorted out of top-K.
4. **Exploration and data:** if 1–3 are fine, show the train-variant learning curves for these families. Is the agent ever clearing the train single spike?

Write findings plus any minimal fix (Python side) in `tasks/M3-baseline.md` under a "Diagnosis" section. Re-run only the affected drills to confirm the fix.

## Files / claims
- Claim `RUNTIME:gd-2.2091` plus your paths. Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md`; send bridge needs to Claude by handoff.
- **Commits:** Claude commits and pushes the repo. Don't commit yourself. Leave your work in place and release your claims.

## Response — [recipient/session, UTC]
