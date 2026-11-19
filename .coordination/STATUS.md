# Coordination Status

Last updated: 2026-11-19 (codex/m6-guided-02): #20, #21 and #30 complete; #21 curve deployed privately

## Codex task queue

Claude coordinates and delegates. The user runs a monitor that starts Codex on this queue.

**Codex procedure:**
1. Read AGENTS.md, then take the **first `queued` row** in this table.
2. Set that row's state to `in progress (codex/<session>)`.
3. Claim the paths the handoff lists in CLAIMS.md. If you need the game, also claim `RUNTIME:gd-2.2091`.
4. Do the work. Write your result in the handoff's Response section.
5. Set the row's state to `done` (or `blocked: <reason>`), release your claims, and stop.

**To reach Claude** (bridge bugs, protocol changes, questions): write `handoffs/<date>-codex-to-claude-<topic>.md` with `To: claude` and `Status: pending`. Claude's monitor picks it up automatically. Bridge changes (`mod/`, `injector/`, `docs/PROTOCOL.md`) always go through Claude.

**Open rows:** whenever either agent finds an issue or something unoptimized, it adds a row with state `open` (both monitors report it). Whoever is free takes it: set the state to `in progress (<agent>/<session>)`, then continue as above. Take your own `queued` rows first.

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
| 11 | Triple spike: why no agent clears it; trainer throughput in background mode | (claude, no handoff) | yes | done (claude): search tape does not generalize (0/3 at seeds 1207, 3907); background keeps 77% clone speed at 1/3 CPU; see tasks/11-triple-spike-followup.md |
| 12 | Parallel GD instances: per-instance pipe, discovery and save dir (M7) | (claude, no handoff) | yes | done (claude): 12/12, identical traces, 2x throughput; root cause of stalls was fullscreen auto-minimize (now windowed) |
| 13 | ChatGPT Sites dashboard: static site + per-mode performance rating (survival-hazard IRT anchored to GDDL) | handoffs/2026-11-19-claude-to-codex-site-dashboard.md | no | deployed privately with real telemetry |
| 14 | M5b official-level transfer: diagnose why it dies <6% on official 1-5, fix, then learn official levels by practice; held-out = downloaded online levels | handoffs/2026-11-19-claude-to-codex-m5b-official-transfer.md | yes (slot 1) | done (codex study, claude write-up): route encoder 19->22/27 drills; official 2-8%, online 0/10 |
| 15 | (small, do between #14 runs) Patch slot 1's bot save for windowed display; relaunch on the new bridge | handoffs/2026-11-19-claude-to-codex-display-fix.md | no | done (claude): slot 1 save patched while closed |
| 16 | M5c search-based teacher: deterministic segment search finds verified clears without humans; then expert iteration (BC on search clears) | tasks/M5c-search-teacher.md | yes (slot 0) | done (claude): Stereo Madness, Back on Track, Polargeist verified; #18 advanced Dry Out and Base After Base without full clears |
| 17 | Codex takes over: deploy ChatGPT Site, finish M5c solves (official 2/4/5), expert iteration, attempt logging, triple-spike follow-up | handoffs/2026-11-19-claude-to-codex-catchup.md | yes (slots 1+; slot 0 after Claude releases) | done (items 1/3/4/5); two full clears still pending under #16 |
| 18 | Finish addenda: site front-page performance summary (redeploy) + Dry Out solver stall | handoffs/2026-11-19-claude-to-codex-site-performance.md, handoffs/2026-11-19-claude-to-codex-dryout.md | Dry Out: yes | done: Overview deployed; both original stalls passed and longer prefixes saved; full clears still pending under #16 |
| 19 | M6 search-teacher data at scale: ~60 online training levels + all drill variants solved in parallel slots; scaling curve (held-out vs # solved levels) | handoffs/2026-11-19-claude-to-codex-m6-scale.md (B) | yes | in progress (claude/m6-resume-02): resumed on slot 1 by the user; one slot only (RAM ~1.7 GB free) |
| 20 | DAgger with the search teacher (label states the policy visits) | handoffs/2026-11-19-claude-to-codex-m6-scale.md (C) | yes | done: 729 evaluations per arm; final DAgger 11/27 drills vs expert 10/27, both 0/10 online |
| 21 | Fewer-attempts curve: policy-guided search, evaluations per new level across generations | handoffs/2026-11-19-claude-to-codex-m6-scale.md (D) | yes | done: final policy 3/5 vs unguided 2/5; no fall across generations on common clears; curve deployed |
| 22 | Solver stalls on Dry Out (x≈1,370) and Base After Base (x≈10,150): find what the candidate set / 4-tick grid / backtrack depth misses (`snapshot` at the saved prefix), fix, resume both (`--level main:4 --level main:5`) | handoffs/2026-11-19-codex-to-claude-dryout-claim.md (response) | yes | done with #18: original stalls passed; Dry Out and Base After Base remain uncleared |
| 23 | (claude) Bridge throughput for M6: skip rendering in dedicated mode (the plan's draw-skip, never built) and measure ticks/s and CPU per slot; verify step_seq/trace parity with drawing off | (claude) | yes | done (claude): `set_render` opt-in draw-skip, +7-9% on step_seq, parity identical; see handoffs/2026-11-19-claude-to-codex-bridge-perf.md |
| 24 | (claude) RAM per GD slot: low-detail and texture settings in the bot saves (`tools/gd_save.py`), measure working set per slot, so M6 can run more parallel slots (a run was killed at 2.2 GB free) | (claude) | yes | done (claude): 450-800 MB WS / 630-960 MB private per slot on the largest online levels; texQuality=1 saves 80-115 MB with identical physics (slots 0/2/3 set; slot 1 when closed) |
| 25 | (claude) Dashboards: check that the Claude artifact's "Attempts by level" renders after the 8:20 pm routine; once the user confirms the ChatGPT Site works for them, ask before retiring the Claude artifact + routine | (claude) | no | done (claude): attempts data has 70 rows with every field the table reads |
| 26 | (claude) Coordinator: review and commit Codex's #18-#21 results, keep `docs/progress.json` current, check for GD updates (stay on 2.2091 unless the user says otherwise) | (claude) | no | done (claude): Codex's #18/#19 work committed (bee0d77) |
| 27 | Independent safety review (pass 1 alone, then cross-check vs #28): memory/storage leaks, unsafe or dangerous code, whole repo | handoffs/2026-11-19-claude-to-both-safety-review.md | optional | done: 13 first-pass findings and Claude cross-check recorded; targeted regression suites 12/12 |
| 28 | (claude) Independent safety review, same handoff as #27 (pass 1 alone, then cross-check) | handoffs/2026-11-19-claude-to-both-safety-review.md | optional | done (claude): review + cross-check written; fixes are open rows #33-#44 |
| 29 | M6 slot-memory mitigation in `tools/m6/solve_pool.py`: save + relaunch the slot above about 1.6 GB private or below 1.5 GB free system RAM, one fresh launch per level; then resume #19 | handoffs/2026-11-19-codex-to-claude-m6-slot-memory.md (response) | yes | done (claude): solve_pool --max-private-mb/--min-avail-mb (exit 75) + tools/m6/supervise.py relaunch-and-resume |
| 30 | ChatGPT Site: add a Job queue section (every numbered job, owner, status, progress), generated from STATUS.md in the nightly data build; redeploy | handoffs/2026-11-19-claude-to-codex-site-jobs.md | no | done: all 30 jobs rendered; private Site deployed; nightly export reads STATUS.md |
| 31 | M6 online solver stalls: why online searches use the whole 6,000-evaluation budget (Dark Paradise, Stageix stuck at one point; others backtrack), fix solver | handoffs/2026-11-19-claude-to-codex-online-stalls.md (#31) | yes (slot 1) | done (claude/stalls-04): stalls are 2+ segments deep (Dark Paradise) or need finer timing (Stageix); solver stall escape added: Dark Paradise x 1,642 -> 9,369, Stageix verified clear; tools/m6/stall_probe.py + watch.py (1x) |
| 32 | Triple spike with 3-5 search tapes across 3 clone seeds (follow-up to #11) | handoffs/2026-11-19-claude-to-codex-online-stalls.md (#32) | yes | done: three verified tapes; 0/9 triple clears in both arms; other drills 25/78 multi-tape vs 29/78 control |
| 33 | Memory guard checks every N evaluations / 30 s (not only on `x=` lines) in solve_pool + guided; regression case where x never advances (review #27/#28, high) | reviews/2026-11-19-safety-review-claude.md | yes | done (claude/coord-03): solve_pool.guard_evaluations checks memory at least every 15 s of evaluations (solve_pool + guided); tests/test_memory_guard.py; live on #19 |
| 34 | Verified process kills: supervise.py / instances_test.py / fresh_slot check exe path + creation time + slot before taskkill, verify exit; mute_gd.ps1 matches only the bot exe (review #27/#28, high) | reviews/2026-11-19-safety-review-claude.md | yes | done (claude/coord-03): gdbot.instances.owned_pid/stop_slot verify exe path + creation time before taskkill and confirm the exit; supervise, instances_test and mute_gd.ps1 use them; tests/test_instances_owned.py |
| 35 | Network isolation fails closed: launcher verifies the GDBot firewall rule for the actual exe path, or the bridge blocks curl_multi_perform too (bridge: Claude reviews) (review #27/#28, medium) | reviews/2026-11-19-safety-review-claude.md | no | open |
| 36 | Pipe robustness: heartbeat watchdog in supervise (no log bytes ~10 min + idle GD -> restart slot), per-user pipe DACL, debug_peek behind a flag, request-id-safe error path (bridge: Claude reviews) (review #27/#28, medium) | reviews/2026-11-19-safety-review-claude.md | yes | open: supervisor watchdog done (claude: hung = no worker output 10 min AND GD CPU <1 s over 5 min -> restart slot; tests/test_supervise_watchdog.py). Still open, bridge (Claude reviews): pipe deadlines, per-user DACL, debug_peek flag, request-id-safe error path |
| 37 | gdbot/sections.py: parallel writers lose each other's boundaries; serialize read-merge-write, unique temp names, test with two writers (review #27/#28, medium) | reviews/2026-11-19-safety-review-claude.md | no | done: writes use a shared file lock and atomic replacement; concurrent writers share stable section IDs |
| 38 | Solver resume: persist candidate frontier (don't repeat rejected candidates); make rebuild a loop not recursion (coordinate with #31) (review #27/#28, medium) Evidence 2026-11-19: boo resumed at segment 151 / 1,406 evals, ran 18 min, and after a restart resumed at 151 / 1,410 evals: stall work between anchors is not saved, so every restart throws it away. | reviews/2026-11-19-safety-review-claude.md | no | open |
| 39 | Solver efficiency: replace full 0% replay every 16 commits (O(n^2), 35M ticks on Skill Gotten Gains) with checkpoint-based anchoring; measure ticks/segment (coordinate with #31) (review #27/#28, medium) | reviews/2026-11-19-safety-review-claude.md | no | open |
| 40 | Size limits on level downloads, decompression and cached level data before native load (gdbot/levels/online.py, tools/m6/pool.py, tools/site/gddl.py) (review #27/#28, low) | reviews/2026-11-19-safety-review-claude.md | no | done: bounded HTTP and level decoding; Python bridge rejects oversized inputs; all 71 cached levels verified |
| 41 | tools/gd_save.py: atomic write + .bak + refuse while the slot's GD runs; bridge init checks save dir creation (bridge: Claude reviews) (review #27/#28, low) | handoffs/2026-11-19-codex-to-claude-save-path-init.md | no | waiting: Python save editor and offline tests complete; native path checks handed to Claude |
| 42 | Retention: rotate bridge.log (>5 MB -> .prev), supervisor logs and power samples; nightly_refresh.ps1 checks every git command, unique index path, allowlisted diff (review #27/#28, low) | handoffs/2026-11-19-codex-to-claude-native-hardening.md | no | open: nightly Git checks and supervisor rotation done; native rotation and power-sample retention remain |
| 43 | Skill Gotten Gains: confirm cause of stationary committed segments and add a no-progress detector (review #27/#28, low) UPDATE 2026-11-19 23:10: from segment 5,571 to 7,554 x stayed at exactly 24,819.39 (player not moving at all). First check whether the player reached the level end and the bridge missed the completion (g_end_reached via playEndAnimationToPos may not fire for this level type); watch it with tools/m6/watch.py. | handoffs/2026-11-19-codex-to-claude-solver-resume.md | yes | waiting: 5,429 exact stationary segments verified at x 24,819; pinned replay needs RAM and shared solver changes need review |
| 44 | Pin native dependency hashes in mod/CMakeLists.txt; trusted-checkpoint policy for study CLIs (review #27/#28, low) | reviews/2026-11-19-safety-review-claude.md | no | open |
| 45 | Review the M8 plan (human view: 1x watch + overlay hotkeys + launch defaults; CBF sub-tick input), rounds 1 and 2 | handoffs/2026-11-19-claude-to-codex-m8-round2.md | no | done: both agents agreed; implementation acceptance checks recorded |
| 46 | (claude) M8 bridge + overlay UI (front end is Claude's per user): hotkeys Ctrl+Alt+V (1x watch) / Ctrl+Alt+O (overlay), view.json, launch defaults (dedicated, overlay on), overlay node, resumable step/step_seq, set_overlay op | plans/2026-11-19-m8-human-view-and-cbf.md | yes | implemented (claude, c02f929): 1x watch, overlay UI, V/O hotkeys + hand-over, view.json, --session fresh|keep, set_overlay; smoke 6/6; Codex review + session/perf/parity tests: handoffs/2026-11-19-claude-to-codex-m8-46-review.md |
| 47 | M8 CBF review + tests (codex): review Claude's bridge CBF (same core mechanism as upstream CBF v1.5.0), f=0 and onset-shift tests, input_timing labels on the Site (past results = without CBF) | plans/2026-11-19-m8-human-view-and-cbf.md | yes | queued: CBF bridge landed (a9a0a2c, smoke 7/7); review + slope/orb/wave/ship/moving/dual fixtures: handoffs/2026-11-19-claude-to-codex-m8-cbf.md |
| 48 | M8 CBF always on (user rule; CBF's core mechanism, not an exact port): bridge split-step + fracs (claude); solver sub-step fractions at stalls (codex); past results labelled without CBF, not re-verified | plans/2026-11-19-m8-human-view-and-cbf.md | yes | bridge part done (claude, a9a0a2c): frac/fracs, split update, vanilla CBS/COS forced off; queued for Codex: solver fractions at stalls + input_timing records (same handoff) |
| 51 | Solver stall escape: each failed escape rebuilds from 0% (a full prefix replay) and each try replays the prefix from 0%; on very long levels (Skill Gotten Gains, 5,234 segments) use the newest checkpoint at or below depth-b instead | handoffs/2026-11-19-claude-to-codex-online-stalls.md | yes | open |
| 49 | Dashboard export fails on the new `open` queue state. Support open rows and verify the real queue exports successfully. | reviews/2026-11-19-safety-review-codex.md | no | done: exports open jobs as unassigned; real queue and regression test passed |
| 50 | Eliminate the remaining slot cleanup race by verifying and terminating through the same process handle. Follow-up to #34. | handoffs/2026-11-19-codex-to-claude-process-cleanup-review.md | no | done: verified Windows handle covers identity, termination and exit; offline tests passed |

## Where we stopped (2026-11-19, read this first)

- **Headline:** the M5c search teacher clears official levels with no human input, each verified by a clean 0% run. Stereo Madness, Back on Track and Polargeist are solved (`build/m5c/main_1.json` through `main_3.json`). Dry Out and Base After Base: see `build/m5c/main_{2,4,5}.json` and `*.progress.json`. The solver resumes and skips solved levels.
- **The trained policy still can't play real levels** (best 7.6% on official, 0/10 online). Expert cloning gave 0/5 official and 0/10 online clears; adding a training search tape cleared the unseen triple-spike drill on attempt 3.
- **Handoff #17 is complete for Codex items 1, 3, 4 and 5.** The #17 response records the dashboard URL and experiment results. The subsequent #18 diagnostics advanced the remaining two official searches and saved resumable prefixes.
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
| codex | Job queue on the ChatGPT Site | handoffs/2026-11-19-claude-to-codex-site-jobs.md | completed, private deployment verified |
| codex + claude | Two independent safety reviews (#27, #28) | handoffs/2026-11-19-claude-to-both-safety-review.md | completed, both independent reviews and cross-checks recorded |
| codex | Online solver stalls (#31) + multi-tape triple spike (#32) | handoffs/2026-11-19-claude-to-codex-online-stalls.md | completed, results recorded for both jobs |
| codex | Review M8 plan round 1 (#45) | handoffs/2026-11-19-claude-to-codex-m8-plan-review.md | completed |
| claude | Respond to M8 plan review and send revision for confirmation | handoffs/2026-11-19-codex-to-claude-m8-round1.md | pending |
| codex | Confirm revised M8 plan, round 2 | handoffs/2026-11-19-claude-to-codex-m8-round2.md | completed, agreed |
| claude | Critique process-handle cleanup before #50 implementation | handoffs/2026-11-19-codex-to-claude-process-cleanup-review.md | completed, reviewed and implemented |
| claude | Review or take native save-path initialization checks for #41 | handoffs/2026-11-19-codex-to-claude-save-path-init.md | pending |
| claude | Coordinate native safety follow-ups #35, #36, #42 and #44 | handoffs/2026-11-19-codex-to-claude-native-hardening.md | pending |
| claude | Review stationary suffix evidence and shared solver resume, anchoring, and escape changes | handoffs/2026-11-19-codex-to-claude-solver-resume.md | pending |
| claude | CBF contract probe available for the revised bridge | handoffs/2026-11-19-codex-to-claude-cbf-probes.md | pending |
| codex | Bridge rebuild: draw-skip, window colours, quit crash warning | handoffs/2026-11-19-claude-to-codex-bridge-perf.md | info |
| claude | Transfer Dry Out solver files for #18 | handoffs/2026-11-19-codex-to-claude-dryout-claim.md | completed (reassigned to Codex, #22) |
| claude | Profile memory during repeated M6 search | handoffs/2026-11-19-codex-to-claude-m6-slot-memory.md | completed (#29) |
| claude | M6 continuity if Codex becomes unavailable | handoffs/2026-11-19-codex-to-claude-m6-continuity.md | info |
| claude | Slot 1 used for both #20 and #21 | handoffs/2026-11-19-codex-to-claude-m6-policy-slot.md | pending |

## Decisions awaiting user

- Optional: review the M1 screenshots in game/2.2091/gdbot/m1_screens/ (they stand in for the in-game sign-off).

## Notes

Keep this index short. Full details belong in plan, task, or handoff files. Updates are not push notifications. The user's monitor only feeds Codex from the queue above.
