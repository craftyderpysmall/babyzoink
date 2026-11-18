# Task: M2 live Python integration

Status: the fixed-bridge parity and throughput gate passed for the fixtures and conditions below. Broader M2 coverage is still open.
Agent/session: codex/m2-live-01 and codex/m2-rerun-01
Related plan: ../plans/2026-11-17-gd-learning-bot.md
Related handoff: ../handoffs/2026-11-18-claude-to-codex-m2-live.md

## Original player-only run

- Both isolated desktop launches were started by gdbot-launch.exe and closed after their runs. Both hello replies confirmed save redirection and HTTP blocking. Game PIDs were 11048 and 24516.
- Stereo Madness reset to tick 0. At k=4 the Gymnasium encoding fit its observation space, the press at ticks 61–64 raised the cube, and the next step reached tick 68. The hold/release assertion failed on both launches because the press observation still reported holding=false.
- The 404-tick tape ended in death. All 24 fixed-cadence comparisons and freeze checks passed across the two launches. This includes same-process resets, normal/dedicated/background comparison at k=1 and k=4, and fresh-launch comparisons with the PID-11048 run. An idle wait of 750 ms preserved the next tick's state in all three modes.
- Comparing k=1 against k=4 first diverged at tick 14 in players[0].vx, 1.2982501983642578 vs 1.298250675201416. Across the 404 paired rows, vx was the sole differing field. The bridge derives it from the previous observation, which changes with request grouping.
- Replay reports include terminal status from the step envelope. Native per-tick events were empty and the queue field was constant. These comparisons cannot establish trigger or queue fidelity.
- The first immediate step after the initial load/reset once returned INTERNAL because the scene did not produce ticks. The runner allows one second for the initial scene to settle. Both measured launches then advanced successfully.

## Benchmark

Windows Python 3.14.10, Stereo Madness, live bridge with objects=false. The observation stage includes host encoding, and the PPO stage includes collection and updates on CPU. No staged measurement here includes native object extraction.

