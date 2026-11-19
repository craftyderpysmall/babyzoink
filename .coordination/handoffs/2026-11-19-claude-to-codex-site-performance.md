# Handoff: performance metrics on the site's front page (user request, addendum to #17 item 1)

From: claude/plan-01
To: codex
Created: 2026-11-19
Status: pending (do it with the Site deploy, #17 item 1)

The user wants the per-mode **performance metrics** on the dashboard now, as frontend, even though most numbers don't exist yet. Today the metrics only live on the separate Performance tab.

**Request (frontend only, in `site/`):**
1. **Performance summary on the Overview** (the page people land on). Show one card per game mode (cube, ship, ball, UFO, wave, robot, spider, swing). Each card shows:
   - the mode rating on the GDDL scale with its interval when one exists;
   - otherwise a clear placeholder, e.g. "Not rated yet: 34 s observed, 2 deaths", taken from the evidence counts already in `performance`;
   - deaths per minute and the best level cleared in that mode, or "—".
2. **One headline line:**
   - **Official levels cleared:** count of official rows in `levels` with `normal_clears > 0`, e.g. "3 of 5 (by the search teacher)". `levels` comes from the attempts ledger.
   - **Trained-policy best:** from the zero-shot / first-run numbers.
   - Make clear which clears are search-teacher replays and which are the trained policy playing on its own.
3. **A placeholder** for "attempts to first clear across generations", the "fewer attempts on harder levels" chart. Show the axis and empty state now; it fills once expert iteration (#17 item 3) records generations.
4. **Links** from each card to the full Performance tab for that mode.
5. **Empty and missing data:**
   - Empty or missing fields must render placeholders, not errors.
   - The page must still load from an older `site-dashboard.json` without these fields; the nightly feed lags the bundled snapshot.
6. **Then deploy** it as part of item 1, and give the user the URL.
