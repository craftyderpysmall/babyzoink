# M5c search-based teacher (expert iteration)

Status: in progress (claude/plan-01).

## Why
- M5b showed that behaviour cloning from 27 drill tapes doesn't transfer to real levels: official 2–8%, online 0/10.
- Self-imitation can't bootstrap, because local practice search rarely finds a working section.
- GD in lockstep is deterministic, and bot checkpoints restore exactly. So a search can find clears of real levels with no human input. Those clears then become the demonstrations.

## Solver (`tools/m5c/solver.py`)
- **Segment search:** depth-first search over segments of 8 decisions (k=4) on the bridge checkpoint stack (create = push, reset = restore newest, pop = backtrack).
- **Candidates per segment:** about 74 patterns, in order: keep the current input, flip it, short taps, then longer holds.
- **Acceptance:** a segment is accepted when some simple follow-up survives a 28-decision lookahead. The follow-ups are nothing, a single tap at any point, hold, or alternate. The lookahead must outlast a cube jump's airtime (~26 decisions), or "not yet" looks viable when it is already too late. A 10-decision lookahead needed 1,200+ evaluations per triple-spike group and ran out of budget.
- **Bridge support:** the new `step_seq` op returns only the outcome of a whole action list.
- **Verification:** every solution is replayed from a clean 0% run (practice off). Only verified clears count.

## Results so far
| Level | Evaluations | Search ticks | Verified from 0% |
| --- | ---: | ---: | --- |
| triple-spike train-1102 | 835 | 93,012 | yes |
| triple-spike heldout-2102 (never cleared by any learned policy) | 1,567 | 157,323 | yes |
| pillar-gaps heldout-2104 | 255 | 34,826 | yes |
| gravity-portal heldout-2106 | 168 | 26,631 | yes |

**Stereo Madness was solved** (verified from 0%): 21,161 evaluations, about 1.7M search ticks, and 45 re-anchors that caught 3 drifts.

## Checkpoint restore exactness (`tools/m5c/restore_probe.py`)
Probe method: walk the verified Stereo Madness clear. At each released segment boundary, checkpoint, run the next segment, restore, run it again, and compare the full player state.
- **Restore then press immediately:** 36/197 probes mismatched. There were 26 `buffered` mismatches (an immediate press after a restore is queued as a buffered jump) and 10 vy/y/rot mismatches in the ship section.
- **One released warm-up decision replayed between restore and segment:** 0/107 mismatched.
- **Solver changes:**
  - Checkpoints are created one decision before a boundary, only where that decision is a release, and every evaluation replays it first.
  - Depth 0 uses a clean reset instead of a checkpoint.
  - Re-anchoring stays as a backstop. A drift now excludes a window of 4 restore points at once.
  - A replay that dies stops immediately, because practice mode respawns the player.
- **Effect on Polargeist:** without the warm-up, it drifted at segment 13 and looped. With it, there was no drift until segment 373 (x≈15,500).
- The Back on Track run (pre-warm-up) stalled at x≈13,300. A likely contributor is inexact restores making real paths look fatal. Rerunning.

## Next
1. Turn verified solutions into demonstrations by replaying them through the env with the route encoder. Re-clone (expert iteration): search solves the train levels → BC learns → evaluate zero-shot on held-out (drills, then the frozen online set).
2. Policy-guided search: order segment candidates by the cloned policy's action probabilities, and measure evaluations per level as generations improve. Fewer evaluations is the "fewer attempts on harder levels" metric.
