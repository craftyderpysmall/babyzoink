"""Per-level attempt ledger for the dashboard: normal vs practice attempts on every level.

One JSONL row per (run, level) in build/attempts/<run>.jsonl:
  {run, level, name, t, normal_attempts, practice_attempts, normal_clears, practice_clear,
   best_progress, first_clear_attempt, input_timing}
- normal attempt  = a full run from 0% (practice off). first_clear_attempt is the 1-based index of
  the first normal attempt that completed (None if none did).
- practice attempt = a reset from a checkpoint or start position (practice drilling, local timing
  search, and each candidate the M5c search teacher evaluates).
Level keys match section telemetry: drill:<family>/<variant>, official:<n>, online:<GD id>.
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "build" / "attempts"
OFFICIAL = ("Stereo Madness", "Back on Track", "Polargeist", "Dry Out", "Base After Base")
INPUT_TIMINGS = ("tick", "cbf")


def row(run, level, *, name=None, normal_attempts=0, practice_attempts=0, normal_clears=0,
        practice_clear=False, best_progress=0.0, first_clear_attempt=None, input_timing="tick", t=None):
    if not level or ":" not in level:
        raise ValueError("level keys look like drill:<family>/<variant>, official:<n> or online:<id>")
    if input_timing not in INPUT_TIMINGS:
        raise ValueError("input_timing must be tick or cbf")
    return {"run": run, "level": level, "name": name or level.split(":", 1)[1], "t": t or round(time.time(), 3),
            "input_timing": input_timing,
            "normal_attempts": int(normal_attempts), "practice_attempts": int(practice_attempts),
            "normal_clears": int(normal_clears), "practice_clear": bool(practice_clear),
            "best_progress": round(float(best_progress), 4), "first_clear_attempt": first_clear_attempt}


def from_result(run, level, result, *, name=None, t=None):
    """Row from the common study shape {attempts: [{terminal, peak_progress}], practice: [{resets}]}."""
    attempts = result.get("attempts", [])
    first = next((i for i, a in enumerate(attempts, 1) if a.get("terminal") == "complete"), None)
    practice = result.get("practice") or []
    return row(run, level, name=name, t=t, input_timing=result.get("input_timing", "tick"),
               normal_attempts=len(attempts),
               practice_attempts=sum(p.get("resets", 0) for p in practice),
               normal_clears=sum(a.get("terminal") == "complete" for a in attempts),
               practice_clear=any(p.get("section_completed_level") for p in practice),
               best_progress=max([a.get("peak_progress", 0.0) for a in attempts] or [0.0]),
               first_clear_attempt=first)


def write(run, rows, directory: Path = DEFAULT_DIR):
    """Replace this run's ledger file atomically (runs are re-exportable, never appended twice)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run}.jsonl"
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)
    return path


def read(directory: Path = DEFAULT_DIR):
    rows = []
    for path in sorted(Path(directory).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def summarize(rows):
    """Totals per level across runs, sorted official -> online -> drills."""
    levels = {}
    for r in rows:
        timing = r.get("input_timing", "tick")
        if timing not in INPUT_TIMINGS:
            raise ValueError("input_timing must be tick or cbf")
        s = levels.setdefault(r["level"], {"level": r["level"], "name": r["name"], "normal_attempts": 0,
                                           "practice_attempts": 0, "normal_clears": 0, "practice_clear": False,
                                           "best_progress": 0.0, "runs": 0, "first_cleared_by": None,
                                           "last_attempt_t": 0, "input_timing": []})
        if timing not in s["input_timing"]:
            s["input_timing"].append(timing)
            s["input_timing"].sort(reverse=True)  # tick before cbf
        s["normal_attempts"] += r["normal_attempts"]
        s["practice_attempts"] += r["practice_attempts"]
        s["normal_clears"] += r["normal_clears"]
        s["practice_clear"] |= r["practice_clear"]
        s["best_progress"] = max(s["best_progress"], r["best_progress"])
        s["runs"] += 1
        if r["normal_clears"] and (s["first_cleared_by"] is None or r["t"] < s["first_cleared_by"]["t"]):
            s["first_cleared_by"] = {"run": r["run"], "attempt": r["first_clear_attempt"], "t": r["t"],
                                     "input_timing": timing}
        s["last_attempt_t"] = max(s["last_attempt_t"], r["t"])
    order = {"official": 0, "online": 1, "drill": 2}

    def key(s):
        kind, _, rest = s["level"].partition(":")
        num = int(rest) if rest.isdigit() else 0
        return order.get(kind, 3), num if kind == "official" else 0, s["name"]

    return sorted(levels.values(), key=key)
