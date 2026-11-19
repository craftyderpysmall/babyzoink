# Bridge protocol (mod ⇄ Python)

Protocol version: **0** (draft). Owner: claude/plan-01. Changes: open a handoff. Any change to message shapes bumps the version.

Version 0 is deliberately simple: length-prefixed JSON. M2 benchmarks will show whether serialization dominates. If it does, version 1 adds a compact fixed-width binary observation block (planned below). Neither side may assume field order.

## Transport
- **Pipe:** a Windows named pipe `\\.\pipe\gdbot-<pid>`, where `<pid>` is the GD process id. The bridge is the server and accepts one client.
- **Discovery:** the bridge also writes `game/2.2091/gdbot/bridge.json` = `{"pipe": "...", "pid": n, "proto": 0}`. This assumes save redirection puts the bot's data under the game folder.
- **Framing:** `u32 little-endian length` + `length` bytes of UTF-8 JSON. One request gets exactly one reply, strictly alternating.
- **Request shape:** `{"op": "<name>", "id": <int>, ...}`.
- **Reply shape:** `{"id": <same>, "ok": true, ...}` or `{"id": <same>, "ok": false, "error": {"code": "<CODE>", "msg": "..."}}`.
- **Error codes:**
  - `BAD_REQUEST`
  - `UNKNOWN_OP`
  - `NOT_IN_LEVEL`
  - `UNSUPPORTED` (a capability is disabled, e.g. a live check failed)
  - `BUILD_MISMATCH` (sent once, as the hello reply, then the pipe closes)
  - `EPISODE_MISMATCH`
  - `INTERNAL`

## Physics freeze guarantee
Between replies, while it waits for a `step`, the bridge does **not** advance gameplay ticks. Render and UI may keep running.

The bridge runs requests on the game thread. The pipe thread only moves bytes.

## Ticks and stepping
- A *tick* is one completed physics step at 240 tps: one `processCommands` call with `isLastTick` semantics, to be confirmed in M1.
- `tick` counts completed ticks since the last reset, starting at 0.
- `step{action, k}` works as follows:
  - It applies the input edge (if the action differs from the currently held state) **at the start** of the first tick.
  - It advances exactly `k` ticks, or stops early at the first tick that produces a terminal event.
  - It returns the **post-step** observation.
  - `k` ≥ 1, and the bridge must support `k = 1`.

## Operations

### `hello`
- **Request:** `{"op": "hello", "id": 1, "proto": 0, "client": "gdbot/0.x"}`
- **Reply:**
  ```json
  {"id": 1, "ok": true, "proto": 0,
   "build": {"exe_sha256": "...", "game_version": "2.2091"},
   "capabilities": {"step": true, "reset": true, "startpos": false, "checkpoint": false,
                    "trace": false, "modes": ["normal"], "dual": false, "isolation": true},
   "isolation": {"saves_redirected": true, "http_blocked": true}}
  ```
- **Isolation rule:** if `isolation.saves_redirected` or `isolation.http_blocked` is false, the client must refuse to play.
- **Capabilities** become true only after the matching M1/M4 live checks pass.

### `load_level`
- **Request:** `{"op": "load_level", "id": n, "level": {"kind": "main", "id": 1}}`
- **`kind` values:**
  - `main`: an official level by id.
  - `local`: a local editor level, identified by `name`.
  - `cached`: a downloaded level, by id.
  - `level_string`: an inline level string (reserved, levelgen).
- **Reply:** `{"ok": true, "level": {"kind", "id", "name", "length_x": float, "revision": "..."}}`

### `reset`
- **Request:** `{"op": "reset", "id": n, "start": {"kind": "zero"}}`
- **`start` values:**
  - `{"kind": "startpos", "x": float, "mode": "cube", "speed": 1, "gravity_flipped": false, "mini": false}` (M4)
  - `{"kind": "checkpoint", "checkpoint_id": int}` (M4)
- **Reply:** `{"ok": true, "episode": int, "tick": 0, "obs": OBS}`
- The episode id increments on every reset. The action state resets to released.

### `step`
- **Request:** `{"op": "step", "id": n, "episode": int, "action": 0|1, "k": int}`
- **Reply:** `{"ok": true, "episode": int, "tick": int, "ticks_advanced": int, "obs": OBS, "events": [EVENT...], "terminal": null | "death" | "complete"}`
- **`EVENT`** = `{"type": "death" | "complete" | "mode_change" | "checkpoint" | "trigger", "tick": int, ...}`
- `step` with a stale `episode` returns `EPISODE_MISMATCH`.

