# ChatGPT Sites dashboard

Status: local source and exporter complete (codex/site-dashboard-01). Account setup, publication, and production telemetry remain pending.

## Delivered

- Buildless Overview with milestones, study outcomes, daily and cumulative estimated energy, local electricity price, and last-update time. The estimate retains the existing 1.75 J per game or trainer CPU-second model.
- Performance view with zero-shot, full-run and all-start evidence filters, model intervals, generation trends, and a per-level table. Empty and uncalibrated views display the evidence available.
- Offline-first JSON exporter and cached public GD Demon Ladder client. The verified endpoint is plural `/api/levels/{id}`. One real public lookup returned rating 2.2222 and 63 community ratings on API 3.5.9. Existing anchors stay frozen across refreshes. The checked-in snapshot contains the real project Overview and no synthetic ratings.
- [Deployment and nightly update instructions](../../site/DEPLOY.md). The existing raw data branch supports cross-origin reads. Keep the bundled snapshot until the nightly task writes the combined data file and the owner deploys the configured Site.

## Metric decision

Use a piecewise-constant death hazard by entered section. The log hazard is difficulty slope times the level anchor, plus a penalized section residual, minus mode skill for that generation. The likelihood scores exposure time and observed deaths, so short visits count without rounding to one-second buckets. A successful exit or a timeout contributes exposure up to censoring. A GDDL rating estimates the difficulty of a typical entered section the policy survives for 10 seconds with 50% probability. Drills and the lowest official levels anchor 0, rated non-demons lie below 1, and demons retain their published numeric GDDL anchors.

An interval is conditional on observed sections and the fitted model. Reaching later sections selects a subset of attempts. Report zero-shot separately and compare trends on a frozen evaluation mix. Display evidence without a numeric rating when there are too few anchors or the estimate extrapolates. In particular, the site never advertises a demon tier estimated solely from easy or drill data.

## Verification

- Synthetic censored trials recovered both known mode skills inside their model-based 95% intervals and showed the correct ordering across generations. Additional tests exercised practice filtering and frozen rating snapshots.
- All 54 Python tests and both JavaScript syntax checks passed.
- Browser checks covered the actual Overview and empty Performance view, then rating intervals, generation and practice filters, and the per-level breakdown with a temporary synthetic input. The bundled snapshot was regenerated from real records afterward.
- The local dashboard uses the existing progress and power data. Raw section telemetry has not yet been produced, so live mode ratings remain empty. The backend handoff should confirm the stable section identity plus optional `zero_shot` and `cleared` fields.
