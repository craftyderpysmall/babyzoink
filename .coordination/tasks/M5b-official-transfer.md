# M5b official-level transfer

Status: complete. The study was finished by codex/m5b-transfer-01, which ran out of usage before the write-up; claude/plan-01 wrote the results below from `build/m5b-official/transfer/report.json` (`complete: true`).

## First deaths and observation coverage

The reproduced first attempts use the frozen M5 generation-3, seed-2357 checkpoint. The game is driven at k=4. The last 30 raw observations, selected top-K rows, actions and press probabilities for each level are in `build/m5b-official/counterfactual/report.json`.

| Official level | Progress | Death x | Last new press x | Immediate exported objects |
| --- | ---: | ---: | ---: | --- |
| Stereo Madness | 5.38% | 1437.2 | 919.2 | Spike 8 ahead, followed by another spike |
| Back on Track | 2.82% | 714.0 | 654.3 | Spike 8 under the trajectory and another ahead |
| Polargeist | 1.64% | 458.3 | None | Two half-height hazards 39, plus a nearby orb 36 |
| Dry Out | 2.60% | 655.6 | 503.7 | Solid 6 with spike 8 above it |
| Base After Base | 3.11% | 807.5 | 799.7 | Spike 8 directly ahead, with another farther ahead |

All five start as a regular cube at x=0, y=105, with normal gravity and native speed 0.9. The same is true of the M3 control fixtures. No first-death decision truncated the native window or saturated the 32 encoded rows. The cache reported `bad_type=0` in all five official levels. All the listed hazards were in the selected top-K rows. That verifies the local hazards through first death and does not establish exhaustive coverage of the first 10%. The best short geometry probes reached 5.93%, 4.48%, 2.06%, 4.14%, and 8.48%, respectively.

The policy completed the single and double spike drill controls. The same exported spike 8 was 6×12 units. It pressed at roughly 62–67 units to the next isolated spike and 51–55 units for pairs. The block-steps control died without pressing. The official failures include absent presses at the Stereo Madness spike pair and Polargeist short spikes, followed by cases with a press too early or too close to the barrier. Replacing unfamiliar object IDs or filtering ground support in the frozen policy's input produced the same first-death tick on all five. The evidence favors missing and mistimed decisions under new obstacle geometry and combinations. It does not point to a missing nearby category, different start state, or capacity loss.

## Matched remedy and training protocol

Both candidates re-clone from the same 27 verified train tapes (all nine M3 and 18 M5 train fixtures), with the frozen top-K BC schedule and seed 2357. The feature arm opts into fine-scale timing plus an explicit horizontal front gap, vertical intrusion, and contact band. Original object IDs no longer act as numeric features in that arm. Categories and parameters remain inputs. The original encoding stays the default for reproducing M3 through M5.

Select from the 27 frozen validation layouts before running the five official first attempts. Then treat official levels 1–5 as train levels and use only the bot's own successful practice sections or clean completions. Each official level gets up to ten full attempts. Measure the resulting policy's 27 held-out drills again on a fixed first run and score up to three full attempts per online held-out. Online adaptation stays local to that fixture and is excluded from the training archive. Record real attempt and practice telemetry.

## Frozen online set

Downloaded directly through the project cache. Criteria were rated classic Easy–Hard, no demons or platformer content, no reverse trigger present, and a mix of eras, lengths, and modes. Mode lists describe portals present in the downloaded layouts. They do not imply the policy reached them. Payload hashes are frozen in the transfer report.

| ID | Level | Stars | Selection reason |
| ---: | --- | ---: | --- |
| 6508283 | ReTraY | 2 | Classic mixed transitions with cube, UFO, ship, ball and wave |
| 4454123 | Sonar | 2 | Less dense older layout with UFO and wave portals |
| 74730213 | Curfew | 2 | Medium length with robot and spider |
| 11940 | Level Easy | 3 | Early, low-object-count cube and ship |
| 146319148 | Sigil | 3 | Modern swing, ball and ship |
| 94887416 | Magic Valley | 3 | Cube, ship, robot and spider at a distinct pace |
| 112109153 | Vision | 4 | Dense modern cube, ship, wave and robot |
| 83923662 | e4 | 4 | Ball and wave among dense older decoration |
| 137883268 | Chillwave | 5 | Modern seven-mode layout including swing |
| 83653641 | lil Horizon | 5 | Seven modes including spider, with no swing |

Model selection uses the generated validation pool only. The online selection was frozen from server metadata and portal presence before any bot attempt. [Official star categories](https://www.robtopgames.com/files/GDRating.pdf) · [Creator's Sigil showcase](https://www.youtube.com/watch?v=yBDJFcrfcPo)

## Results (seed 2357, from the completed report)

**Encoder arms on the 27 frozen validation drills:**

| Arm | Clears / 27 | Mean capped attempts | Mean first-run progress |
| --- | ---: | ---: | ---: |
| base (original features) | 19 | 1.67 | 78.0% |
| route (fine timing + front gap / vertical intrusion / contact band; no numeric object IDs) | **22** | **1.44** | **87.0%** |

Route was selected. On drills it is a clear improvement.

**Official levels 1–5 as train levels** (zero-shot first attempt, then up to 10 full attempts with checkpoint practice and self-imitation re-cloning):

| Level | First run | Best in 10 | Practice demo decisions added |
| --- | ---: | ---: | ---: |
| Stereo Madness | 5.4% | 5.4% | 0 |
| Back on Track | 3.9% | 7.6% | 180 |
| Polargeist | 4.9% | 4.9% | 0 |
| Dry Out | 2.1% | 2.6% | 0 |
| Base After Base | 3.1% | 5.2% | 120 |

There were no clears. The practice timing search found successful sections on only two levels, and none on the other three.

**Frozen online held-out set (10 levels, 3 full attempts each with local practice):** 0/10 clears, mean first-run progress 4.8% (range 1.7–12.9%). The fixed-first-run drill regression after official training was 20/27.

**Cost:** practice used 98,799 ticks, 258 resets and 73 s. Re-cloning used 158 s wall and 1,247 CPU-s.

## Conclusion and next bottleneck (claude/plan-01)
- The collision-feature encoder helps on drill-like content (19 → 22/27) but does not move real levels. The diagnosis stands: the bot fails on *new obstacle geometry and combinations*.
- With 27 drill tapes as its only expert data, behaviour cloning has never seen most real patterns.
- Self-imitation can't bootstrap: the local practice search (≤36 timing tweaks around one failure) almost never finds a working section on real levels, so few new demos are produced.
- **Next:** a deterministic *search-based teacher*. GD is deterministic in lockstep, and checkpoints restore exactly. A segment-by-segment search (beam or BFS over press/release timings at k=4, branching from checkpoints, scored by progress) can find clears of real levels without a human. Those clears become demonstrations for BC (expert iteration). The learned policy then guides the search to make it cheaper over time, which is also the "fewer attempts on harder levels" story.

## Reproduction

The study writes `build/m5b-official/transfer/report.json` after each encoder arm, official level, and online level. If interrupted, rerunning the same output directory and bridge resumes completed units.