### `set_mode`
- **Request:** `{"op": "set_mode", "id": n, "mode": "normal" | "dedicated" | "background"}`
- `normal` means real time with full rendering. It's used for parity baselines and for watching.
- The mode changes pacing and rendering only, **never** simulation results. M2 parity tests enforce this.

### `trace`
- **Request:** `{"op": "trace", "id": n, "enabled": bool}`
- While enabled, each `step` reply adds `"trace": [TRACE_ROW per advanced tick]`.
- **`TRACE_ROW`** = `{"tick", "players": [PLAYER], "button": {"held": bool, "queued": int}, "events": [...]}`
- This feeds the M2 parity suite. Rows must contain everything the suite compares.

### `bye`
- **Request:** `{"op": "bye", "id": n}`. The bridge releases input and closes the pipe.

## OBS (v0)
```json
{
  "players": [PLAYER],
  "objects": [OBJECT],
  "progress": 0.0,
  "window": {"ahead_x": float, "behind_x": float, "max_objects": int, "truncated": bool},
  "unsupported": ["<mechanic names present in the window that the bridge can't encode>"]
}
```
- `players` has one entry, or two in dual mode once `capabilities.dual` is true.
- `progress` is the game's own verified level progress, 0..1. It is **not** a policy input; it's for reward and metrics only.

PLAYER:
```json
{"x": float, "y": float, "vx": float, "vy": float, "rot": float,
 "mode": "cube|ship|ball|ufo|wave|robot|spider|swing",
 "speed": float, "gravity_flipped": bool, "mini": bool,
 "on_ground": bool, "on_ceiling": bool, "holding": bool, "buffered": bool,
 "dashing": bool, "dead": bool}
```

OBJECT, in gameplay coordinates and taken from collision data:
```json
{"uid": int, "cat": CAT, "type_id": int,
 "x": float, "y": float, "w": float, "h": float, "rot": float,
 "active": bool, "params": {}}
```
- **`CAT` values:** `solid`, `hazard`, `orb`, `pad`, `portal_mode`, `portal_gravity`, `portal_size`, `portal_speed`, `portal_dual`, `portal_teleport`, `other`.
- **`params`** depend on the category. Examples: orb `{"kind": "yellow|pink|red|blue|green|black|dash_green|dash_pink|spider|toggle"}`, portal_mode `{"to": "ship"}`, portal_speed `{"to": 0.5|1|2|3|4}`.
- **`uid`** is stable for the object's lifetime within an episode. Python uses it to derive per-object velocity from consecutive observations.
- **Coordinates** are absolute gameplay coordinates. Python makes them relative to the player. The bridge doesn't, so traces stay simple.

## Real bridge behaviour, v0 (measured 2026-11-18)
These clarifications are additive. Clients written to the text above stay compatible.

- **Observations are post-tick.** On the tick a cube jump is pressed, the game sets `vy` = 11.18 and applies one tick of gravity (−0.216) before the observation is read, so the first `vy` the client sees is 10.964.
- **Units:**
  - `x` and `y` are game units, updated every tick (the CCNode position).
  - `vx` is game units **per tick**, computed by the bridge from consecutive observations. It is 1.2982 at 1x speed.
  - `vy` is the game's internal `m_yVelocity`.
- **`hello.capabilities.objects`:** a new boolean, currently `false`. While false, `obs.objects` is `[]` and `obs.unsupported` contains `"objects"`. `on_ceiling` and `buffered` are always false and are listed in `unsupported` because those fields are not mapped yet.
- **`load_level`:** only `kind: "main"` works, and only from the menu (not while already in a level). The reply is deferred until the level has rendered about 30 frames. `name` and `length_x` are `null`.
- **`reset`:** only `start.kind: "zero"` works. `startpos` and `checkpoint` return `UNSUPPORTED` until M4.
- **Control:** a client owns the game from `hello` until disconnect or `bye`. While it does:
  - Physics advances only inside `step`.
  - Game-initiated resets (respawn after death) and pause-on-focus-loss are suppressed.
  - On disconnect, the button is released and the game runs normally again.
