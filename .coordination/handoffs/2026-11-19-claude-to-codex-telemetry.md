# Handoff: section telemetry is ready; record it in the M5 runs and point the site at the live feed

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: pending (do it as part of #10 if you're still in M5, otherwise as queue #14)
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
2. **The nightly job** (20:03) now also runs `tools/site/export.py --refresh-gddl` and pushes `site-dashboard.json` to `dashboard-data`.
   - Verified: HTTP 200 with `Access-Control-Allow-Origin: *` at `https://raw.githubusercontent.com/craftyderpysmall/babyzoink/dashboard-data/site-dashboard.json`.
   - Set `remoteData` in `site/config.js` to that URL. The user deploys the Site.
3. **Online levels:** `python -m gdbot.levels.online <ids>` caches levels and metadata in `levels/online/` (verified on Bloodbath and Sonic Wave). M5 step 4 stays official levels 1–5; pick online levels only once the official ones make sense.

## Constraints
- Claim `tools/m5/`, `site/config.js`, tests. Don't edit `gdbot/sections.py`; ask by handoff if the schema needs to change. Claude commits.

## Response — [recipient/session, UTC]
