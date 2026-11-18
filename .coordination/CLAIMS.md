# Temporary Edit Claims

**Important:** These entries are cooperative reservations, not enforceable or atomic file locks. Two sessions can race while claiming files.

## Active claims

| Agent/session | Paths (exact files preferred) | Task | Claimed at (UTC) | Expected release | State |
| --- | --- | --- | --- | --- | --- |
| None | — | — | — | — | — |

**Game runtime:** only one client can drive GD at a time. Claim it as the pseudo-path `RUNTIME:gd-2.2091` (meaning the GD process and its pipe) before launching `gdbot-launch.exe`, and release it when the game is closed.

## Claim procedure

1. Read this table immediately before editing.
2. Check for exact-path and parent-directory overlaps.
3. Add your row, save, then reread the table to catch visible conflicts.
4. If there is any conflict or uncertainty, stop and coordinate before editing.
5. After completing or pausing work, remove your row and update the task/handoff.
6. Do not clear another session's row without confirmation from that session or the user.

## Resolved conflicts / transfers

None.
