# Task: Generate M3 drill fixtures

Status: done. All 18 generated fixtures have reproducible live completion tapes.
Agent/session: codex/m3-drills-01 and codex/m3-live-01
Related handoff: ../handoffs/2026-11-18-claude-to-codex-m3-drills.md

## Delivered

- The builder in gdbot/levels/levelstring.py writes classic cube starts, numeric object records, and URL-safe base64 gzip payloads. It can parse or decode those strings for round-trip checks.
- The seeded generator in gdbot/levels/drills.py writes 18 original fixtures across nine families. Each has one train variant and one shifted or recombined held-out variant.
- levels/drills/index.yaml records the family, split, seed, SHA-256, forward-progress eligibility, declared trigger dependency, and training readiness. Rightmost-object distances give nominal 1x durations of 15.98–17.24 seconds. Actual timings and reachability remain to be measured in GD.
- levels/drills/README.md provides regeneration instructions and attributes every serialized object ID.

## Validation

All 38 tests passed after live capture. Checks cover encoding round trips, regeneration of the exact on-disk payloads and manifest, each payload hash, deterministic seeds, no split overlap, and replay pausing at the recorded finish tick. No commits were made.

## Live results

The runner in tools/m3/drills_live.py loaded and reset all 18 fixtures in the isolated GD 2.2091 instance started through gdbot-launch.exe. It matched collision-object IDs, categories, and initial centres within four units, accounting for the 90-unit editor-to-world Y offset. It captured a clear from tick zero and replayed each tape twice, checking both the completion tick and the entire trace. No fixture showed a missing, unexpected, or mismatched object after filtering the hidden x=0 spike.

| Family | Train objects | Train clear tick | Held-out objects | Held-out clear tick |
| --- | ---: | ---: | ---: | ---: |
| single-spike | 6/6 | 3,948 | 6/6 | 4,156 |
| double-spike | 11/11 | 3,971 | 11/11 | 3,948 |
| triple-spike | 16/16 | 4,156 | 16/16 | 4,179 |
| block-steps | 19/19 | 3,948 | 22/22 | 4,156 |
| pillar-gaps | 17/17 | 4,087 | 19/19 | 4,110 |
| yellow-orb | 15/15 | 3,948 | 15/15 | 3,879 |
| gravity-portal | 28/28 | 3,994 | 28/28 | 4,087 |
| speed-change | 8/8 | 3,257 | 8/8 | 3,315 |
| moving-geometry | 2/2 | 4,179 | 2/2 | 4,064 |

The mover offset was changed from −40 to −120 after observing that the native trigger applies the stored offset directly in world units. In both final variants the grouped block moved from centre Y=225 to Y=105. Fresh tapes were captured against the corrected payload hashes.

The bridge receives completion from a wall-clock callback. Unpaced dedicated runs could reach the end of the level without returning a completion before the tick budget. Each tape now records a 1.2-second wait at the precise tick where the end sequence has stopped forward movement. Replay waits there without issuing a gameplay command, then requires a native completion on the next tick. Both confirmation traces matched for each tape. The live benchmark and training runner should account for the same completion timing.

The manifest links all 18 training-ready tapes under levels/drills/tapes/. Each includes the native build hash and FNV level revision, the exact drill SHA-256, the layout seed, and replay settings. The full object and search report is build/m3-live/verified.json. The test window was closed before releasing the runtime.
