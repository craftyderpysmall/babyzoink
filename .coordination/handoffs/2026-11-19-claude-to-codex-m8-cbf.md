# Handoff: M8 CBF is in the bridge. Review it, run the fixtures (#47), integrate it in the solver (#48)

From: claude/m8-bridge-05
To: codex
Created: 2026-11-19
Status: pending

The CBF bridge part is done in commit `a9a0a2c` (`mod/src/cbf.cpp`). It's documented in docs/PROTOCOL.md under "Implemented: M8 CBF".

The protocol:
- `step` takes `frac`; `step_seq` takes `fracs` with one value per action, each in [0, 1).
- A fraction applies to the first step of its decision when the held state changes.
- 0, or no fraction, behaves exactly as before.
- `reset` reports `input_timing`; vanilla Click Between Steps and Click On Steps are forced off.
- hello reports `capabilities.cbf`.

`tools/m8/cbf_smoke.py --slot 3` passed 7/7:
- exact parity on the verified Stereo Madness clear;
- bad fractions refused before physics moves;
- jump onset linear in f; f=0.5 is within 0.012 of the midpoint of the f=0 ticks.

Slot 3 runs this build. #19 stays pinned to `mod/build/pinned-pre-cbf/`.

## #47: review and fixtures (before any solver uses fractions for results)
1. **Code review:**
   - Review `mod/src/cbf.cpp` against upstream main.cpp L389-489 @9fa7c6f, and `mod/src/control.cpp` (`parse_fracs`, `cbf_arm`/`cbf_settle` in `exec_advance`).
   - Check the offsets in the file header. Two were found live by behaviour: `m_lastPosition` 0x4d0 and the collision logs at 0x5b0/0x5d0.
2. **Fixtures:** slope, orb (yellow and blue), wave, ship, moving platform and dual transition. For each, with f in {0, 0.25, 0.5, 0.75}:
   - no crash;
   - f=0 identical to a run without fracs;
   - the onset shift is monotonic where the player isn't buffering;
   - buffering states (airborne cube without a ring) behave as click-on-steps.
3. **Known gap:** `m_isDualMode` isn't mapped, so player 2 is never split. Map it if you can (GJGameState inside GJBaseGameLayer), and tell me the offset. I'll wire `p2Split`.

## #48 (Codex part): the solver
1. **Input timing records:** every new report and solution or resume record gets `input_timing: "cbf"`. A resume across the timing boundary refuses to continue (plan point 5). Old results are labelled `tick` ("without CBF") on the Site; not re-verified (user rule).
2. **Fractions at stalls:** use fractions where the tick grid fails, as in the plan's C3. The #31 evidence: at the Stageix stall, k=1 passed where k=4 never did. Most candidates keep f=0. A decision that changes the held state can get f in {0.25, 0.5, 0.75} when a segment has no surviving candidate.
3. **Rollout:** new CBF runs use the new bridge (`mod/build/Release`). #19 continues on the pinned build until it ends, or until the user says to migrate it.

Don't edit `mod/`. Bridge changes go through Claude.
