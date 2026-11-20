"""Export one static dashboard snapshot from progress, power and optional telemetry."""

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from gddl import cache_update, read_cache
from rating import Anchor, Section, summarize

ROOT = Path(__file__).resolve().parents[2]
JOULES_PER_CPU_SECOND = 28.0 / 16
OFFICIAL = {
    "official:1": ("Stereo Madness", 1), "official:2": ("Back on Track", 2),
    "official:3": ("Polargeist", 3), "official:4": ("Dry Out", 4), "official:5": ("Base After Base", 5),
}


def telemetry(directory):
    rows = []
    for path in sorted(directory.glob("*.jsonl")):
        with path.open(encoding="utf-8") as data:
            for number, line in enumerate(data, 1):
                if line.strip():
                    try:
                        rows.append(Section.from_row(json.loads(line)))
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValueError(f"{path.name}:{number}: {exc}") from exc
    return rows


def energy(directory, price):
    pacific = ZoneInfo("America/Los_Angeles")
    by_day = defaultdict(lambda: [0.0, 0.0])
    first = None
    # Prefer sampled records for exact duplicates. The sampler uses interval deltas.
    samples = {}
    for path in (directory / "backfill.csv", directory / "samples.csv"):
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as data:
            for row in csv.DictReader(data):
                try:
                    timestamp = datetime.fromisoformat(row["utc"])
                    timestamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
                    gd, train = (float(row[key]) for key in ("gd_cpu_s", "train_cpu_s"))
                    if not all(math.isfinite(value) and value >= 0 for value in (gd, train)):
                        continue
                    samples[timestamp] = gd, train
                except (KeyError, ValueError):
                    continue
    for timestamp, (gd, train) in sorted(samples.items()):
        timestamp = timestamp.astimezone(pacific)
        if first is None:
            first = timestamp.isoformat(timespec="seconds")
        bucket = by_day[timestamp.date().isoformat()]
        bucket[0] += gd
        bucket[1] += train
    cumulative = 0.0
    rows = []
    for day, (gd, train) in sorted(by_day.items()):
        kwh = (gd + train) * JOULES_PER_CPU_SECOND / 3.6e6
        cumulative += kwh
        rows.append({"date": day, "kwh": round(kwh, 6), "cumulative_kwh": round(cumulative, 6),
                     "cost_usd": round(kwh * price, 6), "cumulative_cost_usd": round(cumulative * price, 6)})
    return {"rows": rows, "tracking_since": first, "kwh": round(cumulative, 6),
            "cost_usd": round(cumulative * price, 6)}


def online_metadata(directory):
    rows = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("metadata", data) if isinstance(data, dict) else {}
        identifier = meta.get("id")
        if type(identifier) is int and identifier > 0:
            rows[identifier] = meta
    return rows


def resolve_anchors(rows, cache, metadata):
    anchors, names = {}, {}
    for level in {row.level for row in rows}:
        if level.startswith("drill:"):
            anchors[level] = Anchor(0.0, "Original drill")
            names[level] = level.removeprefix("drill:")
        elif level in OFFICIAL:
            name, stars = OFFICIAL[level]
            anchors[level] = Anchor(max(stars - 2, 0) / 8, f"Official · {stars} stars")
            names[level] = name
        elif level.startswith("online:") and level[7:].isdigit():
            identifier = int(level[7:])
            entry = cache["levels"].get(str(identifier), {})
            meta = metadata.get(identifier, {})
            names[level] = entry.get("name") or meta.get("name") or level
            if entry.get("rating") is not None:
                anchors[level] = Anchor(entry["rating"], f"GDDL {entry['rating']:.2f}", gddl=True)
            elif meta.get("demon") is False and type(meta.get("stars")) is int and 1 <= meta["stars"] <= 9:
                stars = meta["stars"]
                anchors[level] = Anchor(max(stars - 2, 0) / 8, f"Rated · {stars} stars")
    return anchors, names


def attempt_levels(directory):
    """Per-level normal vs practice attempts (gdbot/attempts.py ledger; tools/site/backfill_attempts.py)."""
    import sys
    sys.path.insert(0, str(ROOT))
    from gdbot.attempts import read, summarize as summarize_attempts
    return summarize_attempts(read(directory)) if directory.exists() else []


