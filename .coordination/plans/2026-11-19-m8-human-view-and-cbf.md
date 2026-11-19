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

### Decision (user, 2026-11-19): CBF on every level, CBF's exact implementation

- **Always on:** every level, every run (search, training, verification). There is no vanilla mode for results.
- **No TPS bypass.** CBF's own "Physics Bypass" option is off too, so the step count stays vanilla (`calculateStepCount(..., forceVanilla)` path).
- **"Exact implementation, by the dogma":** don't invent our own split-step. Port CBF's code faithfully.

### Why we can't load the unmodified mod (facts, not preference)

1. **Version:** CBF v1.5.0 (`mod.json`, upstream commit `9fa7c6f`) targets **GD 2.2081 with Geode 5.3.0**. Our bot copy is pinned at **2.2091**, and Geode support for 2.209x isn't confirmed. Moving to 2.2081 means redoing M0 (offsets) and needs the user's OK under the "stay on 2.2091" rule.
2. **Input source:** CBF timestamps *real input devices* on a raw-input thread. Its README says "does not work with bots". The bot's presses never reach that thread.
3. **Clock:** CBF places inputs by wall-clock time between frames (`input.m_timestamp - lastFrameTime`). The bot runs physics 50-100x faster than real time inside a single frame, so wall-clock timestamps don't mean anything for it.

### Plan: a faithful port of CBF v1.5.0 into the bridge

- **Pin:** upstream `theyareonit/Click-Between-Frames@9fa7c6f` (v1.5.0, MIT). Vendor `src/main.cpp`, `timestamp.hpp` and `includes.hpp` unmodified under `mod/third_party/cbf/` with its LICENSE, for reference and diffing.
- **Port line by line.** CBF's logic is copied as written:
  - `Step`/`EMPTY_STEP`, `stepQueue`, `buildStepQueue`, `popStepQueue`;
  - `calculateStepCount` (vanilla path);
  - the `processCommands` / `getModifiedDelta` step-queue hooks;
  - the `PlayerObject::update` split, with sub-step `update(stepDelta * deltaFactor)`, `updateRotation`, P2 handling, `midStep`/`inputThisStep`/`p1Split`;
  - the `m_lastPosition` fix-up hook;
  - `decomp_resetCollisionLog`;
  - the vanilla CBS/COS overrides.
- **Only two adapters change, each documented:**
  1. **Hook plumbing:** Geode `$modify` and `setHookPriority` become MinHook detours on the same functions. Each function's 2.2091 RVA and member offset is found and verified M0-style, against Geode's 2.2081 bindings as the reference.
  2. **Input source:** CBF's raw-input thread and timestamps become a bot input queue. For each bot press, we compute the timestamp CBF's own formula would turn into the requested step fraction (`timestamp = lastFrameTime + stepDelta * (i + f)`). We push it into CBF's own `inputVector`. Everything downstream is unchanged CBF code. The bridge's physics loop feeds CBF's `lastFrameTime`/`currentFrameTime` from simulated time, not the wall clock.
- **Port record:** `mod/src/cbf_port.md` maps every upstream function and line range to our code. Any unavoidable divergence (inlined functions, 2.2091 layout changes) is listed with its reason. Codex reviews the port against upstream line by line.
- **Validation:**
  - (a) Fraction 0 everywhere gives CBF's "input at step start" behaviour. Compare with real CBF semantics on drills.
  - (b) Invariant tests from CBF's design: an input at fraction f moves the jump start by f·stepDelta.
  - (c) Optional and strongest, needs the user's OK: a separate GD 2.2081 + Geode + real CBF copy. Drive identical inputs through both at real-time speed and compare player traces.
- **Consequence:**
  - Every existing verified result is vanilla-timed: Stereo Madness, Back on Track, Polargeist, 59/63 drills, all #19 data.
  - After the port, re-verify each under CBF. Tapes whose presses all sit at step starts may still replay; measure it.
  - Anything that doesn't replay is re-solved. #19 keeps running meanwhile: its prefixes seed the CBF re-solve.

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

- **CBF is required on every level, using CBF's exact implementation** (see section 3, Decision).
  - The user wants input finer than 240 per second. GD 2.2 physics stays at 240 steps/s, and CBF lets a press land at any fraction of a step.
  - **TPS bypass is ruled out by the user.**
  - The earlier C0-C4 phases (own reimplementation, measure-first gate, "prefer tick-grid clears") are **superseded**.
- **Overlay front end is Claude's,** not an open task: layout, look and contents. The user likes Claude's UI. The back end (data feed, set_overlay, Python side) can be either agent.

## Review history

- Round 1: requested from codex (handoff 2026-11-19-claude-to-codex-m8-plan-review.md).