- **Pacing:**
  - `normal` and `background` serve one request per rendered frame, measured at 60 steps/s while the game window was unfocused.
  - `dedicated` serves requests back to back for up to 12 ms per frame. Measured with Python as the client: k=1 at 7,546 ticks/s (31× real time), k=4 at 17,838 ticks/s (74×).
  - `background` also lowers the process priority.
- **Trace:** one row per physics tick. In the M1 test, the same 468-step input tape played twice from a reset gave identical traces (405 rows, ending in death).

## v0 additions (implemented and verified live 2026-11-18; additive, no version bump)
- `hello.capabilities` gains `objects`, `level_string`, and `quit_level` (all true).
- `level.revision` for level_string loads is `fnv1a64:<hex>` of `data`. Clients keep their own sha256 for tapes.
- `obs.objects` filters out GD's hidden anticheat spike. Its layer offset is learned on the first ticks after the first reset in a process, so only that very first reset may still list it at x=0.
- `obs.window` is 150 behind to 1200 ahead, with at most 128 objects (`truncated` is set when cut). Object `x`/`y` is the hitbox centre and `w`/`h` the hitbox size, from `GameObject::getObjectRect()`.
- **`terminal: "complete"` is tick-driven** (from 2026-11-18): it fires on the tick the player crosses the level end (`PlayLayer::playEndAnimationToPos`), deterministically and with no wall-clock wait. That's a few ticks before GD's own `levelComplete`, which arrives later on a real-time timer; under bot control a stale one is suppressed after a reset.
- **`players[].buffered`** (from 2026-11-18) is GD's `m_stateJumpBuffered`. It is true after a *fresh* press while the button is held, cleared on release, and consumed when a jump or orb fires. A hold that started earlier (e.g. at takeoff) does **not** set it. This is what distinguishes "will hit the orb" from "holding through it". It has been removed from `unsupported`.
- **`debug_peek {target: "player1"|"layer", off, len<=4096}`** is dev-only. It returns `hex` raw memory plus `tick`, for field mapping (`capabilities.debug_peek`).
- **Practice (M4; verified live 2026-11-18, `tools/m1/checkpoint_test.py` 8/8, including restore parity: a checkpoint suffix matched the continuous run on all 2,236 ticks through completion):**
  - `set_practice {enabled}` → `{practice}`.
  - `checkpoint_create` → `{checkpoint_id, tick, x, count}`. It needs practice on and the player alive.
  - `checkpoint_pop` → `{removed, count}`.
  - `reset {start: {kind: "checkpoint", checkpoint_id?}}` restores the **newest** bot checkpoint. An older id returns UNSUPPORTED; pop first.
  - `reset {kind: "zero"}` turns practice off, so a full run is always clean from 0%.
  - While a client is in control, GD's practice auto-checkpoints are blocked, so "newest" means the bot's own.
  - `reset` replies now include `start`. `capabilities.checkpoint` is true.
- **Run modes (verified live 2026-11-18, `tools/m1/mode_test.py` 8/8; identical traces in both modes; dedicated 38x and background 22x real time at k=4):**
  - `dedicated` gives all hardware threads, normal priority, and requests served back to back up to 12 ms per frame.
  - `background` gives below-normal priority, GD limited to the 4 highest-numbered hardware threads, and 6 ms bursts.
  - `normal` serves one request per frame.
  - The user can override the client: hotkey **Ctrl+Alt+B** toggles dedicated/background, or `tools/mode.ps1` writes `gdbot/mode.txt`. A user choice wins over `set_mode` (whose reply then has `overridden_by_user: true`) until the user sets `auto`.
  - `step` and `hello` replies include `mode`.
  - Modes change pacing and CPU share only, never simulation results.
- `trace` rows carry per-tick terminal events. `button.queued` is `null` (not mapped).
- `players[].vx` is x(t)−x(t−1) per physics tick, independent of k. `rot` is visual rotation (degrees) and not gameplay orientation. Per-tick dy ≈ `vy` × 0.225.

### Original plan text
- **`load_level {"level": {"kind": "level_string", "name": "<drill id>", "data": "<level string>"}}`**
  - `data` is the level string **encoded the way GD stores it**: URL-safe base64 of the gzip of the inner level string, which starts with `H4sI`. Python does the encoding; the bridge writes it into a fresh `GJGameLevel` unchanged.
  - The *inner* string has a header section `kA..,..;`, then one object per `;`-separated record as `key,value` pairs. At minimum it has `1,<object id>,2,<x>,3,<y>`, plus optional `6,<rotation>`, `4,<flipX>`, `5,<flipY>`, `32,<scale>`.
  - The reply's `level.revision` is the SHA-256 of `data`, so tapes can pin the exact drill.
