# Coordination Status

Last updated: 2026-11-18 (claude/plan-01) — #6 done (written up by Claude); M4 checkpoints + run modes verified live; #7 #8 queued

## Codex task queue

Claude coordinates and delegates. The user runs a monitor that starts Codex on this queue.

**Codex procedure:**
1. Read AGENTS.md, then take the **first `queued` row** in this table.
2. Set that row's state to `in progress (codex/<session>)`.
3. Claim the paths the handoff lists in CLAIMS.md. If you need the game, also claim `RUNTIME:gd-2.2091`.
4. Do the work. Write your result in the handoff's Response section.
5. Set the row's state to `done` (or `blocked: <reason>`), release your claims, and stop.

**To reach Claude** (bridge bugs, protocol changes, questions): write `handoffs/<date>-codex-to-claude-<topic>.md` with `To: claude` and `Status: pending`. Claude's monitor picks it up automatically. Bridge changes (`mod/`, `injector/`, `docs/PROTOCOL.md`) always go through Claude.

One row per run. Don't take rows marked `waiting`. If a handoff conflicts with an active claim, mark the row `blocked` and stop. Don't commit: Claude commits and pushes the repo.

| # | Task | Handoff | Needs game? | State |
| --- | --- | --- | --- | --- |
| 1 | M3 drill levels as generated level strings (Python only, steps 1–4; step 5 waits for the bridge) | handoffs/2026-11-18-claude-to-codex-m3-drills.md | no | done |
| 2 | Drills live: load every drill in GD, verify objects, find known-good tapes, set training_ready | handoffs/2026-11-18-claude-to-codex-m3-drills-live.md | yes | done |
| 3 | M2 gate re-run on the fixed bridge with objects on; bench + profile | handoffs/2026-11-18-claude-to-codex-m2-rerun.md | yes | done |
| 4 | M3 baseline: heuristic vs PPO top-K vs PPO set encoder, train drills -> held-out drills | handoffs/2026-11-18-claude-to-codex-m3-baseline.md | yes | done |
| 5 | Diagnose held-out failures (single/double spike, yellow orb): cadence, orb input, encoding | handoffs/2026-11-18-claude-to-codex-m3-diagnose.md | yes | done |
| 6 | M3 at scale: 3 seeds x 2 encoders, ~1M transitions, new validation layouts -> pick encoder | handoffs/2026-11-18-claude-to-codex-m3-scale.md | yes | done |
| 7 | M4 practice curriculum: start positions, death-hotspot drilling, clean full-run gate; measure attempts-to-clear with vs without practice | handoffs/2026-11-18-claude-to-codex-m4-practice.md | yes | queued |
| 8 | Trainer follows the user's dedicated/background toggle (threads, priority, affinity) | handoffs/2026-11-18-claude-to-codex-mode-follow.md | yes | queued |

## Active work

| Task | Agent/session | State | Plan or task file |
| --- | --- | --- | --- |
| GD learning bot: plan | claude/plan-01 + codex/gd-review-02 | agreed | plans/2026-11-17-gd-learning-bot.md |
| M0 identify and map | claude/plan-01 | done (static) | tasks/M0-identify-and-map.md |
| M1 isolated bridge (native) | claude/plan-01 | done (core) | tasks/M1-isolated-bridge.md |
| M1b objects, level_string, quit_level, Codex M2 fixes | claude/plan-01 | done: objects_test 8/9 (9th was a test expectation, fixed); real save unchanged | tasks/M1-isolated-bridge.md |
| M2/M3 Python side (mock) | codex/python-01 | done against v0 mock | tasks/M2-M3-python-mock.md |
| M2 live environment, replay and benchmarks | codex/m2-rerun-01 | fixes and measured parity passed with objects; broader coverage listed in task | tasks/M2-live.md |
| M3 drill fixtures | codex/m3-live-01 | 18 fixtures and completion tapes verified live; all training-ready | tasks/M3-drills.md |
| M3 CPU baselines | codex/m3-baseline-01 | complete; each PPO cleared 4/9 held-out within the cap | tasks/M3-baseline.md |
| M3 scaled six-run study | codex/m3-scale-01 | running; report and resume details in task record | tasks/M3-scale.md |

## Pending reviews and handoffs

| Recipient | Request | File | Status |
| --- | --- | --- | --- |
| codex | Critical review round 1 of the GD bot plan | handoffs/2026-11-17-claude-to-codex-plan-review.md | completed |
| codex | Review round 2 of the revised GD bot plan | handoffs/2026-11-18-claude-to-codex-review-round2.md | completed (agreed) |
| codex | Build M2/M3 Python side against docs/PROTOCOL.md + mock | handoffs/2026-11-18-claude-to-codex-python-side.md | completed |
| codex | M2 live: env/replay vs real bridge, parity suite, bench | handoffs/2026-11-18-claude-to-codex-m2-live.md | completed |
| claude | Fix native input state and startup readiness; M3 needs | handoffs/2026-11-18-codex-to-claude-m2-findings.md | completed (fixes verified live; Codex re-run is queue item 3) |
| codex | M3 drill levels | handoffs/2026-11-18-claude-to-codex-m3-drills.md | completed for Python steps 1–4 |
| codex | Verify all drills live and capture completion tapes | handoffs/2026-11-18-claude-to-codex-m3-drills-live.md | completed |
| codex | Re-run fixed-bridge parity and profile with objects | handoffs/2026-11-18-claude-to-codex-m2-rerun.md | completed |
| codex | Train and evaluate the M3 CPU baselines | handoffs/2026-11-18-claude-to-codex-m3-baseline.md | completed |
| codex | Diagnose spike and orb failures | handoffs/2026-11-18-claude-to-codex-m3-diagnose.md | completed |
| claude | Live-verify pending input state for orb activation | handoffs/2026-11-18-codex-to-claude-orb-diagnosis.md | pending |

## Decisions awaiting user

- Optional: review the M1 screenshots in game/2.2091/gdbot/m1_screens/ (they stand in for the in-game sign-off).

## Notes

Keep this index short. Full details belong in plan, task, or handoff files. Updates are not push notifications. The user's monitor only feeds Codex from the queue above.
