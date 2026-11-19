# Coordination Status

Last updated: 2026-11-19 (codex/takeover-02): #17 items 1/3/4/5 complete; Claude retains the remaining official solves

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
| 7 | M4 practice curriculum: start positions, death-hotspot drilling, clean full-run gate; measure attempts-to-clear with vs without practice | handoffs/2026-11-18-claude-to-codex-m4-practice.md | yes | done: 23/27 clean clears with practice vs 19/27 control |
| 8 | Trainer follows the user's dedicated/background toggle (threads, priority, affinity) | handoffs/2026-11-18-claude-to-codex-mode-follow.md | yes | done (claude) |
| 9 | Fix the training recipe: behaviour cloning from verified tapes, then PPO fine-tune; compare to the scaled-study baseline | handoffs/2026-11-18-claude-to-codex-m3-imitation.md | yes | done (claude): BC 6.3/9 held-out; PPO fine-tune hurts |
| 10 | M5 curriculum: drills for every mode, a BC + self-imitation generation loop, official levels 1–5 | handoffs/2026-11-19-claude-to-codex-m5-curriculum.md | yes | done: all 54 drills verified, three generations and five official levels scored |
| 11 | Triple spike: why no agent clears it; trainer throughput in background mode | (claude, no handoff) | yes | in progress (claude) |
| 12 | Parallel GD instances: per-instance pipe, discovery and save dir (M7) | (claude, no handoff) | yes | done (claude): 12/12, identical traces, 2x throughput; root cause of stalls was fullscreen auto-minimize (now windowed) |
| 13 | ChatGPT Sites dashboard: static site + per-mode performance rating (survival-hazard IRT anchored to GDDL) | handoffs/2026-11-19-claude-to-codex-site-dashboard.md | no | deployed privately with real telemetry |
| 14 | M5b official-level transfer: diagnose why it dies <6% on official 1-5, fix, then learn official levels by practice; held-out = downloaded online levels | handoffs/2026-11-19-claude-to-codex-m5b-official-transfer.md | yes (slot 1) | done (codex study, claude write-up): route encoder 19->22/27 drills; official 2-8%, online 0/10 |
| 15 | (small, do between #14 runs) Patch slot 1's bot save for windowed display; relaunch on the new bridge | handoffs/2026-11-19-claude-to-codex-display-fix.md | no | done (claude): slot 1 save patched while closed |
| 16 | M5c search-based teacher: deterministic segment search finds verified clears without humans; then expert iteration (BC on search clears) | tasks/M5c-search-teacher.md | yes (slot 0) | in progress (claude) |
| 17 | Codex takes over: deploy ChatGPT Site, finish M5c solves (official 2/4/5), expert iteration, attempt logging, triple-spike follow-up | handoffs/2026-11-19-claude-to-codex-catchup.md | yes (slots 1+; slot 0 after Claude releases) | done (items 1/3/4/5); item 2 remains with Claude under #16 |
| 18 | Finish addenda: site front-page performance summary (redeploy) + Dry Out solver stall | handoffs/2026-11-19-claude-to-codex-site-performance.md, handoffs/2026-11-19-claude-to-codex-dryout.md | Dry Out: yes | in progress (codex/site-overview-01; Dry Out waits for claim transfer) |
| 19 | M6 search-teacher data at scale: ~60 online training levels + all drill variants solved in parallel slots; scaling curve (held-out vs # solved levels) | handoffs/2026-11-19-claude-to-codex-m6-scale.md (B) | yes | queued |
| 20 | DAgger with the search teacher (label states the policy visits) | handoffs/2026-11-19-claude-to-codex-m6-scale.md (C) | yes | queued |
| 21 | Fewer-attempts curve: policy-guided search, evaluations per new level across generations | handoffs/2026-11-19-claude-to-codex-m6-scale.md (D) | yes | queued |
| 22 | (claude) Base After Base: confirm the slot-0 solve finished (`build/m5c/main_5.json`); if not, resume it (`--level main:5`, progress file); then release the slot-0 claim and commit | (claude) | yes (slot 0) | queued (claude) |
| 23 | (claude) Bridge throughput for M6: skip rendering in dedicated mode (the plan's draw-skip, never built) and measure ticks/s and CPU per slot; verify step_seq/trace parity with drawing off | (claude) | yes | queued (claude) |
| 24 | (claude) RAM per GD slot: low-detail and texture settings in the bot saves (`tools/gd_save.py`), measure working set per slot, so M6 can run more parallel slots (a run was killed at 2.2 GB free) | (claude) | yes | queued (claude) |
| 25 | (claude) Dashboards: check that the Claude artifact's "Attempts by level" renders after the 8:20 pm routine; once the user confirms the ChatGPT Site works for them, ask before retiring the Claude artifact + routine | (claude) | no | queued (claude) |
| 26 | (claude) Coordinator: review and commit Codex's #18-#21 results, keep `docs/progress.json` current, check for GD updates (stay on 2.2091 unless the user says otherwise) | (claude) | no | queued (claude) |

## Where we stopped (2026-11-19, read this first)

- **Headline:** the M5c search teacher clears official levels with no human input, each verified by a clean 0% run. Stereo Madness, Back on Track and Polargeist are solved (`build/m5c/main_1.json` through `main_3.json`). Dry Out and Base After Base: see `build/m5c/main_{2,4,5}.json` and `*.progress.json`. The solver resumes and skips solved levels.
- **The trained policy still can't play real levels** (best 7.6% on official, 0/10 online). Expert cloning gave 0/5 official and 0/10 online clears; adding a training search tape cleared the unseen triple-spike drill on attempt 3.
- **Handoff #17 is complete for Codex items 1, 3, 4 and 5.** Claude retains the remaining official search solves under #16. The #17 handoff response records the dashboard URL and experiment results.
- **Dashboards:** the Claude artifact (https://claude.ai/artifact/KRrQvsq6WkTcYJ4kmvp7ak) is refreshed by the 8:20 pm cloud routine trig_01YAtCETwr76snKBFJWJ9VyE. The ChatGPT Site is in `site/`, fed by `main/data/dashboard/site-dashboard.json`. The Windows task "babyzoink dashboard data" commits the data to `main` nightly at 8:03 pm. The repo has a single branch (`main`).
- **Game:** GD 2.2091 bot copy in `game/2.2091` (gitignored). Launch with `mod/build/Release/gdbot-launch.exe [--instance N]`; one client per slot.

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
| M3 scaled six-run study | codex/m3-scale-01 | complete; top-K selected provisionally | tasks/M3-scale.md |
| M4 practice curriculum | codex/m4-practice-01 | complete; live start positions, checkpoint practice, paired comparison | tasks/M4-practice.md |
| M5 curriculum | codex/m5-curriculum-02 | complete; held-out clears averaged 21, 20.3, and 19 of 27; no official clears | tasks/M5-curriculum.md |
| ChatGPT Sites dashboard | codex/site-dashboard-01 | deployed privately; packaged attempts and performance views verified | tasks/site-dashboard.md |

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
| claude | Live-verify pending input state for orb activation | handoffs/2026-11-18-codex-to-claude-orb-diagnosis.md | completed |
| codex | M5 curriculum | handoffs/2026-11-19-claude-to-codex-m5-curriculum.md | completed |
| codex | ChatGPT Sites dashboard + mode ratings | handoffs/2026-11-19-claude-to-codex-site-dashboard.md | completed locally |
| claude | Restore sequential custom level loads in slot 0 so M5 can resume | handoffs/2026-11-19-codex-to-claude-m5-bridge.md | completed |
| codex | Record M5 telemetry and point the site at the public main-branch feed | handoffs/2026-11-19-claude-to-codex-telemetry.md | completed |

## Decisions awaiting user

- Optional: review the M1 screenshots in game/2.2091/gdbot/m1_screens/ (they stand in for the in-game sign-off).

## Notes

Keep this index short. Full details belong in plan, task, or handoff files. Updates are not push notifications. The user's monitor only feeds Codex from the queue above.
