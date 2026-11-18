# Task: M3 CPU baseline on the live bridge

Status: completed. Both CPU PPO agents and the timing heuristic were scored live.
Agent/session: codex/m3-baseline-01
Related handoff: ../handoffs/2026-11-18-claude-to-codex-m3-baseline.md

## Frozen protocol

The launcher-owned game runs in dedicated mode at k=4. Both PPO encoders use CPU with two Torch threads, seed 1207, the same two shuffled passes over the nine verified training fixtures, and 8,192 transitions per fixture visit. The planned total is 147,456 transitions per encoder. Both use 256-step rollouts, batch size 64, four epochs, and the same optimizer settings. Each has a 50-minute wall-clock safety cap. Initial, half-budget, and final checkpoints are saved in the run directory.

The separate validation pool consists of three fresh fixtures with seeds 3101, 3105, and 3108. Validation seeds and payloads were fixed before training. The nine held-out variants receive no training or online practice. Both PPO policies take a deterministic first attempt and up to two seeded stochastic retries. The heuristic repeats its fixed policy. A failure counts as three attempts. Initial PPO checkpoints are scored for first-run progress only. The per-episode cap is 6,000 physics ticks.

The task measures progress from normalized forward displacement because the native editor playtest progress can persist after a reset. Death incurs a 0.1 penalty and a native completion earns a 1.0 bonus. No level identity or absolute progress enters either policy encoder. A 1.2-second no-command finish wait allows the game to report its wall-clock completion event.

The live runner is tools/m3/baseline.py. Checkpoints and per-attempt JSON results are under build/m3-baseline/first-study/. The JSON distinguishes extra full-run reset, tick, transition, and wall-time costs from the zero online practice budget.

## Results

Both encoders completed 147,456 training transitions. Top-K took 230.5 seconds of wall time and 223.0 seconds of Python process CPU. The set encoder took 228.1 seconds of wall time and 273.1 seconds of Python process CPU. The two encoders used the same configured budget. Their measured process CPU use differed. The game process is outside those CPU measurements. The initial, round-1, and round-2 checkpoints are present for both encoders.

| Agent | Held-out mean first progress | First-run clears | Clears within 3 tries | Mean capped attempts | Validation clears within 3 tries |
| --- | ---: | ---: | ---: | ---: | ---: |
| Timing heuristic | 19.7% | 0/9 | 0/9 | 3.00 | 0/3 |
| PPO top-K | 38.2% | 0/9 | 4/9 | 2.67 | 1/3 |
| PPO masked set | 51.9% | 4/9 | 4/9 | 2.11 | 0/3 |

The initial top-K checkpoint averaged 27.0% first-run progress with no clears. The initial set checkpoint averaged 27.7% and cleared moving geometry. Training added first-run clears on pillar gaps, gravity and speed for the set encoder. Held-out stochastic retries used the same frozen weights and fixed seeds.

Each cell below gives first-run progress, capped outcome, and attempts counted. The practice budget and usage were zero for every drill. The separate retry costs are recorded in the JSON by drill.

| Held-out drill | Timing heuristic | PPO top-K | PPO masked set |
| --- | --- | --- | --- |
| Single spike | 10.0% / fail / 3 | 10.0% / fail / 3 | 10.0% / fail / 3 |
| Double spike | 10.5% / fail / 3 | 10.5% / fail / 3 | 10.5% / fail / 3 |
| Triple spike | 10.0% / fail / 3 | 99.1% / fail / 3 | 10.0% / fail / 3 |
| Block steps | 8.9% / fail / 3 | 10.0% / clear / 3 | 10.0% / fail / 3 |
| Pillar gaps | 24.8% / fail / 3 | 99.1% / clear / 2 | 100.0% / clear / 1 |
| Yellow orb | 26.3% / fail / 3 | 28.2% / fail / 3 | 27.0% / fail / 3 |
| Gravity portal | 33.5% / fail / 3 | 33.7% / clear / 2 | 100.0% / clear / 1 |
| Speed change | 25.2% / fail / 3 | 25.2% / fail / 3 | 100.0% / clear / 1 |
| Moving geometry | 27.9% / fail / 3 | 27.9% / clear / 2 | 100.0% / clear / 1 |