- **`quit_level`**: return to the menu so another `load_level` can follow without relaunching.
- **`hello.capabilities.objects` becomes true** once object extraction lands:
  - `obs.objects` lists collision-relevant objects inside the window.
  - Each object has `uid`, `cat`, `type_id`, `x`, `y`, `w`, `h`, `rot`, `active`, and `params`, as defined above.

## Planned v1 (not implemented)
After `reset`/`step` replies, the bridge may add a binary trailer frame (`u32 len` + bytes):
- `PLAYER`: N × fixed 64-byte rows.
- `OBJECT`: M × fixed 40-byte rows, schema id in the JSON header.

It is enabled per session via `hello.capabilities.binary_obs`. This is only built if M2 profiling shows JSON dominates.

## Mock bridge requirement (for Python tests)
`gdbot` ships a mock bridge that speaks this protocol over the same framing. It can run in-process or on a real named pipe. Its toy physics only needs to exercise plumbing (deaths, completion, k-stepping, episode IDs, traces). It is not a GD physics clone and must not try to be one.

## Implemented: minimized window, parallel instances (2026-11-19)
- **Minimized GD keeps working.** A minimized GD stops its frame loop, and the bridge answers inside that loop.
  - Minimize requests (title bar, taskbar, Win+Down) now send the window behind all other windows instead.
  - A watchdog restores it, unfocused, if it gets minimized another way.
  - The launcher starts GD shown and unfocused.
- **`quit_level` timing fix.** The reply now waits for 45 frames *and* at least 1 s after the level layer is gone. At uncapped frame rates, 45 frames alone ended before the fade to the menu did, and the next `load_level` never started. Verified: `tools/m1/sequential_test.py 3` passes 6/6.
- **Audio:** `tools/mute_gd.ps1` mutes the bot copy through the Windows per-app mixer.
- **Windowed display.** A fullscreen GLFW window minimizes itself whenever it loses focus, which caused the stalls and killed new parallel copies.
  - The fix is GD's own setting: `gv_0025=1` (windowed) in each slot's bot save (`tools/gd_save.py <slot> set gv_0025 1`, only while that slot is closed). GD then starts in a 640×480 window with correct visuals.
  - If a slot still starts fullscreen, the bridge falls back to `CCEGLView::toggleFullScreen(false, false, false)` on the first frame and logs `display: WARNING`. This keeps the bot working, but the runtime switch leaves stale GL state: a white quadrant, flashing, and untinted black-and-white sprites.
- **`snapshot` (debug):** `{"op":"snapshot"}` reads the last presented frame (GL front buffer) and writes `snapshot.bmp` into the slot's directory. It returns `{path, width, height}` and never brings the window forward.
- **Parallel instances (verified 2026-11-19, `tools/m1/instances_test.py` 12/12).**
  - `gdbot-launch.exe --instance N` (1–63) sets `GDBOT_INSTANCE`. Slot N keeps `bridge.json`, `bridge.log` and `save/` in `gdbot/inst<N>/`; a new slot's save is seeded from slot 0's bot save. `bridge.json` gains `"instance"`.
  - `mode.txt` stays shared, so one toggle drives every slot. Python helpers are in `gdbot/instances.py`.
  - Two slots running the same tape at once both match a solo trace exactly. Aggregate throughput was 6,211 ticks/s, against 3,086 for one instance.
  - Claim a slot as `RUNTIME:gd-2.2091/slot<N>`; plain `RUNTIME:gd-2.2091` means slot 0.
- **Per-slot DLL copy:** the launcher copies the bridge DLL into the slot's directory (`gdbot/gdbot_bridge.dll` or `gdbot/inst<N>/gdbot_bridge.dll`) and loads that copy. The build output is never locked, so the bridge can be rebuilt while other slots run; a slot picks up the new build at its next launch.
- **Input guard:** while a bot client is connected, mouse and keyboard input to GD is ignored, and this is logged. A stray click in the visible window once started a level under the bot. Window moves, resizes and minimizing still work.
- **Diagnostics:** `ExitProcess`, self-`TerminateProcess` and the first three access violations are logged to `bridge.log` with a module+offset stack.
