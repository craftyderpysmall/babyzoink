# Offsets and build identity

## Pinned build
| Item | Value |
| --- | --- |
| Game version | 2.2091 (Windows, Steam buildid 26002420, released 2026-10-17) |
| `GeometryDash.exe` SHA-256 | `4eee06d5c2e2213b4ba2b1f6233dd426bbdd0e9b29d7c375e499516b6f8f69d5` |
| PE timestamp | `0x6AD2D987` |
| Offsets file | `mod/offsets/4eee06d5c2e2213b.json` (keyed by the first 16 hex chars of the exe SHA-256) |
| Reference | geode-sdk/bindings @ `c6ce3dc90487ad75a71ded9b95e58d19c871a158`, `bindings/2.2091/GeometryDash.bro` |

2.209 and 2.2091 show the same version string. **Identify builds by hash, never by version text.** The bridge must stay inactive if the exe hash has no offsets file.

The bindings repo has no license file. We use it only as reference data: the downloaded `.bro` files stay in the gitignored `tools/m0/ref/`. We commit only addresses we have re-verified against our own exe.

## Frozen copy (`game/2.2091/`, gitignored)
- It is a clean copy of the Steam install. File hashes are in `tools/m0/frozen_manifest.json`.
- Left out of the copy, because they are mods in the user's Steam install:
  - `XINPUT1_4.dll` (Mega Hack proxy loader)
  - `hackpro.dll` (Mega Hack)
  - `geode/` (leftover Geode data)
  - `absolllute.megahack/`
  - `replays/`
  - `_gd_backup_*`
- The exe and `libcocos2d.dll` are byte-identical to the user's 2026-11-11 backup.
- **Do not launch the frozen copy yet.** By default GD saves to `%LOCALAPPDATA%\GeometryDash`, which is the user's real, Steam-Cloud-synced save (`steam_autocloud.vdf` is present).
  - The bridge must hook `CCFileUtils::getWritablePath` / `getWritablePath2` (exported by `libcocos2d.dll`) to redirect saves *before* the copy runs.
  - A backup of the real save (without music) is at `game/save-backup-2026-11-18/`.

## How RVAs are verified
1. **Static (M0, done)**
   - Command: `python -I tools/m0/verify_surface.py game/2.2091/GeometryDash.exe tools/m0/ref/GeometryDash.bro tools/m0/surface_report.json`
   - Each RVA must equal a `BeginAddress` in the exe's `.pdata` table (the x64 exception directory).
   - Result: all 20 surface functions pass, out of 19,380 `.pdata` entries.
   - This proves only that a function *starts* there. It does not prove the function is the one we want.
2. **Live (M1, pending)**
   - Inside the injected bridge, before any automated play, check each hook's behaviour:
     - `handleButton` fires on a manual click with the expected `down` and `button` values.
     - `destroyPlayer` fires once per death.
     - `processCommands` reports isHalfTick/isLastTick at the expected 240 tps cadence.
     - `resetLevel` returns the player to the start position.
   - Record the result as `live_check` in the offsets file.
   - A failed check disables that capability.

## Hook-by-export (companion DLLs; fingerprints in the offsets file)
| DLL | Symbol | Use |
| --- | --- | --- |
| libcocos2d.dll | `CCFileUtils(Win32)::getWritablePath2` | save redirection (isolation) |
| libcocos2d.dll | `CCScheduler::update` | time scale (dedicated/background) |
| libcocos2d.dll | `CCDirector::drawScene` | draw skip/decimation |
| libExtensions.dll | `CCHttpClient::send` | block online traffic (isolation) |

## Known gaps (M1)
- **Member field offsets are not mapped yet.** Player position, velocity and mode on `PlayerObject` and `GJBaseGameLayer` are needed for M1 observations. The `.bro` declarations don't give Windows offsets directly. Options:
  - (a) Run the bindings codegen offline to get the layout.
  - (b) Discover the offsets live: diff memory around a known `PlayerObject*` while the player moves.

  Either way, verify live.
- `GameStatsManager::incrementStat` has an inline overload. Only the out-of-line one (`0x2da460`) is hookable.
- Isolation uses two layers:
  - (1) Windows Firewall rules "GDBot - block frozen GD 2.2091 (outbound/inbound)" on `game/2.2091/GeometryDash.exe`. Created 2026-11-18 and keyed to that path, so they must be recreated if the copy moves.
  - (2) The `CCHttpClient::send` hook (M1). Verify the hook also covers 2.209's death telemetry and chat, which may use libcurl or websockets directly.
