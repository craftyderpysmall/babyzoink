# Temporary Edit Claims

**Important:** These entries are cooperative reservations, not enforceable or atomic file locks. Two sessions can race while claiming files.

## Active claims

| Agent/session | Paths (exact files preferred) | Task | Claimed at (UTC) | Expected release | State |
| --- | --- | --- | --- | --- | --- |
| claude/m6-resume-02 | RUNTIME:gd-2.2091/slot2, build/m6-scale/solutions/, build/m6-scale/supervise-slot2.* | #19 resume (user request) | 2026-11-19 | when #19 pauses or finishes | active |

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
