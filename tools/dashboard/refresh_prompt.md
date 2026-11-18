Nightly refresh of the babyzoink progress dashboard: https://claude.ai/artifact/KRrQvsq6WkTcYJ4kmvp7ak
You are running unattended from Windows Task Scheduler in C:\Users\user\Documents\babyzoink. Do only the steps below. Don't change anything else in the repo or on the machine, and don't touch the game or the coordination claims.

1. Make sure the power sampler is running. A powershell process whose command line contains `power_sampler.ps1` should exist. If none does, start it hidden:
   `Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\Users\user\Documents\babyzoink\tools\dashboard\power_sampler.ps1'`
2. Update `docs/progress.json`, using only facts recorded in the repo:
   - Milestone statuses come from `.coordination/STATUS.md` and the `.coordination/tasks/*.md` files.
   - Add rows to `results` only for studies whose task file reports finished numbers (for example `tasks/M3-scale.md`). Copy the numbers exactly.
   - Re-check the latest month in the U.S. EIA Electric Power Monthly, Table 5.6.A (https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a), for California residential. Update `price` only if a newer month is published.
   - Set `updated` to today's date.
3. Run `python -I tools/dashboard/collect.py`.
4. Upload each of `build/dashboard/energy_daily.json`, `milestones.json`, `results.json` and `price.json` to the artifact as an asset: Artifact tool, action publish, `asset: true`, `url` as above, `file_path`.
5. Read `datasets/energy_daily`, `datasets/milestones`, `datasets/results` and `datasets/price` with ArtifactData. In one batch `update`, pinned with each document's `if_version`, set:
   - `source.url` to the new `/_blob/...` url;
   - `updated` to `{"at": <now, ISO UTC>, "by": "Nightly refresh (Windows Task Scheduler)"}`.
6. Delete the assets those datasets pointed to before this run (Artifact action delete, `url` plus the old asset id as `path`), so old copies don't pile up.
7. If `docs/progress.json` changed, commit only that file and push. Use the message "Dashboard: nightly progress refresh" and end it with:
   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
8. Print a one-line summary: total kWh, total cost, milestones done, and any step that failed.