| Agent | Extra full starts | Simulated ticks | Agent decisions | Wall time (s) |
| --- | ---: | ---: | ---: | ---: |
| Timing heuristic | 18 | 14,028 | 3,516 | 1.18 |
| PPO top-K | 15 | 31,826 | 7,964 | 10.12 |
| PPO masked set | 10 | 5,396 | 1,354 | 1.28 |

## Recommendation and limits

Carry top-K forward provisionally for the capped-clear objective because it won 1–0 on the separate validation pool. Retain the set checkpoint as the zero-shot comparator. The set encoder had stronger held-out first-run results, with the same number of capped clears. The validation pool has three fixtures and this comparison used a single model seed, so the architecture choice is provisional. Use additional seeds and new validation layouts before tuning further or declaring a winner.

Both PPO agents failed the held-out single spike, double spike, and yellow orb. These results locate failure regions and do not isolate a bridge field, exploration, or control cadence as the cause. The yellow orb is the clearest diagnostic target. Inspect activation windows, buffered input, and whether the orb remains actionable in a controlled trace before requesting bridge changes. Verified tapes establish reachability with tick-level edges. Their success at the policy's four-tick cadence was not measured.

The live run completed, all 39 local tests passed, and the launcher-owned game was closed. No commits were made.

## Diagnosis

The updated bridge completed every held-out single-spike, double-spike, and yellow-orb tape on all four k=4 phases. The original single-tick pulses were rounded to the nearest phase boundary and held for at least one decision. All phases cleared at ticks 4,144, 3,936, and 3,867 respectively, with no finish wait. A four-tick action grid can solve all three layouts. The baseline runner now uses the bridge's tick-driven completion.

The first spike survived top-K selection in every sampled observation before the no-input deaths. It was first in both layouts, with one unmasked object and no truncation. In the closest sampled train and held-out observations, the raw gaps were approximately 19.0 and 20.1 units. The normalized gaps were 0.0211 and 0.0224. Width and height were 6 and 12 units in both layouts, with corresponding features of 0.00667 and 0.01333. Full vectors and raw fields are in build/m3-diagnose/diagnosis.json.

The orb probe found an input-history distinction. Holding continuously from takeoff gave no boost. A new press during overlap boosted at tick 899 on train and 1,056 on held-out. A new press five ticks before overlap also boosted at entry when held through, while the same early pulse released after one tick did not. Immediately before overlap, the sampled player fields and orb geometry matched exactly between the continuously held and recently re-pressed cases. The next tick differed, with vertical velocity jumping to 11.18 only in the latter. The current observation cannot distinguish the two input histories. The native follow-up asks for a verified pending orb-press flag.

The checkpoint check used three frozen-policy attempts per checkpoint and drill. The first run was deterministic. The table gives first-run progress across the three checkpoints and the clear count over each set of attempts. The saved study has no continuous train-episode histories, so these are checkpoint snapshots.

| Train drill | PPO setup | Initial progress / clears | Round 1 | Round 2 |
| --- | --- | --- | --- | --- |
| Single spike | Top-K | 8.5% / 0 | 8.5% / 0 | 8.5% / 0 |
| Single spike | Masked set | 8.5% / 0 | 56.1% / 0 | 56.1% / 0 |
| Double spike | Top-K | 9.6% / 0 | 9.6% / 0 | 9.6% / 0 |
| Double spike | Masked set | 9.6% / 0 | 10.5% / 0 | 10.5% / 0 |
| Yellow orb | Top-K | 22.0% / 0 | 22.0% / 1 | 23.7% / 0 |
| Yellow orb | Masked set | 22.0% / 0 | 23.9% / 0 | 23.9% / 0 |

The spike results show a failure to reliably solve the training variants as well as the held-out variants. They do not isolate exploration, data balance, or an optimizer setting as the cause. The existing heuristic's 0.08-second lead died at the first spike. A 0.12-second lead chosen on the train variants reached 99.1%, then died on the final solid tile because the heuristic only considered hazards. The updated heuristic targets solid blocks that intersect the cube's centre height. It cleared the affected single- and double-spike drills on both splits at k=4. It still died at 24.0% train and 28.3% held-out on the yellow-orb drill. The heuristic fix was confirmed without updating PPO weights. The historical baseline table above retains its original values.

All 40 local tests passed. The launcher-owned test window was closed before releasing the runtime. Per-phase outcomes, orb traces, encoder dumps, checkpoint scores, and heuristic reruns are in build/m3-diagnose/diagnosis.json.
