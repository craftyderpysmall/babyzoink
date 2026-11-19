# Handoff: bridge rebuild (draw-skip, window colours) + quit crash warning

To: codex
From: claude/perf-01
Status: info (no action required; read before your next GD launch)
Date: 2026-11-19

## What changed (mod/build/Release/gdbot_bridge.dll, picked up at each slot's next launch)
1. **Your GD windows turn ChatGPT green**, mine Claude orange, at the user's request. It's automatic: `BridgeClient.hello()` finds `codex` in its parent-process chain. If your Python runs detached from codex.exe, set `GDBOT_AGENT=codex`.
2. **`set_render` draw-skip**, off by default, so nothing changes unless you opt in. For M6 throughput, send `c.request("set_render", present_every_ms=1000)` after `set_mode dedicated`. It gave +7–9% on long `step_seq` requests, with identical replies. Details are in docs/PROTOCOL.md (2026-11-19 section).

## Warning: quit_level crash (older bug, not caused by these changes)
`quit_level` from inside a main level after a long dedicated `step_seq` session crashed GD three times out of three, on both the old and the new bridge. It crashes in a CCFadeTo on a freed sprite atlas about 0.55 s after onQuit. M6 quits between levels, so if a slot dies at quit, this is why. I'm investigating it next. Until then, relaunching the slot after the crash recovers.

## Response
