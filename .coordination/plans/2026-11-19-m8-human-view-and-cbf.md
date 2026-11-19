# Plan: M8, human view (hotkeys, overlay, launch defaults) and click-between-frames input

Proposer: claude/coord-03. Created 2026-11-19. Status: **proposed, awaiting Codex review round 1.**
Requested by the user (2026-11-19). The user asked both agents to agree and cover each other's blind spots.

## User requests (verbatim intent)

1. Start positions: since practice works, the user thinks we don't need startpos in future. Confirm.
2. Plan a CBF (Click Between Frames) implementation. The Geode mod is open source; our own implementation is fine.
3. Ctrl+Alt+B already exists. Add a hotkey to watch the game at **1x speed** for human eyes.
4. Add a hotkey to **show/hide an overlay**: current attempts, game speed, and other info useful to THE HUMAN USER.
5. **Defaults at first launch:** not in background mode, fastest speed, overlay shown.

## 1. Start positions: proposal = drop from the roadmap

- Practice checkpoints already give what startpos gave training: the solver and M4 practice restore any point that was reached.
- Startpos's one extra ability is starting a section the bot has never reached. The search teacher reaches it anyway.
- Keep the existing code (`with_startpos`, M4 drills) working, but don't extend it. Retire startpos-based curriculum ideas.
- **Question for Codex:** do M4 or M5 drills or the DAgger tooling depend on startpos in a way that would break if we stop maintaining it?

## 2. Human view

### Current state (checked in code)

- Ctrl+Alt+B is `RegisterHotKey` in `mod/src/control.cpp` (hotkey_thread). The choice persists in the shared `gdbot/mode.txt`; today the file says `auto`.
- `RegisterHotKey` is **system-wide**: only the first GD slot gets the key; the others log "unavailable". It works for all slots only because they share mode.txt.
- When no client is connected, the mode is `normal` (real time, 60 fps). Dedicated mode with draw-skip (`set_render` 1000 ms) draws about once a second.

### Proposed design

- **Hotkeys** (same owner model as B: whichever slot registers them writes shared state, and every slot polls it):
  - `Ctrl+Alt+B`: unchanged (dedicated ⇄ background).
  - `Ctrl+Alt+V`: **watch at 1x**. It toggles 1x for the slot whose window is in the foreground. If none is, it picks the lowest running slot. One watched slot at a time.
  - `Ctrl+Alt+O`: **overlay on/off** for all slots.
  - State lives in `gdbot/view.json`: `{"overlay": true, "watch_slot": null}`, written atomically. Mode stays in mode.txt for compatibility.
- **1x watch mode** (the hard part):
  - While watched, the bridge paces physics to 240 ticks per wall-clock second and draws every frame (draw-skip off for that slot).
  - The Python client sees no protocol change; requests just take real time.
  - **Engineering issue:** `step_seq` runs thousands of ticks inside one frame (one request, one frame). At 1x the bridge must yield between frames. Proposal: make step and step_seq resumable, like the existing deferred replies for load_level and quit_level: run up to `elapsed_wall_s * 240` ticks per frame, keep the cursor, reply when done.
  - Alternative: call `CCDirector::drawScene` inside the loop. Rejected: re-entrancy inside the scheduler update.
  - Watching a search shows rapid practice restores. The overlay labels each one ("evaluation 1,234 · restoring checkpoint").
  - **Question for Codex:** should 1x instead replay the current best prefix as a normal run (nicer to watch, costs a slot), or show the live search?
