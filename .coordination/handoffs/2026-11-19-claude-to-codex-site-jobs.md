# Handoff: job queue on the ChatGPT Site dashboard (user request)

To: codex (queue #30)
From: claude
Created: 2026-11-19
Status: pending

## Request
The user wants both dashboards to list every queued job by number with its progress. Claude added a "Job queue" section to the Claude artifact dashboard on 2026-11-19. Please do the same on the ChatGPT Site in `site/`, then redeploy.

## What to build
- A "Job queue" section with one row per numbered job in `.coordination/STATUS.md` (the "Codex task queue" table, currently #1–#29 and this #30). Columns: #, job, owner (Claude for rows marked `(claude)`, otherwise Codex), status (done / in progress / paused / queued / blocked) and progress (the state text).
- Order: in progress first, then paused or blocked, then queued, then done. Within each group, sort by number. Above the table, one line such as "23 of 29 jobs are done. Still open: #11, #19, …".
- **Generate it from STATUS.md, don't hand-copy it.** Parse the table in the script that builds `data/dashboard/site-dashboard.json` (or a sibling `jobs` key), so the nightly 8:03 pm data commit keeps it current. Claude's parser in this session was about 15 lines: rows matching `^\| \d+ \| `, last cell = state, owner by the `(claude)` marker. Reuse it if that helps.
- Text from STATUS.md is untrusted for rendering: use textContent, never innerHTML.

## Current state for reference (2026-11-19 09:00 UTC)
- Done: 23. Queued: #20, #21, #27 (safety review) and #28 (Claude's review, saved for later by the user). Paused: #11 and #19.
- #19 (M6) was paused by the user after Claude's run. Drills are 59/63 verified; online is 0 verified, with Skill Gotten Gains saved mid-search. Resume with `tools/m6/supervise.py` (see tasks/M6-scale.md) only when the user says so.

## Response
