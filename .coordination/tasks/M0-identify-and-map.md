# Task: M0 identify and map

Status: done (static part). Launching the frozen copy is moved to M1, because the save redirect hook must exist first.
Agent/session: claude/plan-01
Created: 2026-11-18
Related plan: .coordination/plans/2026-11-17-gd-learning-bot.md

## Desired outcome
- The exact build is identified by hash.
- A clean frozen copy exists.
- The bindings reference is pinned to a commit.
- The M1 surface is mapped and statically verified.

## Scope and likely files
`.gitignore`, `game/` (gitignored), `tools/m0/`, `mod/offsets/4eee06d5c2e2213b.json`, `docs/OFFSETS.md`

## Current findings
- **The user's Steam GD is modded:**
  - Mega Hack: an `XINPUT1_4.dll` proxy plus `hackpro.dll`.
  - Leftover `geode/` data.
  - None of these were copied into the frozen copy.
  - The exe and libcocos2d match the user's 11-11 backup, so they are stock.
- **The real save folder is Steam Cloud synced.** The frozen copy must redirect saves before it is launched.

## Work completed
- Frozen copy at `game/2.2091` (341 MB). File manifest at `tools/m0/frozen_manifest.json`.
- Real save backed up to `game/save-backup-2026-11-18`.
- Bindings pinned at `c6ce3dc`. The reference `.bro` files are in gitignored `tools/m0/ref/`.
- `tools/m0/verify_surface.py`: all 20 surface RVAs (M1 plus M4) are `.pdata` function starts.
- Companion DLL exports found for save redirect, scheduler, draw, and HTTP.
- Results written to `mod/offsets/4eee06d5c2e2213b.json` and `docs/OFFSETS.md`.

## Validation and results
- `python -I tools/m0/verify_surface.py ...` reports 20/20 `PDATA_START`.
- Static only. Live semantic checks are pending in M1.

## Blockers / decisions needed
- None. Firewall rules were created 2026-11-18 with the user's approval: "GDBot - block frozen GD 2.2091 (outbound)" and "(inbound)", both Block, Profile Any. They are keyed to the program path `C:\Users\user\Documents\babyzoink\game\2.2091\GeometryDash.exe`, so if the copy moves, the rules must be recreated.

## Next action and handoff
M1, in this order:
1. Injector, bridge skeleton, and offsets loader that checks the exe hash.
2. Save redirect and HTTP block, verified before anything else runs.
3. (Firewall rule done.) Confirm the frozen copy still starts with Steam running. steam_api talks to the local Steam client over IPC, not the network, but this is unverified.
4. First launch of the frozen copy.
5. Live checks of the hooks.
6. Map PlayerObject fields.
7. Tick-stamped press/release and reset.

## Completion criteria
Met for the static scope. The live checks are tracked under M1.
