# Handoff: catch-up for when Codex's usage refills (attempt logging, M5c search teacher)

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: pending (waiting for Codex usage to refill; the user will start it)
Related: tasks/M5c-search-teacher.md, gdbot/attempts.py, tools/site/backfill_attempts.py, tasks/M5b-official-transfer.md (Claude finished your write-up)

## What changed while you were out
1. **M5b was written up and closed by Claude** from your completed report. Your route encoder gave 19→22/27 on drills, but real levels didn't move (official 2–8%, online 0/10).
2. **M5c search teacher** (`tools/m5c/solver.py`, Claude): a deterministic checkpoint search finds level clears with no human input. Every clear is verified by a clean run from 0% with practice off.
   - **Verified so far:** Stereo Madness (20,899 search evaluations) and Polargeist (41,286). Back on Track, Dry Out and Base After Base are running.
   - **Restore exactness:** a GD practice-checkpoint restore is *not* exact if the bot presses immediately after it (the press is buffered; ship vy/y/rot drift). One released warm-up decision after the restore makes it exact: 0/107 mismatches vs 36/197 (`tools/m5c/restore_probe.py`). **Use this in any checkpoint practice code**, including the M4/M5 practice loop: checkpoint one released decision before the point you want, and replay that decision after every restore.
   - New bridge op `step_seq` (docs/PROTOCOL.md): a whole action list in one round trip, with no objects in the reply.
3. **Attempt logging (the user asked for it on both dashboards).**
   - `gdbot/attempts.py` keeps a per-level ledger of normal attempts (full runs from 0%, practice off) and practice attempts (checkpoint resets) in `build/attempts/`.
   - `tools/site/backfill_attempts.py` rebuilds it nightly from the M4/M5/M5b/M5c reports.
   - It shows in the ChatGPT Site ("Attempts by level", your `site/`) and in the Claude artifact dashboard.

## Request
1. **Every runner you write from now on records attempts.** Use `gdbot.attempts.from_result`/`row` + `write`, or add your report to `backfill_attempts.py`. Normal and practice attempts must be counted separately.
2. **Next study: expert iteration on the search clears** (`tools/m5c/expert.py`, written but not yet run).
   - Clone on the 27 drill demos plus the verified official clears.
   - Then score zero-shot on official 1–5 and the frozen online set, against the M5b route baseline (online 4.8% first-run, 0/10).
   - If it helps, iterate: the policy orders the search's candidates, and evaluations per level should fall across generations ("fewer attempts on harder levels").
3. Mind RAM. A background run was killed for low memory at 2.2 GB free. The solver is resumable now (`*.progress.json`); keep any long runner resumable too.

## Constraints
- Claim `RUNTIME:gd-2.2091/slot<N>`. Claude uses slot 0.
- Don't edit `mod/`, `injector/`, or `docs/PROTOCOL.md`. Claude commits.

## Response — [recipient/session, UTC]
