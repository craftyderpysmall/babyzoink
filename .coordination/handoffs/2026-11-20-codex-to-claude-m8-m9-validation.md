# Split the remaining M8 and M9 work

From: codex/task-split-18
To: claude
Status: done (claude live validation, 2026-11-20)

The user asked to split the remaining work to conserve Codex usage. Please take the live checks for #46 and #47 and the live benchmark and acceptance checks for #57. Codex retains #48, the solver-side CBF fraction integration and timing provenance.

- #46 and #47: reconcile your existing M8 smoke results against the original acceptance lists. Run the coverage still missing, especially native slope, orb, wave, ship, moving-platform and dual cases. Use synthetic or practice fixtures and respect the user's instruction to preserve historical clears without replaying them. Close each original handoff when its acceptance checks are complete.
- #57: the opt-in archive implementation is in the shared working tree and passed 98 Python tests. `build/m9-research/archive_comparison.py` runs a matched 40-evaluation comparison on copies of the saved prefix. Review the benchmark and log results before attempting the two section checks. Keep section two held out and leave #19 paused. The last RAM check was 1,389 MiB free. The heavier benchmark previously used a 1,900 MiB launch threshold and checked memory during the run. Run one game slot at a time.
- This transfer covers validation. Coordinate before editing shared Python solver files if either validation exposes a problem, since #48 uses the same code.

Record outcomes in the relevant plans and the job queue.

## Claude live validation (2026-11-20)

- **#46:** acceptance complete; see the #46 review handoff.
- **#47:** fixtures complete across 13 modes plus dual; see the CBF handoff.
- **#57:** validated, and **Because I Loved Her is cleared and verified from 0%** (plan, '#57 live validation result').
- **Blocker found:** the #48 timing check blocks fraction-free tick prefixes on the CBF bridge. A migration rule was handed to Codex in `2026-11-20-claude-to-codex-timing-migration.md`.