- **Overlay:** a cocos `CCLabelBMFont` node (GD's own font) on top of the running scene, refreshed at most 4 times a second, top-left, small, semi-transparent background. Lines:
  - slot · level name · job (e.g. "#19 M6 online")
  - mode: DEDICATED / BACKGROUND / WATCH 1x · speed: current ticks/s and "×N real time"
  - attempts: normal (full runs) · practice evaluations · this level's best % · current x / %
  - solver: segment, budget used / total, ETA if known
  - GD memory MB · system free MB
  - hotkey hints: "Ctrl+Alt+V watch · O overlay · B background"

  The bridge knows the mode, speed, x/% and episode counts. Python adds job, evaluations and budget through a new op, `set_overlay {"lines": {...}}` (strings only, length-capped, rendered as text). The overlay is drawn even on draw-skip frames: it draws with the scene, so it updates at the present rate.
- **Launch defaults (user rule):**
  - **Mode:** a freshly launched GD starts **dedicated** (fastest), never background, even if mode.txt says background.
  - **Overlay:** shown by default.
  - **Speed:** maximum at launch. Before a client connects there's nothing to run; once the client connects, dedicated applies.
  - **Conflict to resolve:** the supervisor relaunches slots every level and on memory caps. If "first launch" means every GD process, the user's background choice resets on every relaunch.
  - **Proposal:** at bridge init, if **no other bot slot is running**, reset mode.txt to `dedicated` and view.json to `{overlay: true}`. That's a new session. A relaunch while other slots run inherits the current choice.
  - **Question for Codex:** is that the right reading, or should a supervisor relaunch of the only slot keep the user's choice? A possible rule: keep the choice if mode.txt changed within the last 10 min.

## 3. CBF (click between frames)

### What CBF does (read from github.com/theyareonit/Click-Between-Frames, MIT, src/main.cpp)

- **Input capture:** a raw-input thread timestamps clicks with a high-resolution timer.
- **Step queue:** each frame, `buildStepQueue(stepCount)` places each input at a fraction of a physics step: `inputTime = fmod(t - lastFrameTime, stepDelta) / stepDelta`.
- **Split update:** a `PlayerObject::update` hook splits that step: `update(stepDelta * f)`, then `handleButton`, then the rest of the step. Rotation is split too (`updateRotation`), and `m_lastPosition` is patched at the end of the step loop. Player 2 is handled the same way.
- **Vanilla 2.2:** has "Click Between Steps" (CBS, limited to 480 TPS, about half a step) and "Click On Steps". CBF overrides both. Its README says "does not work with bots", because it reads real input devices.

### Decision (user, 2026-11-19, clarified): CBF on every level, same core mechanism as CBF

- **Always on:** every level, every run (search, training, verification). No TPS bypass, and no CBF "Physics Bypass" either: the step count stays vanilla.
- **"Same core mechanism",** not a line-by-line port. The user clarified: no copying upstream word for word and no divergence log. The mechanism must be CBF's:
  - a press lands at a fraction f of a physics step;
  - that step's player update is split into `update(stepDelta*f)`, then `handleButton`, then `update(stepDelta*(1-f))`;
  - rotation and last position are handled the way CBF does it;
  - the vanilla click-on-steps / click-between-steps flags are overridden.

  CBF (theyareonit/Click-Between-Frames v1.5.0, MIT) is the reference for those details and is credited. Its raw-input and timestamp machinery isn't needed: the bot names f directly.
- **Past results aren't re-verified.** Dashboards label every result made before CBF as "without CBF" (`input_timing: tick`). New results are `cbf`.
- **No 2.2081 + real-CBF comparison copy.** It was only needed to prove an exact port, which isn't the goal any more.

### Phases

- **C1, bridge (claude):**
  - hook `PlayerObject::update`; find and verify the 2.2091 RVAs for `updateRotation` and the collision-log reset;
  - add a per-step input with fraction f, plus the split and rotation/position handling following CBF;
  - **vanilla Click Between Steps and Click On Steps always OFF (user rule).** The bridge forces `m_clickBetweenSteps = false` and `m_clickOnSteps = false` on every PlayLayer init, as CBF does. It also sets them off in every slot's bot save settings, and `hello`/`reset` replies report both flags so tests can assert they're off;
  - always on.
- **C2, protocol:**
  - `step_seq` and `step` take an optional `fracs` array parallel to `actions`; a missing value means f=0 (start of step);
  - `hello` reports `capabilities.cbf`;
  - tests: f=0 matches a press at step start; jump onset moves by f·stepDelta.
- **C3, solver (codex):** keep the tick grid for most candidates. Where a segment has no surviving candidate, retry its presses at fractions (e.g. 0.25 / 0.5 / 0.75), guided by the #31 stall analysis.
- **C4, labels (both):** `input_timing` on every attempt and clear.
  - Everything before the switch is `tick` ("without CBF").
  - The Claude artifact (claude) and the ChatGPT Site (codex) show the label per level.

## Risks

- Resumable step/step_seq touches the bridge's hottest path. It needs a parity and throughput regression test (`tools/m7/perf_bench.py`) before and after.
- Overlay drawing must not run on skipped frames' visit path, or it has to be part of the scene. It also shouldn't cost the 7-9% draw-skip gain.
- Global hotkeys: another app may already own Ctrl+Alt+V or Ctrl+Alt+O. Log it, and fall back to `tools/view.ps1`.
- CBF split-step on 2.2091 needs offsets that CBF gets from Geode bindings. We have to find and verify them ourselves (M0-style).
- With CBS or CBF on, physics differ from vanilla, so tapes are only comparable within one input_timing.

## Proposed split (after agreement)

- **Claude:** all `mod/` work: hotkeys, view.json, launch defaults, overlay, resumable step/step_seq, set_overlay, C1 split-step, C2 protocol.
- **Codex:** C0 measurement, Python `set_overlay` feed from solve_pool/supervise/guided, `tools/view.ps1`, C3 solver refinement, C4 tagging plus Site display. Plus a review of every bridge PR.

## User decisions after the proposal (2026-11-19)

- **CBF is required on every level, with the same core mechanism as CBF** (not an exact port; see section 3, Decision).
  - The user wants input finer than 240 per second. GD 2.2 physics stays at 240 steps/s, and CBF lets a press land at any fraction of a step.
  - **TPS bypass is ruled out by the user.**
  - The earlier measure-first gate and "prefer tick-grid clears" are **superseded**.
- #19 keeps running for now (user OK).
- **Overlay front end is Claude's,** not an open task: layout, look and contents. The user likes Claude's UI. The back end (data feed, set_overlay, Python side) can be either agent.

## Review history

- Round 1: requested from codex (handoff 2026-11-19-claude-to-codex-m8-plan-review.md).
