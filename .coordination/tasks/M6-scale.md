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

## Pool validation

Downloaded 59 classic levels: 12 Easy, 11 Normal, 12 Hard, 12 Harder and 12 Insane. The Normal Short filter returned only two eligible levels after checking additional result pages. Counts by length are 14 Short, 15 Medium, 15 Long and 15 XL. The portal scan represented all eight modes across six reported game-version codes. Manifest checks passed for all 122 payloads. The frozen online IDs and payload hashes do not overlap training, and the frozen drill validation/held-out payloads do not overlap the 63 training drills.

The final memory check returned 2,238 MiB as the slot-0 claim was transferred. No M6 game was launched. Prioritize the newly released #18 diagnostics, then resume #19's live pilot and scaling curve.

## Live pilot and first online batch

The slot-2 pilot verified all six drills in clean runs from 0% (2,083 search evaluations total). The short online level Stageix reached the 2,000-evaluation smoke-test cap without a clear and saved a resumable prefix. The ledger independently shows six normal clears and 4,083 candidate evaluations across those seven levels.

The updated bridge's draw-skip mode made a load fail when enabled in the menu. The worker now loads the scene with full rendering, enables draw-skip for active search, and restores rendering before quitting. The successful pilot used this sequence on all seven levels, including the online transition.

With 3,926 MiB available before launch, started the even-index online shard in slot 2, capped at ten levels and 6,000 cumulative evaluations per level, with 40 lookahead decisions. It runs alongside the separate official task in slot 1. Log: build/m6-scale/online-shard0.log; retained session 71708. Check solve rates before broadening the budget, and preserve reports when resuming.

## Scaling evaluation prepared

tools/m6/curve.py freezes the verified cohort on first launch. It holds the verified drill demos fixed, balances an independently seeded order across online difficulty and length, and uses nested online subsets at 10, 20, 40 and all available clears. It verifies level and action hashes for resumption, rejects overlap with the frozen online test levels, and logs replays separately from learned-policy first runs on official 1–5 and the ten frozen online levels. The seed can be supplied explicitly for the three-seed rerun. CLI, deterministic ordering, and live solution discovery checks passed; a learning run needs at least ten verified online solutions.

After the official diagnostics finished, Codex applied texQuality=1 to the closed slot-1 bot save and kept a local backup. At the attempted second M6 launch the host had 2,127 MiB free, so it did not launch. Slot 2 continues the online batch. Slot 1 is available for the next drill batch once memory recovers.

A live sample found 2,409 MiB working set in the slot-2 game on Skill Gotten Gains and 1,964 MiB available for the host. Keep the single M6 session until there is enough headroom for another. Asked Claude to compare memory during level load, prolonged resets and quit in a separate slot after capacity is available.

The old slot-2 batch was stopped at its saved Skill Gotten Gains checkpoint to pick up the tested older-checkpoint fallback. After Steam was closed at the user's request, the launcher warned Steam was absent. The newly launched GD process exited with code 1 within 60 ms, before the client could open its pipe. Leave Steam closed until the user asks to restart it or starts it themselves. The online training batch can then resume without repeating its two capped levels. Slot 2 is released.

## Resumed after Steam restart

The first game launch after opening Steam exited before sign-in finished. Once Steam reported a signed-in session, GD slot 2 launched successfully (PID 14284, retained session 92207). The worker resumed Skill Gotten Gains at segment 304, x=16,393. The live bridge log verifies the older-anchor fallback restored an earlier checkpoint at x=5,017 instead of replaying each candidate from 0%. The machine had 4,119 MiB available before launch. Both previous capped levels remain recorded.

For the current worker and live checkpoints, see build/m6-scale/online-run-state.json, online-shard0-older-anchor.log and solutions/*.progress.json. Claude has a standby handoff in handoffs/2026-11-19-codex-to-claude-m6-continuity.md. Keep these coordination notes current at each completed level and recheck them during long searches.

Paused at the user's request. Codex stopped slot 2; Claude's GD was left alone. Latest saved Skill Gotten Gains checkpoint: segment 320, x=17317, 1013 evaluations.

## Claude runs #19 (2026-11-19 08:30 UTC, claude/m6-run-01)
The user asked Claude to run M6 while Codex is paused. Two detached supervisors (`tools/m6/supervise.py`, venv Python), budget 6,000, lookahead 40, draw-skip at 1,000 ms:
- Slot 2: `--split online --shards 2 --shard 0`. It resumed Skill Gotten Gains at segment 320 (x 17,317).
- Slot 1: `--split drills`, then `--split online --shards 2 --shard 1`.
- Memory guard (#29): solve_pool saves progress and exits 75 when GD's private bytes pass 1,500 MB or available RAM falls below 900 MB. The supervisor kills only that slot's GD (its discovery PID), relaunches it, waits for Steam if needed, and resumes. It allows at most 40 restarts per job.
- Live state: `build/m6-scale/supervise-slot{1,2}.json` and `.log`. To stop, end the two supervisor `python.exe` processes, then close the slots' GD windows. Progress resumes from `solutions/*.progress.json`.
- After the run: with 10 or more verified online clears, run the scaling comparison (`tools/m6/curve.py`).
