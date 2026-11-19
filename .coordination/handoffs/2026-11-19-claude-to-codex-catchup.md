# Handoff: Codex takes over everything: deploy the ChatGPT Site, finish M5c, expert iteration, attempt logging

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: pending
Related: tasks/M5c-search-teacher.md, tasks/M5b-official-transfer.md, site/DEPLOY.md, gdbot/attempts.py, tools/site/backfill_attempts.py, tools/m5c/

The user's Codex usage has reset, and they want **Codex to handle everything from here**. Claude's session is ending. Work through the items in order. Each is its own unit, so keep the task record current after each one.

## What changed while you were out
1. **M5b was written up and closed by Claude** from your completed report. The route encoder gave 19→22/27 on drills; real levels didn't move (official 2–8%, online 0/10).
2. **M5c search teacher** (`tools/m5c/solver.py`): a deterministic checkpoint depth-first search finds level clears with no human input. Every clear is verified by a clean run from 0% with practice off.
   - **Verified:** Stereo Madness (20,899 search evaluations) and Polargeist (41,286).
   - **The rest:** see `build/m5c/main_{2,4,5}.json` and the "Where we stopped" note in STATUS.md. The solver is resumable (`*.progress.json`) and skips verified levels. Rerun it with `--slot <your slot> --level main:2 --level main:4 --level main:5 --budget 80000` for any level not yet verified.
   - **Restore exactness: important for all checkpoint code.** A GD practice-checkpoint restore is *not* exact if the bot presses immediately after it (the press is buffered; ship vy/y/rot drift). One released warm-up decision replayed after the restore makes it exact: 0/107 mismatches vs 36/197 (`tools/m5c/restore_probe.py`). Checkpoint one released decision before the point you want, and replay that decision after every restore. This applies to the M4/M5 practice loop too.
   - New bridge op `step_seq` (docs/PROTOCOL.md): a whole action list in one round trip, with no objects in the reply.
   - How the solver handles a checkpoint where advancing is impossible: it backtracks (pops it and tries the previous segment's next candidate) and re-anchors from a clean 0% replay every 16 segments. Details are in the solver's docstrings.
3. **Attempt logging (the user asked for it on both dashboards).** `gdbot/attempts.py` keeps a per-level ledger in `build/attempts/` of:
   - **normal attempts:** full runs from 0%, practice off;
   - **practice attempts:** checkpoint resets.

   `tools/site/backfill_attempts.py` rebuilds it nightly from the M4/M5/M5b/M5c reports. It's shown in your ChatGPT Site ("Attempts by level") and in the Claude artifact dashboard (the `attempts` dataset, refreshed by the 8:20 pm routine from `main/data/dashboard/attempts.json`).
4. **Display fixes in the bridge.**
   - GD runs windowed via the save's `gv_0025=1`. All slots are patched; `tools/gd_save.py <slot> set gv_0025 1` patches a slot, only while it's closed.
   - A minimize request sends GD behind other windows instead.
   - User input is ignored while a bot client controls GD.
   - The launcher loads a per-slot DLL copy.
   - There is a `snapshot` debug op for seeing the screen without bringing the window forward.

## Request (in order)
1. **Deploy the ChatGPT Site for the user.** The user authorizes it.
   - Follow `site/DEPLOY.md` with their ChatGPT Sites account (`<username>.chatgpt.sites`).
   - Point `remoteData` at `https://raw.githubusercontent.com/craftyderpysmall/babyzoink/main/data/dashboard/site-dashboard.json`. It is pushed to `main` nightly at 8:03 pm Pacific by the Windows task; single-branch repo, no other branches.
   - Keep it private unless the user says otherwise.
   - Verify the deployed URL loads, including "Attempts by level" and the Performance page.
   - Put the URL in the response.
2. **Finish M5c solves** for official levels 2, 4 and 5 (see above). **While claude/plan-01 still holds `RUNTIME:gd-2.2091` (slot 0) in CLAIMS.md, Claude's solver is running these levels and writing their `build/m5c/main_*.json` / `.progress.json`. Don't run them concurrently.** Do item 1 meanwhile. Claude releases the claim when its run ends.
3. **Expert iteration:** `tools/m5c/expert.py` is written but not yet run.
   - Clone on the 27 M5b route drill demos plus every verified official clear (official levels are train levels).
   - Score zero-shot on official 1–5 and the frozen online held-out set. Compare against the M5b route baseline: online 4.8% mean first-run, 0/10 clears.
   - If it helps, iterate: let the cloned policy order the solver's segment candidates, and measure evaluations per level across generations. Fewer evaluations is the "fewer attempts on harder levels" metric.
   - Optionally, run the solver on online held-out levels **only as a separate measurement, never as training data**.
4. **Log attempts in every runner from now on** (`gdbot.attempts`, or add your report to `backfill_attempts.py`), counting normal and practice attempts separately. Keep `docs/progress.json` current, since both dashboards read it.
5. **Triple spike follow-up** (Claude's #11, now yours).
   - Seed 1207 results are in `build/m3-triple/near/report.json`: longer BC (300 epochs) took held-out triple spike from 12% to 42% and pillar gaps to a clear; fine-scale features alone cleared everything except triple spike.
   - The search teacher clears triple spike outright, so adding search clears of drill variants as demos is the natural fix.
6. **Coordinator duties.** Claude normally commits, coordinates and writes `docs/progress.json`. Until Claude is back, you may commit and push to `main` yourself. Pull with `git pull --rebase --autostash` first, because the nightly job commits to `main`. No branches.

## Constraints
- Claim `RUNTIME:gd-2.2091/slot<N>` per game copy; slot 0 is free once Claude's claim is gone.
- Watch RAM. A background run was killed at 2.2 GB free. Keep every long runner resumable.
- Bridge (`mod/`, `injector/`) changes are allowed if needed; record them in `docs/PROTOCOL.md`.

## Response — [recipient/session, UTC]
