# Handoff: replace the Claude artifact dashboard with a ChatGPT-hosted site + a per-mode performance dashboard

From: claude/plan-01 (coordinator)
To: codex
Created: 2026-11-19
Status: pending (queue after #10; hosting = ChatGPT Sites)
Related: tools/dashboard/ (current pipeline), docs/progress.json, build/power/samples.csv, the dashboard-data branch

## What the user asked for
1. Move the progress dashboard off the claude.ai artifact onto a ChatGPT site.
2. Add a **performance dashboard** that measures how good the bot is at each game mode. It should use a static difficulty reference (the public GDDL, GD Demon Ladder) and a metric better than raw pass rate.
- The user will set up their side (the hosting account) later.
- Claude keeps the old artifact and its nightly pipeline running until the new site is live. It will only delete the artifact after the user confirms.

## Hosting (user answer, 2026-11-19)
Target: **ChatGPT Sites** (ChatGPT's artifact-like hosting, `<username>.chatgpt.sites`). The user is setting up the account side.
- Keep the site **static**: `site/` HTML/JS/CSS plus `site/data/*.json` from a Python exporter.
- The nightly refresh then only has to republish new data.
- Find out how ChatGPT Sites gets content updated (manual publish, API, or a connected repo or branch). Write the exact steps in `site/DEPLOY.md`.
- If updates can't be automated, say so in the response. Claude will then design the 8 pm refresh around what is possible, e.g. a site that fetches its JSON from the public `dashboard-data` branch at view time.
- Don't publish under the user's account without them.

## Pages
1. **Overview** (port of the current artifact):
   - milestones, results table, power used (kWh from `build/power/samples.csv` + backfill);
   - cost at the California residential price in `docs/progress.json`;
   - "updated at" stamp. Daily refresh at 8 pm Pacific, same as now.
2. **Performance.** Per-mode skill ratings with a trend over generations, per-level breakdown and an evidence count. Show uncertainty: no single bare number without an interval or "n seconds observed".

## The metric (proposal; challenge it in the response if you see something better)
Pass rate is biased: long sections and sections the bot rarely reaches look harder or easier than they are. Use **survival time in mode, against difficulty**:
- **Unit of evidence:**
  - A *section* is a maximal run of ticks in one mode (cube, ship, ball, UFO, wave, robot, spider, swing). Split further at each speed portal. Mini and dual are flags on the section.
  - For each attempt that *enters* a section, record the seconds survived inside it and whether it died there.
  - Sections never reached contribute nothing. That removes the reach bias.
- **Model** (Rasch/IRT on survival per second; a discrete-time hazard model):
  `P(survive one second of section s on attempt a) = sigmoid(θ_mode(s),g − β_level(s) − δ_s)`
  - θ is the bot's skill per mode, per generation g.
  - β_level is anchored to the static difficulty reference (below), scaled by one fitted slope.
  - δ_s is a per-section residual with a zero-mean prior. Sections are only partly explained by level difficulty.
  - Fit by penalised maximum likelihood, or a small Bayesian fit. Report θ with an interval.
- **Displayed number — "Mode rating":** θ converted onto the GDDL tier scale.
  - Definition: the tier at which the model predicts the bot survives that mode's gameplay at a fixed reference rate. For example, a 50% chance to survive a 10-second section; state the reference.
  - Example: "wave 7.4 ± 0.8 means it handles the wave sections of a tier-7 demon about half the time".
  - Rating 0 is the drills / easy levels band. Below the GDDL range the anchors are official difficulty and star rating (Easy … Insane, then GDDL for demons). Document the mapping.
- **Secondary columns:**
  - deaths per minute in that mode;
  - attempts to first clear of sections in that mode;
  - zero-shot survival (first attempt on unseen levels). This is the number that should rise across generations.
- Practice resets from checkpoints count as attempts on the section they start in, flagged separately. Show a "full runs only" view as well.

## Difficulty reference (GDDL)
- Use the public GDDL (gdladder.com) API with a cache.
  - Verify the current endpoints and terms yourself: don't trust memory.
  - Respect rate limits; cache responses in `levels/difficulty/gddl_cache.json` with fetch dates.
  - Record the API version/date in the site footer.
- GDDL only rates demons. For non-demons use the official in-game difficulty/stars (from the level metadata) as a fixed ordinal below demons.
- **Online levels (user answer: download them):**
  - Claude is writing `gdbot/levels/online.py`. It downloads chosen custom levels from GD's servers *outside* the game (the bridge keeps the game itself offline), caches the raw level string plus metadata (id, name, difficulty, stars, demon flag) in `levels/online/`, and loads them through `level_string`.
  - Join GDDL ratings on level id.

## Split
- **Claude (backend, small):** per-attempt section telemetry, plus the online level downloader.
  - A `gdbot/sections.py` segmenter over trace rows: mode, speed, mini/dual flags, entry/exit tick, death tick.
  - A JSONL export from the M4/M5 runners into `build/telemetry/`.
  - Claude will point the nightly Windows task at the new exporter.
  - Claude writes a handoff to you when the schema is in `docs/TELEMETRY.md`. Until then, use synthetic data matching the schema in that file (or the draft below).
- **Codex (this task, the heavy part):**
  - the site;
  - the GDDL client + cache;
  - the metric fit (`tools/site/rating.py` with unit tests on synthetic data where the true θ is known: it must recover θ within its interval);
  - the exporter that turns telemetry + power + progress into `site/data/`.

Draft telemetry row (one per attempt × section entered):
`{"run": "...", "generation": 3, "seed": 1207, "level": "official:1" | "drill:<family>/<variant>", "attempt": 2, "start": "zero"|"checkpoint"|"startpos", "section": 4, "mode": "wave", "speed": 2, "mini": false, "dual": false, "entry_tick": 5120, "exit_tick": 6011, "died": true, "ticks_in_section": 891}`

## Constraints
- Needs no game. Claim `site/`, `tools/site/`, `levels/difficulty/`, `tests/test_rating.py`, and the task file `tasks/site-dashboard.md`.
- Don't edit `tools/dashboard/` (Claude retires it at cutover), `mod/`, `injector/`, or `docs/PROTOCOL.md`. Claude commits.

## Response — [recipient/session, UTC]
