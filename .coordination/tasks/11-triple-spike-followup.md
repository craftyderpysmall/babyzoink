# #11 Triple spike follow-up (claude/m6-resume-02, 2026-11-19)

Script: `tools/m5b/triple_seeds.py --slot 1`. Report: `build/m5c-expert/triple-seeds/report.json`.
Held-out drill: `drill:triple-spike/heldout-2102`, 3 attempts per arm. Clones are top-K BC on the 27 route drill demos plus the official search demos (main 1-3). "with-search" also adds the verified 1,036-decision search tape from train-1102.

## Seed robustness (dedicated mode)

| Clone seed | Control: first / best / clears | With search tape: first / best / clears |
| --- | --- | --- |
| 2357 (Codex, #17) | 10.0% / 25.5% / 0 of 3 | 99.1% / 100% / clear on attempt 3 |
| 1207 | 10.0% / 42.0% / 0 of 3 | 11.6% / 11.6% / 0 of 3 |
| 3907 | 40.5% / 42.0% / 0 of 3 | 11.7% / 11.7% / 0 of 3 |

**Finding:** the seed-2357 clear does not generalize. On seeds 1207 and 3907 the search tape makes things worse: every attempt dies at x≈615-631 (the first spike group), where the control reaches x≈2,200. A single tape, about 3% of the ~30k cloning samples, moves the policy's timing at the first group without teaching the three-press pattern. Triple spike stays unsolved by learned policies. Likely fixes: several search tapes from triple-spike variants (M6 drill solves give these), or DAgger labels at the policy's own failure states (#20 tooling).

## Trainer throughput, dedicated vs background (seed 2357 with-search clone, 3 eval runs)

| Mode | Clone samples/s | Clone wall / CPU s | Eval ticks/s |
| --- | --- | --- | --- |
| dedicated | 1,009 | 30.2 / 235 | 2,000 |
| background | 772 | 39.5 / 78 | 879 |

Background mode keeps 77% of the cloning speed for one third of the CPU time (2 torch threads). The environment runs at 44% (below-normal priority, 4 threads, 6 ms bursts). Caveat: slot 2 was running the M6 #19 solver at the same time, so absolute numbers are lower than an idle machine; the ratio is what matters. No user override was active.

State: done. STATUS row 11 is held by Codex's STATUS.md claim (#27); update it to "done" when that claim is released.
