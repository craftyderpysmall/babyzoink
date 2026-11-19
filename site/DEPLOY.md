# Deploy the Babyzoink dashboard

The dashboard is a buildless ChatGPT Site. The current repository includes a local snapshot and two browser views. Account setup and the first publication are pending.

## Export and preview

Install `tools/site/requirements.txt` into the existing project virtual environment. On Windows, `tzdata` supplies the Pacific timezone database.

```powershell
& .\build\gdbot-venv\Scripts\python.exe -m pip install -r tools/site/requirements.txt
& .\build\gdbot-venv\Scripts\python.exe tools/site/export.py
& .\build\gdbot-venv\Scripts\python.exe -m http.server 8769 --bind 127.0.0.1 --directory site
```

Open [the local preview](http://127.0.0.1:8769). The exporter reads `docs/progress.json`, the sampler and backfill CSVs under `build/power/`, and any JSONL files in `build/telemetry/`. It writes one atomic snapshot to `site/data/dashboard.json`. An empty telemetry directory produces a normal Overview and an empty Performance view.

## First publication or changes to the site

1. Use the ChatGPT Sites `create_site` action in the approved owner account. It returns a private Site, project ID, and source repository access. For updates, open that same Site with `get_site` and obtain a fresh source repository credential with `create_source_repository_write_credential`.
2. Open the Site source with the Sites plugin's `site-workflow.mjs --project-id <id>` helper in a separate empty directory. Pass the returned credential through the helper's hidden stdin. Use its returned checkout path.
3. Place `index.html`, `styles.css`, `app.js`, `config.js`, and `data/dashboard.json` from this directory inside `dist/` in the Site checkout. Run the plugin's `set-project-id.mjs --project-id <id> --static-directory dist` from that checkout. This creates the Site hosting manifest.
4. Run `site-workflow.mjs --project-id <id>` again in packaging mode. Supply the credential, the prior source opening result, `commands: []`, and an absolute `archivePath` through hidden stdin. The helper updates the separate Site source repository and returns the commit SHA and archive.
5. For the private Site, pass that archive and commit to `save_version_and_deploy_private`. If the combined action is unavailable, use `save_site_version` followed by `deploy_private_site_version`. For an explicitly approved audience change, use the appropriate Sites publication action and preserve the chosen audience afterward. Verify the returned deployment URL.

Static files update with a Site version deployment. The Sites workflow uses its own source repository. A push to Babyzoink's data branch alone does not redeploy the Site.

## Nightly data updates at 8:03 p.m. Pacific

The existing nightly job publishes the generated dashboard snapshot on the public `main` branch. The raw URL has returned HTTP 200 and `Access-Control-Allow-Origin: *`.

1. The 8:03 p.m. job runs the exporter with `--refresh-gddl --output data/dashboard/site-dashboard.json` and publishes that generated file on `main`. The snapshot includes aggregate results and evidence. It excludes raw attempt telemetry and source logs.
2. The frontend is configured to read the [public dashboard snapshot](https://raw.githubusercontent.com/craftyderpysmall/babyzoink/main/data/dashboard/site-dashboard.json). Deploy the site once, then let the browser choose the newest valid snapshot on open. It uses the bundled snapshot when that is newer or when the feed is unavailable.
3. If the data later needs private hosting, disable the remote URL and publish a new Site version with the updated bundled snapshot.

## Difficulty snapshots and telemetry

`--refresh-gddl` looks up new referenced public demon IDs and records the API version, rating and fetch time in `levels/difficulty/gddl_cache.json`. Existing anchors are frozen. Pair the option with `--replace-anchors` only when deliberately recalibrating the series. The verified public routes are `GET /api/version` and `GET /api/levels/{id}`. The older Swagger page describes v2 limits and singular routes. The live lookup used v3.5.9 and the plural route. The exporter runs without authentication, stays at or below 40 level requests per minute, and stops the batch on HTTP 429. Current usage terms or a separate v3 bulk-use limit were not verified, so keep to the handful of IDs referenced by a study. [Live public API example](https://gdladder.com/api/levels/65977127) · [GDDL rating guidance](https://gdladder.com/about)

Telemetry uses one JSON object per entered section and attempt. In addition to the handoff's required fields, use `zero_shot: true` only for the unseen first attempt from zero and `cleared: true` only for a confirmed section exit. Without those flags, the first-run filter and attempts-to-clear values stay empty. Use stable section IDs across checkpoint and zero starts. Online level keys are `online:<GD level ID>`; the exporter uses `levels/online/*.json` metadata for non-demon stars when present.
