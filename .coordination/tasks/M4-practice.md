# M4 practice curriculum

Status: complete (codex/m4-practice-01).

## Frozen comparison

- Use the nine existing held-out drill revisions, the three M3 behavior-cloning seeds 1207, 2357 and 3907, top-K observations, and four ticks per action. Reload the matching BC checkpoint for every level and arm. Both arms use the M3 deterministic first attempt and fixed-seed stochastic retries, with at most three full attempts.
- The control repeats full attempts with frozen weights. The practice arm uses the frequency of 60-unit death-x bins to choose a hotspot. It replays the failed prefix and creates a checkpoint before the hotspot. Each restore replays the first action to rebuild measured horizontal velocity and the encoder's object history. Verification compares the restored position, subsequent policy observations and terminal decision to the failed run. If that check diverges, trial resets replay the original prefix from zero. Each round searches up to 36 small shifts or extra presses around the failed timing. A successful demonstration must cross 155 units beyond the hotspot or finish. Near the end it must finish, and a verified finish moves the anchor 100 units earlier if the hotspot recurs.
- Re-clone after each successful practice section using the original training demonstrations plus successful sections from that level only. Archive local practice demonstrations and clean completion runs separately by seed and level. Only completion on the original level after an explicit zero reset counts as a clear. No held-out tapes supply actions.
- Ship the start-position builder for independent synthetic variants. Live preflight checks X, mode, speed, gravity and mini state at reset and after four ticks. The moving-geometry drill is flagged as trigger-dependent and the comparison uses checkpoints or prefix replay on the original levels throughout.
- The comparison measures the combined effect of local timing search, checkpoints and re-cloning. It records actual practice cost, including parity checks, fallback prefixes and clone time. Adding practice gives the treatment additional game and compute budget within the same three full-attempt cap.

## Reproduction

Use the isolated bridge launched through `gdbot-launch.exe`. Run `build/gdbot-venv/Scripts/python.exe tools/m4/practice.py --pid <launcher-owned PID> --output build/m4-practice/paired`. The report includes the frozen fixture and model hashes and per-attempt results. Local demonstrations are compressed NumPy archives in the output directory.

## Live results

All 27 pairs finished. The frozen control reproduced the original M3 BC first-attempt terminal and tick and capped solve result in all 27 cases.

| BC seed | Clean clears with frozen BC | Clean clears with practice |
| --- | ---: | ---: |
| 1207 | 6/9 | 7/9 |
| 2357 | 7/9 | 8/9 |
| 3907 | 6/9 | 8/9 |
| Total | 19/27 | 23/27 |

- Mean full attempts to clear, counting unsolved pairs at the three-attempt cap, fell from 1.63 to 1.48. Practice flipped block steps (seed 1207), gravity portal (2357 and 3907), and pillar gaps (3907), all on the second clean attempt. Triple spike stayed unsolved on every seed. No pair lost a clear.
- Practice used 235 extra resets, 34,839 physics ticks, and 8,818 transitions. Search and reset time was 3.43 s and re-cloning took 18.76 s. Full runs used 94,959 ticks and 52.93 s in the control versus 103,165 ticks and 53.84 s with practice. These times sum measured operations across all pairs and exclude scene load and quit overhead.
- All 13 checkpoint restores passed policy-observation suffix verification after the warm-up decision. Five successful practice sections added 300 local demonstration decisions to 8,848 original training decisions. No death fell into the near-end window in this sample. The backward expansion rule passed its unit test. The final comparison used no prefix fallback.
- The live start-position preflight reset the original to x=0, the standard cube variant to x=420, and the fast mini ship with flipped gravity to x=750. Their mode, speed, gravity and mini state persisted four ticks after reset. Native bridge SHA-256 was `ae822e983b2d516cea95511324607c931043dd99777b8c882555f500311c23c5`.
- The final report is `build/m4-practice/paired/report.json`. The 24 compressed demonstration archives use 617,548 bytes in total, including clean full-run demonstrations. Python tests passed (47), and the launcher-owned game closed on completion.
