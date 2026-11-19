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

Official levels 1–5: running.

## Next
1. Turn verified solutions into demonstrations by replaying them through the env with the route encoder. Re-clone (expert iteration): search solves the train levels → BC learns → evaluate zero-shot on held-out (drills, then the frozen online set).
2. Policy-guided search: order segment candidates by the cloned policy's action probabilities, and measure evaluations per level as generations improve. Fewer evaluations is the "fewer attempts on harder levels" metric.
