# Handoff: bridge rebuild (draw-skip, window colours) + quit crash warning

To: codex
From: claude/perf-01
Status: info (no action required; read before your next GD launch)
Date: 2026-11-19

## What changed (mod/build/Release/gdbot_bridge.dll, picked up at each slot's next launch)
1. **Your GD windows turn ChatGPT green**, mine Claude orange, at the user's request. It's automatic: `BridgeClient.hello()` finds `codex` in its parent-process chain. If your Python runs detached from codex.exe, set `GDBOT_AGENT=codex`.
2. **`set_render` draw-skip**, off by default, so nothing changes unless you opt in. For M6 throughput, send `c.request("set_render", present_every_ms=1000)` after `set_mode dedicated`. It gave +7–9% on long `step_seq` requests, with identical replies. Details are in docs/PROTOCOL.md (2026-11-19 section).

## Fixed: quit_level crash (an older bug)
`quit_level` from inside a level after a long dedicated session crashed GD every time, on the old bridge too: a CCFadeTo ran on a freed sprite atlas. The bridge now clears pending CCActions before `onQuit` while a client is in control. That gave 2 of 2 clean quits, and `tools/m1/sequential_test.py 3` passes 6/6. If an M6 slot died at a level switch before, relaunch it on the new build.

## RAM per slot (#24), measured with tools/m7/mem_probe.py on the 8 largest M6 online levels
- A slot uses 450–800 MB working set and 630–960 MB private, with the peak on the 2.5 MB "GD Randomizer"/"im BLIND" payloads. About 400 MB remains at the menu afterwards. Budget about 1 GB per slot in the worst case, and about 0.6 GB for typical levels.
- `texQuality=1` (low textures) in the bot save cuts private memory by 80–115 MB per level (12–15%) while the working set stays flat. Physics is unchanged: the step_seq reply was identical to the default-texture run, and the main 1–3 solutions still complete, at tick 20332 on Stereo Madness as before.
- Applied to slots 0, 2 and 3. **Slot 1 is still on default textures.** Next time it is closed, run `python -I tools/gd_save.py 1 root texQuality 1`, or `python -I tools/gd_save.py all root texQuality 1` when every slot is closed.
- Free RAM mostly goes to the user's own apps (ChatGPT, Steam, Roblox, Defender), not to GD.

## Response
