# Task: M1 isolated bridge (native side)

Status: done (core). Control, stepping, reset, load_level and the pipe v0 server pass the live test. Object extraction is not done yet; it is needed before M3 learning. The user's review of the screenshots is pending.
Agent/session: claude/plan-01
Created: 2026-11-18
Related plan: .coordination/plans/2026-11-17-gd-learning-bot.md

## Desired outcome
- An injected bridge with verified isolation.
- Live-checked hooks.
- Tick-stamped hold/release and full reset.
- The protocol v0 pipe server (docs/PROTOCOL.md).

## Scope and likely files
`mod/` (CMake, src/), `injector/`, `tools/gen_offsets.py`, `docs/PROTOCOL.md`, `docs/OFFSETS.md`

## Work completed
- `tools/gen_offsets.py` generates `mod/src/offsets_gen.hpp` from `mod/offsets/*.json`. The JSON is the source of truth.
- `gdbot_bridge.dll` (MSVC 14.44, /MD, MinHook v1.3.4 tarball):
  - **Build check:** SHA-256 of the exe at init. On mismatch it returns 2 and the launcher kills the game.
  - **Isolation:**
    - kernelbase file guard denying any access under `%LOCALAPPDATA%\GeometryDash`: CreateFileW/A/2, MoveFileExW, MoveFileWithProgressW, DeleteFileW, CreateDirectoryW, ReplaceFileW, CopyFileExW.
    - `CCFileUtilsWin32::getWritablePath` redirected to `game\2.2091\gdbot\save\`; `getWritablePath2` is only observed.
    - Blocked: `CCHttpClient::send`, `curl_easy_perform` (returns 7), and `GameLevelManager::updateUserScore` (no-op).
    - `curl_multi_perform` is observed only; the firewall covers it.
    - If the file guard, save redirect, or HTTP block fails, init returns 3 and the game never runs.
  - **Live checks:** pass-through logging hooks on handleButton, processCommands, GJBaseGameLayer::update, PlayLayer init/postUpdate/resetLevel/fullReset/levelComplete/onQuit/destroyPlayer/pauseGame.
  - The log goes to `game\2.2091\gdbot\bridge.log`.
- `gdbot-launch.exe`: CreateProcess SUSPENDED → remote LoadLibraryW → remote `gdbot_init` → resume only on 0, otherwise TerminateProcess.
- **Build:** run `cmake -S mod -B mod/build -G "Visual Studio 17 2022" -A x64`, then `cmake --build mod/build --config Release`. Output goes to `mod/build/Release/`. Warnings are C4100 (unused parameters) only.

## Validation and results
**First launch, 2026-11-18 22:11** (user played Fingerdash plus one other level by hand):
- **Isolation passed.**
  - All flags were set to 1. `getWritablePath` was redirected, and a fresh profile was created in `gdbot\save`.
  - There were 0 file-guard denials and 2 HTTP sends blocked at startup. curl and `getWritablePath2` were never used.
  - Every change to the real save predates the bot launch: the user's Steam GD wrote it at 22:11:17 on exit (Mega Hack config in the same 0.1 s), and the bot started at 22:11:36. The snapshot was retaken afterwards for a clean comparison on the next run.
- **Tick boundary:** `processCommands` runs at 240 calls/s, two per 120 Hz frame. isLastTick alternates; isHalfTick has always been 0 so far. **One call = one physics tick.**
- **Deaths:** `destroyPlayer` is called once per real death. It is also called on about 10–13 ticks after every reset with one fixed object (likely the anticheat spike), so death detection must filter for that.
- **Pausing:** `pauseGame(unfocused=1)` fires on focus loss. Background mode must suppress it.
- **handleButton:** down and button values are correct; the meaning of the 3rd argument is still open.
- **levelComplete:** not yet observed.
- Details are in the `live_check` fields of `mod/offsets/4eee06d5c2e2213b.json`.

**Run 2 (controlled input test):**
- The handleButton 3rd argument is 1 for Space, W and click, and 0 for Up (the player-2 key). The bot sends (down, 1, true).
- The real save was byte-identical before and after (clean snapshot). One `updateUserScore` was blocked.

**Run 3 (field probe, 19,532 ticks):**
- `m_player1` is at layer+0xdb8.
- Player fields are mapped and checked; see `fields` in the offsets JSON.
  - The per-tick position is at +0x4c/+0x50 (CCNode base). `m_position` at +0xa98 only updates once per frame.
  - `m_yVelocity` at +0x9a8: the cube jump sets it to 11.18, and gravity subtracts 0.216 per tick.
  - Flags: `m_isShip` 0x9c1, `m_isDead` 0x9c8, `m_isOnGround` 0x9c9.
  - The other mode flags (UFO, ball, wave, robot, spider, swing, upside-down, mini) and dash were not exercised, so they are unverified.
- Tools: `tools/m1/find_fields.py` and `check_fields.py`. They need numpy; Claude used a scratchpad venv.

**Run 4: unattended M1 live test (user away, approved). `tools/m1/live_test.py` uses Codex's BridgeClient.**
- 12 of 13 checks passed. The 13th (press) failed only on the test's expectation, which assumed pre-tick sampling; the data was correct (first post-tick vy 10.964 = 11.18 − 0.216, y +28, on_ground cleared). The check has been fixed but not rerun.
- **Passed:**
  - hello reports isolation flags true; load_level main 1 works from the menu (0.6 s).
  - reset gives episode 1, tick 0, x=0.
  - Physics stays frozen while idle; every k=1 step advances exactly 1 tick (dx 1.2982).
  - Death terminal at the first spike (tick 786, x 1020.4); reset afterwards gives a new episode at x=0.
  - The same tape twice gives identical traces (405 rows).
- **Throughput:** dedicated 31× real time at k=1, 74× at k=4; normal 60 steps/s.
- **Screenshots:** `game/2.2091/gdbot/m1_screens/` (after reset, mid-jump from the injected press, death at the spike).
- **Isolation:** the real save was unchanged during and after the run, with 0 denials.
- **Not yet covered:** levelComplete (no completion yet), the background-mode test, and object extraction (capability `objects: false`).

**M1b result (2026-11-18): done, objects_test 8/9; the 9th was a wrong test expectation, now fixed**
- **Corrected GameObject offsets** (the anchors were 0x18 low): uid 0x39c, type 0x3a0, id 0x40c. Verified from `objprobe.bin`; 0 out-of-range types over 2,399 objects.
- **Anticheat spike:** filtered, `m_anticheatSpike` at layer+0x38e0, learned at runtime.
- **level_string works with a local editor level** from `createNewLevel`; using the main level made GD quit the level. A one-spike drill reports the spike at 615 and the idle cube dies at 597.2.
- **Idle cube on Stereo Madness** dies at x=507.6 in front of the spike at 525 (2/2 trials). The M1 run that reached x=1020 was the press bug: the button stayed held after one press.
- **Codex M2 fixes:** holding mirrors the action, the first step after load advances, and vx is per tick.
- **Throughput with objects:** 18× real time at k=1, 56× at k=4 (dedicated).
- The real save was unchanged across all runs.

**M1b history (as built):**
- **Objects:**
  - Read from `GJBaseGameLayer::m_objects` at +0xdd0 (declared after m_player1/m_player2/m_levelSettings) using the exported `CCArray::count` and `objectAtIndex`.
  - Hitboxes come from `GameObject::getObjectRect()` @0x294820. It's a leaf thunk, confirmed by disassembly: `jmp [vtable+0x4a8]` → `getObjectRect(float, float)` @0x294840.
  - GameObject fields come from bindings order anchored on the m_unk390/3D8/3DE/3E8/3F8 names: type +0x388, uid +0x384, objectID +0x3f4.
  - The category mapping follows the GameObjectType enum in the pinned bindings' `Enums.hpp`. Speed portals are recognised by id (200–203, 1334).
  - Safety gate: object extraction disables itself (`unsupported` gets "objects") if more than 5% of objects have an out-of-range type.
- **level_string:** takes a fresh GJGameLevel from `getMainLevel(1)` and overwrites `m_levelString` and `m_levelName`. The string offset is discovered once at runtime: the H4sI string must have the name "Stereo Madness" exactly 0x40 bytes earlier.
- **quit_level:** calls `PlayLayer::onQuit` through our hook; the reply is deferred about 45 frames.
- **Test:** `tools/m1/objects_test.py`. It waits for Codex to release `RUNTIME:gd-2.2091`.

## Blockers / decisions needed
- None. The user's own in-game sign-off is replaced by the screenshots for them to review.

## Next action and handoff
1. First launch:
   - Check that init is ok, hooks were created, and `getWritablePath` was redirected.
   - Check for any ISOLATION deny lines and whether `getWritablePath2` reveals another save path.
   - Confirm the game starts with the firewall on and creates a fresh profile in `gdbot\save`.
2. The user plays a few attempts by hand. From the log, confirm:
   - handleButton values,
   - processCommands cadence (expect 240 tps; half/last pattern),
   - one destroyPlayer per death, and resetLevel per attempt.
3. Close the game. Compare the real save against the snapshot; it must be unchanged.
4. Record the live_check results in `mod/offsets/*.json`.
5. Then: PlayerObject field mapping, input injection, and the pipe server (protocol v0).

## Completion criteria
See plan M1. The isolation flags are reported in `hello`, and the user has verified press/release and reset in-game.
