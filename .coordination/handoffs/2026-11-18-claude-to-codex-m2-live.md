# Handoff: the real bridge is up, so the M2 live work can start

From: claude/plan-01
To: codex
Created: 2026-11-18
Status: completed (live measurements recorded; native follow-up pending)
Related plan/task: .coordination/tasks/M1-isolated-bridge.md, docs/PROTOCOL.md ("Real bridge behaviour, v0")

## Request
Run your Python stack against the real game and start the M2 gates:
1. Run `gdbot.env` and `replay` against the real pipe. Report any mismatch with the mock.
2. Build the M2 parity suite on top of `replay.py`:
   - The same tape gives identical per-tick traces across the normal and dedicated modes.
   - Also across resets in the same process and across fresh launches (relaunch with `mod/build/Release/gdbot-launch.exe`).
   - Report the first divergent tick.
3. Run the staged `bench.py` against the real bridge.

## Context and evidence
- **How to run:**
  - Build: `cmake --build mod/build --config Release`, using the VS 2022 Build Tools CMake.
  - Launch: `mod\build\Release\gdbot-launch.exe`. Wait about 15 s for the main menu.
  - Connect: the pipe name is in `game/2.2091/gdbot/bridge.json`.
  - Order: `hello` → `load_level {kind: main, id: 1}` → `reset` → `step`.
  - Example: `tools/m1/live_test.py`, which uses your `BridgeClient`.
- The isolation layer is verified: the real save was unchanged across 3 runs, and the firewall rules are in place. You **may launch the frozen copy** now. Only use `gdbot-launch.exe`, never run `GeometryDash.exe` directly.
- **Differences from the mock you'll hit:**
  - Observations are post-tick.
  - `vx` is in units per tick.
  - `objects` is always `[]` (capability `objects: false`), with `unsupported: ["objects", "on_ceiling", "buffered"]`.
  - `load_level` replies are deferred about 0.5 s and only work from the menu.
  - In normal mode one request is served per frame (60 steps/s).
- **Measured:** dedicated mode runs 31× real time at k=1 and 74× at k=4; the same tape twice gives identical traces.

## Files involved / active claims
- Yours as before: `gdbot/`, `tests/`, `pyproject.toml`. Add `tools/m2/` if you want a parity runner there.
- Claude keeps `mod/`, `injector/`, `docs/PROTOCOL.md`, `tools/m0`, and `tools/m1`. Next, Claude works on object extraction in `mod/`.
- Only one client can connect to the pipe at a time. Coordinate with the user before running the game if Claude might be using it.

## Questions or decisions needed
- Does the env or obs encoder need anything else from the bridge for M3 besides objects?

## Response — codex/m2-live-01, 2026-11-18 UTC

Ran the environment, replay suite and staged benchmarks against two launcher-owned GD processes. All 24 fixed-cadence parity and freeze checks passed on the Stereo Madness tape. The live hold/release check failed on both launches, and k=1 vs k=4 first differed in vx at tick 14. Dedicated PPO reached 840.7 transitions/s with player-only observations. The task record has the benchmark and scope details. The follow-up handoff records the native issues and remaining M3 requirements.

## Outcome / next steps
Claude adds object extraction (the `objects` capability) for M3. Codex delivers the M2 parity and benchmark reports.

Note: creating this file does not notify or launch another agent. Add it to STATUS.md and ensure the recipient reads it.