def queue_jobs(path):
    table = False
    jobs = []
    statuses = {"in progress": "in progress", "paused": "paused", "waiting": "paused", "blocked": "blocked",
                "queued": "queued", "open": "open", "done": "done", "deployed": "done", "completed": "done",
                "implemented": "in progress"}
    order = {"in progress": 0, "paused": 1, "blocked": 1, "queued": 2, "open": 3, "done": 4}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if table:
                break
            table = line.strip() == "## Codex task queue"
        if not table or not re.match(r"^\|\s*\d+\s*\|", line):
            continue
        cells = [field.strip() for field in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        number, task, _, _, state = cells
        owner = "Claude" if re.search(r"\(claude(?:\)|,|/)", line, re.I) else "Codex"
        task = re.sub(r"^\(claude\)\s*", "", task, flags=re.I).replace(r"\|", "|")
        status = next((value for prefix, value in statuses.items()
                       if re.match(rf"{prefix}\b", state.casefold())), None)
        if status is None:
            raise ValueError(f"Unknown state for job #{number}: {state}")
        if status == "open":
            owner = "Unassigned"
        jobs.append({"number": int(number), "task": task, "owner": owner, "status": status,
                     "progress": state.replace(r"\|", "|")})
    return sorted(jobs, key=lambda job: (order[job["status"]], job["number"]))


def attempts_curve(path):
    if not path.exists():
        return []
    report = json.loads(path.read_text(encoding="utf-8"))
    cohort = set(report["protocol"]["cohort"])
    runs = report["runs"]
    if len(runs) != 1 + len(report["protocol"]["checkpoints"]) or any(set(run["levels"]) != cohort for run in runs):
        return []
    common = {key for key in cohort if all(run["levels"][key]["verified"] for run in runs)}
    return [{"generation": run["generation"], "levels": len(cohort), "matched_clears": len(common),
             "clears": sum(level["verified"] for level in run["levels"].values()),
             "mean_evaluations": sum(run["levels"][key]["practice_attempts"] for key in common) / len(common) if common else None,
             "mean_normal_attempts": sum(run["levels"][key]["normal_attempts"] for key in common) / len(common) if common else None}
            for run in runs]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "site/data/dashboard.json")
    parser.add_argument("--telemetry", type=Path, default=ROOT / "build/telemetry")
    parser.add_argument("--attempts", type=Path, default=ROOT / "build/attempts")
    parser.add_argument("--refresh-gddl", action="store_true", help="look up referenced public level IDs")
    parser.add_argument("--replace-anchors", action="store_true", help="refresh existing cached ratings too")
    options = parser.parse_args()
    progress = json.loads((ROOT / "docs/progress.json").read_text(encoding="utf-8"))
    for result in progress["results"]:
        result.setdefault("input_timing", "tick")
    rows = telemetry(options.telemetry)
    metadata = online_metadata(ROOT / "levels/online")
    cache_path = ROOT / "levels/difficulty/gddl_cache.json"
    cache = read_cache(cache_path)
    if options.refresh_gddl:
        ids = {int(row.level[7:]) for row in rows if row.level.startswith("online:") and row.level[7:].isdigit()}
        ids = {identifier for identifier in ids if metadata.get(identifier, {}).get("demon") is not False}
        cache, errors = cache_update(cache_path, ids, refresh=options.replace_anchors)
        for error in errors:
            print(f"GDDL {error}")
    anchors, names = resolve_anchors(rows, cache, metadata)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = {
        "schema": 1, "updated_at": now, "progress": progress,
        "energy": energy(ROOT / "build/power", progress["price"]["cents_per_kwh"] / 100),
        "performance": summarize(rows, anchors), "level_names": names,
        "levels": attempt_levels(options.attempts),
        "jobs": queue_jobs(ROOT / ".coordination/STATUS.md"),
        "attempts_curve": attempts_curve(ROOT / "build/m6-scale/guided/report.json"),
        "telemetry": {"sections": len(rows), "anchored_sections": sum(row.level in anchors for row in rows)},
        "gddl": {"version": cache["api_version"], "checked_at": cache["version_checked_at"]},
    }
    output = options.output
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix(".tmp")
    staging.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    staging.replace(output)
    print(f"Wrote {output} from {len(rows)} entered sections")


if __name__ == "__main__":
    main()
