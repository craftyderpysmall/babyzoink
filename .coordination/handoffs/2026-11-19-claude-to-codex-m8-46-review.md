# Handoff: review #46 (M8 human view bridge) and run its live acceptance tests

From: claude/m8-bridge-05
To: codex
Created: 2026-11-19
Status: pending

#46 is implemented in commit `c02f929`. It's documented in docs/PROTOCOL.md under "Implemented: M8 human view".

What's in it:
- **Resumable cursor:** step and step_seq share one execution cursor. The fast path is unchanged; watched slots run at 1x.
- **Hotkeys:** Ctrl+Alt+V and Ctrl+Alt+O, with independent registration and a 3-second retry hand-over between slots.
- **Shared state:** `gdbot/view.json`.
- **Launch session:** `gdbot-launch --session fresh|keep`. Fresh writes `mode.txt=dedicated` and turns the overlay on.
- **`set_overlay` op**, plus a two-column overlay drawn with GD's chatFont.
- **Fallback script:** `tools/view.ps1`.
- **`tools/m6/watch.py`** uses the bridge's own watch when it's available.
- **`solve_pool`** feeds Search and Budget lines to the overlay.

My live check: `tools/m8/view_smoke.py --slot 3` passed 6/6. Slot 3 is still running the new build.

**Uncommitted, deliberately: please commit-review with #50.**
- `gdbot/instances.py`: `launch(..., session=None|"fresh"|"keep")`. It's additive and sits on top of your in-progress #50 edits in the same file.
- `tools/m6/supervise.py`: every supervisor launch passes `session="keep"`, so a recycle never resets the user's choices.

Launchers from before M8 ignore unknown arguments, so the pinned #19 launcher is unaffected. I didn't commit `instances.py`, to avoid committing your half-finished #50 code.

Please do the plan's acceptance checks I haven't done (live, on a free slot, after checking RAM):
1. **Session tests:**
   - cold start (fresh writes the defaults);
   - single-slot supervisor recycle (keep preserves `mode.txt` and `view.json`);
   - a second slot joining;
   - the hotkey owner exiting: another slot takes over V, O and B within about 3 s (see the "hotkey ... registered" lines in each slot's bridge.log).
2. **Fast-path throughput** before and after (`tools/m7/perf_bench.py`). The old build is `mod/build/pinned-pre-cbf/`, the new one `mod/build/Release/`. Only noise-level differences are allowed.
3. **Trace parity** between a watched and a dedicated run on a couple of fixtures (`trace` on, `step`).
4. **Code review of the bridge diff:** `mod/src/control.cpp` (Exec / exec_advance / exec_pace_frame), `mod/src/view.cpp`, `injector/main.cpp`.

Record the results in the plan's review section or below, and set #46 accordingly.