| Mode | Stage | k | Ticks/s | Transitions/s | Step p50 / p95 (ms) | Reset p50 (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| normal | IPC | 4 | 236.8 | 59.3 | 16.65 / 16.81 | 32.66 |
| normal | observation | 4 | 236.5 | 59.2 | 16.68 / 16.95 | 34.52 |
| normal | PPO | 4 | 231.9 | 58.1 | 15.43 / 15.95 | 43.08 |
| dedicated | IPC | 4 | 16,373.3 | 4,103.8 | 0.06 / 0.13 | 6.85 |
| dedicated | observation | 4 | 16,269.5 | 4,077.7 | 0.08 / 0.18 | 9.97 |
| dedicated | PPO | 4 | 3,349.4 | 840.7 | 0.17 / 4.58 | 21.38 |
| background | IPC | 4 | 235.5 | 59.0 | 16.65 / 16.97 | 40.15 |
| background | observation | 4 | 236.2 | 59.1 | 16.66 / 16.91 | 36.74 |
| background | PPO | 4 | 233.6 | 58.5 | 15.54 / 15.96 | 38.67 |

Dedicated IPC at k=1 reached 7,415.8 ticks/s. Dedicated PPO at k=4 reached approximately 14× real time for this setup. All 15 benchmark cases and raw traces are in build/m2-live/first.json and build/m2-live/second.json. Each run also saved its input tape.

## Python changes and verification

- Bench, replay, and the environment share a cached level load so same-level resets work with the menu-only bridge. The mock and encoder now use native horizontal units per tick. Replay includes terminal status even when the trace row omits it.
- The runner is tools/m2/live.py. It requires the launcher-reported PID and checks that the discovery file belongs to that process. A second invocation can compare with the first report using --baseline.
- 23 local tests passed. No commits were made.

## Acceptance issues after the original run

Fix native input state and scene readiness, then re-run. Extend trace coverage to real queued inputs and trigger events. Mode switches within a replay, minimized-window parity, timing and trigger fixtures, and foreground frame-time impact were outside the measured runs. Re-benchmark with real objects before treating the dedicated result as M3 throughput.

## Fixed-bridge replay and environment checks

The rerun used two fresh launches through gdbot-launch.exe, PIDs 14516 and 13572. Both confirmed isolation. Both test processes were closed after their run.

- Gymnasium passed all 20 smoke assertions across the two fixtures and launches. The first action after load and reset advanced four ticks without a wait. The pressed and released states matched the command and the jump changed player height.
- All 60 parity and freeze checks passed on the 391-tick Stereo Madness tape and the 1,320-tick moving-geometry prefix. Normal, dedicated, and background matched. Same-process resets and fresh launches matched. The earlier k=1 versus k=4 displacement-derived vx difference was absent.
- Each comparison included the exact native per-tick player trace and object snapshots with raw UID, category, and hitbox centre and size. The bridge emits object snapshots on step replies, so the cross-cadence check compares objects at shared sample ticks. With k=1 that is one snapshot per simulated tick. The drill trace followed the full 120-unit block descent.
- The Python client clears its level cache on a successful quit_level. All 39 local tests passed.

## Fixed-bridge throughput and profiling

The rerun used the object-enabled 2.2091 bridge. The official-level tape sampled 3–14 objects per reply. The moving-drill prefix sampled up to one object, including the grouped block as it moved from Y=225 to Y=105. The PPO stage used the top-K encoder and included collection and CPU updates.

| Fixture | Stage | k | Dedicated ticks/s | Dedicated transitions/s | Step p50 / p95 (ms) | Reset p50 (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Stereo Madness | IPC | 1 | 5,308.7 | 5,308.7 | 0.08 / 0.14 | 23.24 |
| Stereo Madness | IPC | 4 | 14,820.4 | 3,714.5 | 0.09 / 0.16 | 17.51 |
| Stereo Madness | Observation | 1 | 4,806.1 | 4,806.1 | 0.10 / 0.18 | 18.58 |
| Stereo Madness | Observation | 4 | 8,627.2 | 2,162.3 | 0.11 / 0.24 | 27.18 |
| Stereo Madness | PPO | 1 | 942.1 | 942.1 | 0.19 / 4.66 | 23.26 |
| Stereo Madness | PPO | 4 | 3,143.3 | 787.5 | 0.26 / 4.70 | 24.41 |
| Moving drill | IPC | 1 | 8,722.1 | 8,722.1 | 0.05 / 0.09 | 31.17 |
| Moving drill | IPC | 4 | 20,142.6 | 5,043.6 | 0.07 / 0.12 | 25.81 |
| Moving drill | Observation | 1 | 7,131.5 | 7,131.5 | 0.07 / 0.12 | 30.29 |
| Moving drill | Observation | 4 | 18,836.8 | 4,716.7 | 0.09 / 0.15 | 21.72 |
| Moving drill | PPO | 1 | 991.6 | 991.6 | 0.16 / 4.65 | 21.42 |
| Moving drill | PPO | 4 | 3,813.7 | 953.7 | 0.18 / 4.65 | 27.16 |

Normal and background reached about 59 transitions/s across all six stage/cadence combinations on the official level. Dedicated PPO at k=4 reached about 13.1× real time on Stereo Madness and 15.9× on the moving drill. The drill figures measure throughput only. Scored training must allow the wall-clock completion callback found in the drill verification.

In the separate 2,000-step dedicated k=4 profile on Stereo Madness, the IPC trial took 0.854 s. Reads spent 0.775 s waiting for or transferring replies, JSON decoding took 0.036 s, and request packing took 0.013 s. The observation trial spent 0.061 s in the encoder out of 0.965 s. The PPO trial took 3.296 s, including 1.396 s in reads, 0.112 s decoding JSON, 0.191 s encoding, 0.929 s in policy forward passes, and 0.071 s in PPO updates. Native serialization shares the read interval with scheduling, stepping, object extraction, and pipe transfer. The measurements cannot attribute the read time to native JSON alone, so there is no evidence to prioritize a binary protocol yet.

The complete benchmark rows, capture reports, and Python profiles are under build/m2-rerun/. The pre-fix reports remain under build/m2-live/.

## Coverage still open

- Minimized-window parity, switching modes mid-replay, and foreground frame-time impact while training in background mode.
- Further trigger-heavy or dense fixtures. This rerun covers one move-trigger fixture. It does not establish parity for pending triggers, activation and queue state, or any of the four k=4 decision phases on a timing-sensitive fixture.
- Individual native scheduling, physics, object extraction, and serialization costs. The client profile measures their combined time waiting for a reply.
