# Handoff: section telemetry is ready; record it in the M5 runs and point the site at the live feed

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: completed as part of #10
Related: docs/TELEMETRY.md, gdbot/sections.py, gdbot/levels/online.py, site/DEPLOY.md

## Answers to your #13 questions
- **Stable section ids:** yes. `section` is an int, the x of the section's boundary (0 is the level start). It's learned per level in `build/telemetry/section_maps.json` and is the same for zero, checkpoint and startpos attempts.
- **`zero_shot`:** yes. `attempt_meta` only allows it on attempt 1 from zero.
- **`cleared`:** yes. It means the attempt left the section alive. A row with neither `died` nor `cleared` is censored.
- `tests/test_sections.py` loads the rows through `tools/site/rating.py:Section.from_row`.

## Request
1. **Wire `EnvTelemetry` into the M5 generation runner**, and the practice loop if it is shared (three calls; see docs/TELEMETRY.md).
   - Use level keys `drill:<family>/<variant>`, `official:<n>` and `online:<id>`.
   - Set `generation`, `seed` and `practice`.
   - Set `zero_shot` on the first held-out attempt of each generation.
   - Then the Performance page fills in from real runs.
2. **The nightly job** (20:03) now also runs `tools/site/export.py --refresh-gddl` and commits `site-dashboard.json` to **main** under `data/dashboard/` (single-branch repo: the user wants no side branches; `dashboard-data` is retired). Update `site/DEPLOY.md` to match.
   - Verified: HTTP 200 with `Access-Control-Allow-Origin: *` at `https://raw.githubusercontent.com/craftyderpysmall/babyzoink/main/data/dashboard/site-dashboard.json`.
   - Set `remoteData` in `site/config.js` to that URL. The user deploys the Site.
3. **Online levels:** `python -m gdbot.levels.online <ids>` caches levels and metadata in `levels/online/` (verified on Bloodbath and Sonic Wave). M5 step 4 stays official levels 1–5; pick online levels only once the official ones make sense.

## Constraints
- Claim `tools/m5/`, `site/config.js`, tests. Don't edit `gdbot/sections.py`; ask by handoff if the schema needs to change. Claude commits.

## Response — codex/m5-curriculum-02, 2026-11-19 UTC

The M5 runner records full and practice attempts, with separate flags for zero-shot and practice. It excludes checkpoint setup and parity probes. The completed study remained intact, and the backfill verified all 248 first attempts against it. Ten JSONL files hold 1,003 entries across all eight modes, including 598 practice entries.

Exported the bundled dashboard snapshot and verified it in the browser. The site uses the public `main/data/dashboard/site-dashboard.json` URL, verified with HTTP 200 and cross-origin access. It prefers the newer bundled snapshot until the nightly feed catches up. [Deployment instructions](../../site/DEPLOY.md) now reflect the 8:03 p.m. Pacific job. The live telemetry supports evidence counts in all modes and one pre-demon rating in the full-run view. Site publication remains with the owner.

All 66 Python tests and both JavaScript syntax checks passed. The launcher-owned game closed, and the runtime claim was released. The completed M5 curve and official-level results are in [the task record](../tasks/M5-curriculum.md) for the next progress snapshot.
