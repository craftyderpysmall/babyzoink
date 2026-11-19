# Handoff: the M5c solver stalls on Dry Out at x≈1,370 (addendum to #17)

From: claude/plan-01
To: codex
Created: 2026-11-19
Status: pending (part of #17 item 2)

- **Results so far:** Back on Track is verified (4,817 decisions, 1 drift), so Stereo Madness, Back on Track and Polargeist are solved. Base After Base is running in Claude's slot-0 solver now.
- **Dry Out (main:4) stalls:** about 56,000 evaluations at segment 33 (x≈1,371) with **no drift**, so it isn't a restore problem. Every candidate for the next segments dies, and backtracking hasn't found a fix. Progress is saved in `build/m5c/main_4.progress.json` (33 segments, 56,202 evaluations). Claude stopped it.
- **Hypotheses to check, cheapest first:**
  1. **What's there:** load Dry Out, replay the saved prefix (`committed` in the progress file) and call the bridge `snapshot` op to see the obstacle. Also check the exported objects there with the `objects` field of a `step` reply.
  2. **Timing resolution:** the obstacle may need a press window narrower than 4 ticks. Try the solver with `--k`-style finer decisions (add a K option; the bridge's `step_seq` already takes `k`), or with a phase offset.
  3. **Candidate set:** the obstacle may need a press/hold pattern the segment candidates or the 28-decision follow-ups don't contain. Examples: a long hold with a late release, or an orb pressed mid-air right after a pad.
  4. **Backtrack depth:** the fatal choice may be more than about 12 segments back. Raise `KEEP_CHECKPOINTS`, or let the search back up further before giving up.
- Fix it, then resume `--level main:4` (it reuses the progress file).
