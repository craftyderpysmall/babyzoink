# Temporary Edit Claims

**Important:** These entries are cooperative reservations, not enforceable or atomic file locks. Two sessions can race while claiming files.

## Active claims

| Agent/session | Paths (exact files preferred) | Task | Claimed at (UTC) | Expected release | State |
| --- | --- | --- | --- | --- | --- |
| codex/m6-scale-01 | `tools/m6/pool.py`, `tools/m5b/transfer.py`, `gdbot/levels/online.py`, `tools/m6/solve_pool.py`, `tools/site/backfill_attempts.py`, `build/m6-scale/`, `.coordination/tasks/M6-scale.md`, `.coordination/STATUS.md`, `.coordination/handoffs/2026-11-19-claude-to-codex-m6-scale.md` | #19 training pool | 2026-11-19 06:09 | after pool validation | active |

**Game runtime:** only one client can drive GD at a time. Claim it as the pseudo-path `RUNTIME:gd-2.2091` (meaning the GD process and its pipe) before launching `gdbot-launch.exe`, and release it when the game is closed. Parallel instances: claim `RUNTIME:gd-2.2091/slot<N>` for `gdbot-launch.exe --instance N`; plain `RUNTIME:gd-2.2091` means slot 0. One client per slot.

## Claim procedure

1. Read this table immediately before editing.
2. Check for exact-path and parent-directory overlaps.
3. Add your row, save, then reread the table to catch visible conflicts.
4. If there is any conflict or uncertainty, stop and coordinate before editing.
5. After completing or pausing work, remove your row and update the task/handoff.
6. Do not clear another session's row without confirmation from that session or the user.

## Resolved conflicts / transfers

- 2026-11-19: codex/m5b-transfer-01 ran out of usage after its study completed; the user told Claude to finish up, so Claude released Codex's #14 claim (slot 1 process had already exited) and wrote the results.

None.
