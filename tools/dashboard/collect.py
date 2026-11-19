"""Build the progress-dashboard data files from local records.

Inputs:
  build/power/samples.csv, build/power/backfill.csv  (tools/dashboard/power_sampler.ps1)
  docs/progress.json                                  (milestones, results, electricity price; curated)
Outputs (build/dashboard/, gitignored), each {"rows": [...], "meta": [...]}:
  energy_daily.json, milestones.json, results.json, price.json

Energy model (an estimate; the laptop has no power meter software can read):
  CPU-seconds used by the bot's processes x (28 W / 16 hardware threads)
  = 1.75 joules per CPU-second. 28 W is the AMD Ryzen AI 7 350's default package power (cTDP).
  Counts only the frozen bot copy of GD and the bot's Python processes; screen, GPU and the rest
  of the laptop are not included.
Usage: python -I tools/dashboard/collect.py
"""
import csv
import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "build", "dashboard")
JOULES_PER_CPU_S = 28.0 / 16
PACIFIC = dt.timezone(dt.timedelta(hours=-8))  # PST; the project runs in November–February first


def read_samples():
    rows = []
    for name in ("backfill.csv", "samples.csv"):
        p = os.path.join(ROOT, "build", "power", name)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    t = dt.datetime.fromisoformat(r["utc"]).replace(tzinfo=dt.timezone.utc)
                    rows.append((t, float(r["gd_cpu_s"]), float(r["train_cpu_s"])))
                except (KeyError, ValueError):
                    continue
    return sorted(rows)


def attempts_file():
    """Per-level normal vs practice attempts (gdbot/attempts.py ledger, rebuilt nightly by
    tools/site/backfill_attempts.py). Flat rows for the artifact table."""
    import sys
    sys.path.insert(0, ROOT)
    from gdbot.attempts import read, summarize
    kinds = {"official": "Official", "online": "Online", "drill": "Drill"}
    rows = []
    for s in summarize(read(os.path.join(ROOT, "build", "attempts"))):
        first = s["first_cleared_by"]
        rows.append({
            "level": s["level"], "kind": kinds.get(s["level"].split(":")[0], "Other"), "name": s["name"],
            "normal_attempts": s["normal_attempts"], "practice_attempts": s["practice_attempts"],
            "normal_clears": s["normal_clears"], "best_progress_pct": round(100 * s["best_progress"], 1),
            "first_cleared_by": f"{first['run']} (normal attempt {first['attempt']})" if first else "",
        })
    meta = [{"label": "Normal attempt", "value": "a full run from 0% with practice off"},
            {"label": "Practice attempt", "value": "a reset from a checkpoint: practice drilling, timing search, "
                                                  "and each candidate the search teacher evaluates"}]
    return {"rows": rows, "meta": meta}


def main():
    os.makedirs(OUT, exist_ok=True)
    prog = json.load(open(os.path.join(ROOT, "docs", "progress.json"), encoding="utf-8"))
    price = prog["price"]
    usd_per_kwh = price["cents_per_kwh"] / 100.0
    samples = read_samples()
    by_day = {}
    for t, gd, tr in samples:
        day = t.astimezone(PACIFIC).date().isoformat()
        d = by_day.setdefault(day, [0.0, 0.0])
        d[0] += gd
        d[1] += tr
    energy, cum_kwh = [], 0.0
    for day in sorted(by_day):
        gd, tr = by_day[day]
        kwh = (gd + tr) * JOULES_PER_CPU_S / 3.6e6
        cum_kwh += kwh
        energy.append({"date": day, "gd_cpu_hours": round(gd / 3600, 3), "training_cpu_hours": round(tr / 3600, 3),
                       "kwh": round(kwh, 5), "cost_usd": round(kwh * usd_per_kwh, 5),
                       "cumulative_kwh": round(cum_kwh, 5), "cumulative_cost_usd": round(cum_kwh * usd_per_kwh, 5)})
    first = samples[0][0].astimezone(PACIFIC).strftime("%Y-%m-%d %H:%M %Z") if samples else "no samples yet"
    meta_energy = [
        {"label": "Method", "value": "CPU-seconds of the bot's GD copy and Python training x 1.75 J (28 W package power / 16 threads, AMD Ryzen AI 7 350). Estimate; screen, GPU and the rest of the laptop are not counted."},
        {"label": "Price", "value": f"{price['cents_per_kwh']} cents/kWh, {price['region']} {price['sector'].lower()}, {price['month']} ({price['source']})"},
        {"label": "Tracking since", "value": first + " (first day includes CPU already used by runs in progress then; earlier runs were not measured)"},
        {"label": "Generated", "value": dt.datetime.now(PACIFIC).strftime("%Y-%m-%d %H:%M PST")},
    ]
    files = {
        "energy_daily.json": {"rows": energy, "meta": meta_energy},
        "milestones.json": {"rows": prog["milestones"], "meta": [{"label": "Updated", "value": prog["updated"]}]},
        "results.json": {"rows": prog["results"], "meta": [{"label": "Updated", "value": prog["updated"]}]},
        "price.json": {"rows": [{k: price[k] for k in ("region", "sector", "month", "cents_per_kwh", "source", "url")}], "meta": []},
        "attempts.json": attempts_file(),
    }
    for name, body in files.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            json.dump(body, f, indent=1)
    tot = energy[-1] if energy else {"cumulative_kwh": 0, "cumulative_cost_usd": 0}
    print(f"wrote {len(files)} files to {OUT}; days={len(energy)} total={tot['cumulative_kwh']:.4f} kWh "
          f"${tot['cumulative_cost_usd']:.4f}")


if __name__ == "__main__":
    main()
