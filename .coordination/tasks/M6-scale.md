# Task: M6 search-teacher scale

Status: in progress
Agent/session: codex/m6-scale-01
Created: 2026-11-19 (UTC)
Related handoff: handoffs/2026-11-19-claude-to-codex-m6-scale.md (B)

## Desired outcome

Measure first-run progress and clears on the frozen evaluation levels after cloning on 10, 20, 40 and all verified online training solutions. Hold the evaluation set fixed. Track search solve rates, attempts and elapsed time separately from policy evaluation.

## Training pool

- Public, rated classic Geometry Dash levels across Easy, Normal, Hard, Harder and Insane. Target three each in Short, Medium, Long and XL per difficulty, with popular and recently rated sources interleaved. Portal modes are inferred from the downloaded assets and will be measured separately during actual rollouts.
- Use the 27 existing training drills plus two new deterministic training seeds for each of the 18 M5 families. The 63 drills cover 27 families when the original nine families are included.
- Downloads, source search pages, manifests and solution logs are local in build/m6-scale/. The online manifest records the ID, rating, length, reported game version, portal modes and payload hash. The selection excludes frozen evaluation IDs and exact payload matches.
- Generator: tools/m6/pool.py. Search worker: tools/m6/solve_pool.py. The worker verifies each manifest hash, supports disjoint shards on separate slots, and resumes from the existing progress file. The nightly ledger reads the worker outcomes.

## Next run and blocker

Started the cached pool enumeration. The first attempt to launch the slot-1 drill pilot found only 707 MiB available, so the launcher was never called. A later check returned 1,179 MiB while Claude's slot-0 game was active. Retry the pilot when there is sufficient RAM for the 1.2 GiB game process and headroom. The worker has passed a CLI check and still needs a live smoke test. Slot 0 remains with Claude.
