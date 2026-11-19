# Handoff: next milestones: finish the open addenda, then M6 (search-teacher data at scale), DAgger, and the "fewer attempts" curve

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: in progress (#19); #20 and #21 completed
Related: handoffs/2026-11-19-claude-to-codex-site-performance.md, handoffs/2026-11-19-claude-to-codex-dryout.md, tasks/M5c-search-teacher.md, build/m5c-expert/

## Why
Your #17 results tell us what's next:
- **Triple spike:** one search-teacher demo of its train layout took held-out triple spike from 10% to a clear. Search demos work on the content they cover.
- **Online levels:** three official clears moved the frozen online set only from 4.8% to 5.1%. That's far too little data to generalize.

So the bottleneck is **coverage**: how many and how varied the solved levels are. A second bottleneck is **distribution shift**. Cloning only expert trajectories never shows the policy how to recover from its own mistakes.

## Work, in order (each a unit; keep task records current)

### A. Finish the two open addenda (small)
1. **`handoffs/2026-11-19-claude-to-codex-site-performance.md`:** the user asked for the per-mode performance summary on the site's front page, as frontend placeholders now. Redeploy to https://babyzoink.craftyderpysmall.chatgpt.site.
2. **`handoffs/2026-11-19-claude-to-codex-dryout.md`:** the solver stalls on Dry Out at x≈1,370; diagnose and fix it. Base After Base is being solved by Claude in slot 0; check `build/m5c/main_5.json` and CLAIMS before touching it.

### B. M6: search-teacher data at scale (the main milestone)
1. **Training pool (record it in `tasks/M6-scale.md`):**
   - ~60 downloaded online levels at Easy–Insane non-demon, plus later easy demons. They must be **disjoint from the frozen 10 held-out** and spread across modes, eras and lengths. Use `python -m gdbot.levels.online`.
   - Plus every drill variant you can generate (all 18 families; more seeds per family).
2. **Solve them** with `tools/m5c/solver.py` across parallel slots (1–3), as RAM allows. Check free memory before each extra slot; the machine has 13.8 GB and a run was killed at 2.2 GB free.
   - Track solve rate, evaluations and wall time per level.
   - Fix solver gaps as they show up. Dry Out shows there are some: finer `k`, wider candidates, deeper backtracking.
3. **Expert iteration with a scaling curve:** clone on 10, 20, 40 and all solved training levels (same seed, then 3 seeds). Score zero-shot on the frozen online held-out and on official 1–5. **The headline result is held-out first-run progress and clears vs number of solved training levels.**
4. **Log everything:** attempts in the ledger, section telemetry for the mode ratings, and `docs/progress.json` rows.

### C. DAgger with the search teacher (distribution shift)
- Run the cloned policy on training levels. Wherever it dies, or every N decisions, label the states it actually visits with the teacher's action: restore a checkpoint there (with the warm-up rule) and use the solver's first committed input from that state.
- Aggregate those labels and re-clone. Compare against plain expert iteration at equal teacher cost.

### D. The "fewer attempts" curve (the project's core claim)
- **Policy-guided search:** order the solver's segment candidates by the cloned policy's action probabilities.
- For each generation, solve a fixed set of **new** levels and record the search evaluations (practice attempts) and normal attempts needed to the first clear.
- The claim holds if evaluations per level fall across generations on unseen levels.
- Put the curve on the site's placeholder chart and in the attempts ledger.

## Constraints
- **Coordination:** you coordinate and commit while Claude is away. Pull with `git pull --rebase --autostash` first; single branch `main`.
- **Game slots:** claim `RUNTIME:gd-2.2091/slot<N>` per slot. Slot 0 is Claude's until its claim is released.
- **Resumability:** keep every long runner resumable.
- **Data use:** held-out levels never supply demos or selection.

## Response — [recipient/session, UTC]

### B — Training pool ready

Codex selected and verified 59 rated classic online levels and 63 training drills. No frozen online ID or exact held-out payload overlaps the training pool. The manifests are under build/m6-scale/ and the protocol is in tasks/M6-scale.md. The sharded solve worker and nightly ledger support are in place. The drill pilot did not launch due to available RAM; resume it after the #18 diagnostics and another memory check.

### C — DAgger with matched teacher evaluations (#20)

Codex ran two rounds on four training drills from the M6 manifest, two new drills per round. Both arms started with the M5c expert clone and its archives. The control added only clean, verified search demonstrations. DAgger added 184 labels in round one and 125 in round two, including states just before death and states sampled along the rollout. It used a released checkpoint warm-up and fell back to a clean prefix replay if the observed player state disagreed. Both arms spent exactly 426 candidate evaluations in round one and 303 in round two. On yellow orb, the initial strided pass spent 232 of 272 evaluations. Sampling additional states from the same policy rollout filled the shortfall before final evaluation.

| Policy | Held-out drill first-run progress | Drill clears | Frozen online first-run progress | Online clears |
| --- | ---: | ---: | ---: | ---: |
| Starting M5c clone | 59.50% | 8/27 | 5.06% | 0/10 |
| Expert iteration, round 1 | 65.98% | 8/27 | 4.78% | 0/10 |
| DAgger, round 1 | 76.60% | 16/27 | 5.66% | 0/10 |
| Expert iteration, round 2 | 65.51% | 10/27 | 5.22% | 0/10 |
| DAgger, round 2 | 67.66% | 11/27 | 5.45% | 0/10 |

The run used one seed. DAgger's drill advantage narrowed in round two, and neither arm cleared an online level. `build/m6-scale/dagger/report.json` contains rollout-level costs, frozen level hashes, per-level scores, and the initial strided pilot. Checkpoints and label archives are in the same directory. The runner is `tools/m6/dagger.py`.

### D — Policy-guided search (#21)

The runner uses the same candidate set and search budget as unguided search. It reorders candidates by the policy's log odds at the first action that differs from a greedy forecast. The paired cohort is triple spike `heldout-2102`, ball switches `heldout-7101`, blue pad `heldout-7109`, ReTraY and Sonar. All three policy checkpoints exist. The budget is 400 candidate evaluations per level for each of the unguided, starting-policy, first-round and second-round runs. The runner records candidate evaluations, full-run verification attempts and outcomes per level, with resumable search prefixes.

```powershell
& build/gdbot-venv/Scripts/python.exe tools/m6/guided.py --slot 1 --checkpoints build/m5c-expert/official/clone.zip build/m6-scale/dagger/dagger-1.zip build/m6-scale/dagger/dagger-2.zip --levels drill:triple-spike/heldout-2102 drill:ball-switches/heldout-7101 drill:blue-pad/heldout-7109 online:6508283 online:4454123 --budget 400 --min-free-mb 850
```

The 20 paired cases finished in slot 1 once the host had 3,149 MiB available. Claude's #19 continued in slot 2. The ledger and Site exporter read `build/m6-scale/guided/report.json`. The curve compares the two levels cleared by every arm and shows the separate clear count across all five levels.

| Search | Verified clears | Mean evaluations on common clears | Mean normal attempts on common clears |
| --- | ---: | ---: | ---: |
| Unguided | 2/5 | 88.5 | 1 |
| Starting policy | 2/5 | 59.5 | 1 |
| DAgger round 1 | 2/5 | 85.5 | 1 |
| DAgger round 2 | 3/5 | 86.5 | 1 |

The round-2 policy was the only arm to reach a verified triple-spike clear, after 337 candidate evaluations and one clean run from 0%. On the two common clears, evaluations did not fall across policy generations. Neither online level cleared within budget in any arm.

Published the curve on the [private Site](https://babyzoink.craftyderpysmall.chatgpt.site/#attempts-trend-title) and verified all 20 cases in `build/attempts/m6-guided.jsonl`. The version was built while #21 was publishing. The nightly exporter will pick up the final queue state.
