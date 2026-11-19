# M5 curriculum

Status: complete (codex/m5-curriculum-02). The study, official-level evaluation, and dashboard telemetry replay are saved.

## Offline stages

- The M5 manifest contains 54 original variants across 18 families, with separate fixed train, validation, and held-out seeds. The existing M3 manifest and held-out layouts retain their hashes. The new entries remain `training_ready: false` until a live replay proves the completion and passes the exported object audit.
- Each generation starts a fresh top-K BC model per seed using the original M3 train demos, verified tapes for unlocked M5 train families, and that seed's successful practice sections and clean train runs from prior generations. The first M5 family starts unlocked. A clean train win unlocks the next family for the following generation.
- Score the frozen M3 and M5 held-out layouts with the M4 per-level practice budget of three full attempts. Begin every fixture from the frozen generation model. Keep evaluation practice demonstrations in temporary directories so they cannot enter a generation's archives. Validation uses the frozen model and ranks the newest generation's seeds for the official-level run.
- The runner stores demonstration archives on disk and loads one at a time during cloning. It publishes checkpoints, per-attempt outcomes, archive references and progress by generation and seed. It verifies fixture and train tape hashes before resuming.
- Verification uses k=4, repeats each completion witness, and checks object IDs, positions, categories, params and observed mode transitions. The witness search and study require the isolated, launcher-owned game. Their CLI imports and the full Python suite passed offline (49 tests).

## Resume live stages

1. Hold `RUNTIME:gd-2.2091` and the exact work paths while a study session owns the game. Read the running session and report before relaunching.
2. Launch through `gdbot-launch.exe`. Run `build/gdbot-venv/Scripts/python.exe tools/m5/verify.py --pid <launcher-owned PID> --output build/m5-curriculum`. Use `--family` to repeat an audit separately. Resolve witness failures from the real game evidence. If the bridge exports incorrect IDs or is missing required observation fields, record a handoff to Claude and preserve the evidence in the audit.
3. When all live fixtures pass, run `build/gdbot-venv/Scripts/python.exe tools/m5/study.py --pid <launcher-owned PID> --output build/m5-curriculum --generations 3`. The runner evaluates main levels 1–5 with a ten-attempt cap after the generation study. Record measured clears, attempts, progress, ticks, wall time and CPU here.

## First live audit

- Ship corridor train-5100 passed in slot 0, with matching object metadata and both cube and ship observed. The k=4 witness cleared twice at tick 1,094 with 90 edges. The matching tape is saved and its manifest entry is training-ready.
- The second level load failed in three independent launcher sessions. This also occurred between two verified M3 drills in normal pacing without any steps before the second load. See [the bridge handoff](../handoffs/2026-11-19-codex-to-claude-m5-bridge.md). The remaining 53 fixtures, generation study, and official-level tests are pending.

## Post-fix live audit and study

- With the fixed bridge, all 54 variants across 18 families passed a repeated k=4 completion with matching object IDs, positions, categories, and parameters. The witness tapes reached completion in 1,071–1,972 ticks, with 0–220 input edges. The 54 edge tapes total 51,341 bytes.
- Live failures drove revisions before the generation study froze its inputs. The robot uses a lower tall wall for the held jump, the pink pad uses a single closer spike, and the green orb has more room for the gravity switch before the first spike. The final blue-pad, blue-orb, and green-orb witnesses showed the gravity flip. Every dash witness had `dashing: true`, and every mini variant set `mini: true`.
- Tape results are in `build/m5-curriculum/verification.json`. The fixed bridge SHA-256 is `b57b967fa9f43dfd965fc6ff1f49d68e13f08347e387df7e2f194ae231696c9f`. The test suite passed (66 tests).
- The study completed with nine durable checkpoints and five official-level results. Its launcher-owned game closed. The immutable comparison is in `build/m5-curriculum/report.json`.

## Three-generation held-out results

Each seed scored 27 unseen levels (nine frozen M3 drills and 18 M5 drills). Clear counts allow checkpoint practice between up to three full runs. Mean attempts counts failures at the cap. First-run progress is measured before any adaptation for that level.

| Generation | Clean clears by seed (1207, 2357, 3907) | Mean clears / 27 | Mean capped attempts | Mean first-run progress |
| --- | --- | ---: | ---: | ---: |
| 1 | 21, 21, 21 | 21.0 | 1.840 | 71.5% |
| 2 | 21, 18, 22 | 20.3 | 1.901 | 72.4% |
| 3 | 21, 18, 18 | 19.0 | 1.864 | 73.4% |

The three-generation run did not reduce attempts to clear and lost capped clears, even though first-run progress increased. Seeds 1207 and 3907 did not clear the first family (ship) within the curriculum gate. Seed 2357 unlocked ball for generation 3 and cleared it, unlocking UFO for a possible fourth generation. That seed was selected for the official evaluation by the generation-3 validation results (17/27 vs 14/27 and 12/27).

## Official levels

| Level | First-run progress | Best progress | Result |
| --- | ---: | ---: | --- |
| Stereo Madness | 5.38% | 5.38% | No clear in 10 |
| Back on Track | 2.82% | 3.90% | No clear in 10 |
| Polargeist | 1.64% | 5.88% | No clear in 10 |
| Dry Out | 2.60% | 3.55% | No clear in 10 |
| Base After Base | 3.11% | 5.24% | No clear in 10 |

Across validation, held-out, train promotion, and official runs, 1,028 full attempts used 1,283,767 physics ticks and 823.97 s of measured full-run wall time. Practice used 4,175 resets and 829,328 ticks. Checkpoint parity passed in 257/272 windows; the others replayed their clean prefix. Practice search used 105.60 s of wall time, re-cloning took 1,222.28 s, and initial cloning took 85.55 s. Together the measured Python operations consumed 11,208.45 CPU-seconds across threads. The game session lasted about 47 minutes elapsed, including scene transitions and startup.

The next bottleneck is transfer to authentic early sections and promotion robustness. Two seeds never advanced past the introductory family, and the validation-selected model died before 6% on every official level. Re-cloning also dominated practice cost. A frozen comparison should test more diverse verified train demonstrations and a cheaper adaptation budget before extending the generation count.

## Dashboard telemetry follow-up

- The runner now records full attempts and timing-search candidates with `EnvTelemetry`. Checkpoint setup and parity probes stay out of the rating data. Practice candidates are labeled separately, including prefix-replay candidates that start from zero. A generation/seed's JSONL is published only after its run completes.
- The backfill replayed all 243 held-out first attempts and the five official evaluations with practice. All 248 first attempts matched the original terminal, tick count, and end position. The replay left the original study report intact and the launcher-owned game closed.
- Ten telemetry files contain 1,003 section entries across all eight modes, including 598 practice entries. The refreshed local dashboard shows this evidence. The full-run view has one pre-demon rating, and the data supports no numeric demon-tier rating. The public main-branch URL returned HTTP 200 with cross-origin access and still held the previous snapshot. Browser testing confirmed that the newer bundled data displayed in the interim.
