"""Rebuild the per-level attempt ledger (build/attempts/) from completed study reports.

Idempotent: each study becomes one ledger file named after it, rewritten on every run.
Sources: M4 paired practice, M5 curriculum (held-out, validation, train, official), M5b transfer
(validation arms, official training + zero-shot, online held-out, drill regression), M5c search
teacher solutions, the expert-cloning and triple-spike comparisons, and M6 training and evaluation.
Missing reports are skipped.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gdbot.attempts import OFFICIAL, from_result, row, write  # noqa: E402


def variant_families():
    out = {}
    for index in (ROOT / "levels/drills/index.yaml", ROOT / "levels/drills/m5/index.yaml"):
        if not index.exists():
            continue
        family = None
        for line in index.read_text(encoding="utf-8").splitlines():
            m = re.match(r'\s*-?\s*family:\s*"?([\w-]+)"?', line)
            if m:
                family = m.group(1)
            m = re.match(r'\s*variant:\s*"?([\w-]+)"?', line)
            if m and family:
                out[m.group(1)] = family
    from gdbot.levels.drills import NOTES  # validation-41xx layouts are generated in family order (tools/m3/scale.py)
    for index, family in enumerate(NOTES):
        out.setdefault(f"validation-{4100 + index}", family)
    return out


FAM = variant_families()


def drill(variant):
    return f"drill:{FAM.get(variant, 'unknown')}/{variant}"


def mtime(path):
    return round(path.stat().st_mtime, 3)


def m4():
    p = ROOT / "build/m4-practice/paired/report.json"
    if not p.exists():
        return
    r, t = json.loads(p.read_text(encoding="utf-8")), mtime(p)
    for arm in ("control", "practice"):
        rows = [from_result(f"m4-{arm}", drill(v["variant"]), v[arm], t=t) for v in r["pairs"].values()]
        write(f"m4-{arm}", rows)


def m5():
    p = ROOT / "build/m5-curriculum/report.json"
    if not p.exists():
        return
    r, t = json.loads(p.read_text(encoding="utf-8")), mtime(p)
    rows = []
    for key, run in r["runs"].items():
        name = f"m5-g{key.replace('/', '-s')}"
        for split in ("validation", "heldout"):
            for variant, res in (run.get(split) or {}).items():
                rows.append(from_result(name, drill(variant), res, t=t))
    for gen, block in r.get("official", {}).items():
        for i, n in enumerate(OFFICIAL, 1):
            if n in block["levels"]:
                rows.append(from_result(f"m5-official-g{gen}", f"official:{i}", block["levels"][n], name=n, t=t))
    write("m5-curriculum", rows)


def m5b():
    p = ROOT / "build/m5b-official/transfer/report.json"
    if not p.exists():
        return
    r, t = json.loads(p.read_text(encoding="utf-8")), mtime(p)
    rows = []
    for arm, block in r["arms"].items():
        for variant, res in block["validation"].items():
            rows.append(from_result(f"m5b-{arm}-validation", drill(variant), res, t=t))
    for i, n in enumerate(OFFICIAL, 1):
        if n in r.get("training", {}):
            rows.append(from_result("m5b-official-practice", f"official:{i}", r["training"][n], name=n, t=t))
    for key, res in r.get("online", {}).items():
        ident, _, nm = key.partition("/")
        rows.append(from_result("m5b-online", f"online:{ident}", res, name=nm, t=t))
    write("m5b-transfer", rows)


def m5c():
    directory = ROOT / "build/m5c"
    rows = {}
    for p in sorted(directory.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if "level" not in d:
            continue
        outcome = solver_row(d["level"], d["result"], t=mtime(p))
        rows[outcome["level"]] = timed_solver_rows(outcome, d["result"] or d)
    for p in sorted(directory.glob("main_*.progress.json")):
        number = int(p.name.split("_", 1)[1].split(".", 1)[0])
        level = f"official:{number}"
        if any(entry["normal_clears"] for entry in rows.get(level, [])):
            continue
        progress = json.loads(p.read_text(encoding="utf-8"))
        outcome = row("m5c-search", level, name=OFFICIAL[number - 1], t=mtime(p),
                      normal_attempts=progress.get("verification_attempts", 0),
                      practice_attempts=progress["evals"])
        rows[level] = timed_solver_rows(outcome, progress)
    if rows:
        write("m5c-search", [entry for entries in rows.values() for entry in entries])


def solver_row(name, res, t=None):
    """Search teacher: every evaluated candidate is a practice attempt from a checkpoint; the clean
    verification replay from 0% is the normal attempt."""
    kind, _, rest = name.partition(":")
    level, label = name, None
    if kind == "main":
        level, label = f"official:{rest}", OFFICIAL[int(rest) - 1]
    elif kind == "online":
        meta = ROOT / f"levels/online/{rest}.json"
        label = json.loads(meta.read_text(encoding="utf-8"))["name"] if meta.exists() else None
    if not res:
        return row("m5c-search", level, name=label, t=t, normal_attempts=0, practice_attempts=0)
    normal = res.get("verification_attempts", 1)
    return row("m5c-search", level, name=label, t=t, normal_attempts=normal, practice_attempts=res["evals"],
               normal_clears=int(res["verified"]), best_progress=1.0 if res["verified"] else 0.0,
               first_clear_attempt=normal if res["verified"] else None, practice_clear=bool(res["verified"]))


def timed_solver_rows(entry, record):
    current = entry | {"input_timing": record.get("input_timing", "tick")}
    if record.get("migrated_from") != "tick":
        return [current]
    normal = record["tick_verification_attempts"]
    practice = record["tick_evaluations"]
    if not 0 <= normal <= current["normal_attempts"] or not 0 <= practice <= current["practice_attempts"]:
        raise ValueError("migration counters exceed the recorded solver totals")
    current["normal_attempts"] -= normal
    current["practice_attempts"] -= practice
    if current["first_clear_attempt"] is not None:
        current["first_clear_attempt"] -= normal
    historical = row(f"{entry['run']}-pre-cbf", entry["level"], name=entry["name"], t=entry["t"],
                     normal_attempts=normal, practice_attempts=practice)
    return [historical, current]


def m5c_expert():
    p = ROOT / "build/m5c-expert/official/report.json"
    if not p.exists():
        return
    report, t = json.loads(p.read_text(encoding="utf-8")), mtime(p)
    rows = []
    for i, name in enumerate(OFFICIAL, 1):
        level = f"official:{i}"
        if f"main:{i}" in report.get("demos", {}):
            rows.append(row("m5c-demo-replay", level, name=name, t=t, normal_attempts=1,
                            normal_clears=1, best_progress=1.0, first_clear_attempt=1))
        if name in report.get("official", {}):
            result = {"attempts": [report["official"][name]]}
            rows.append(from_result("m5c-expert-official", level, result, name=name, t=t))
    for key, attempt in report.get("online", {}).items():
        ident, _, name = key.partition("/")
        rows.append(from_result("m5c-expert-online", f"online:{ident}", {"attempts": [attempt]}, name=name, t=t))
    write("m5c-expert", rows)


def m5c_triple():
    p = ROOT / "build/m5c-expert/triple/report.json"
    if not p.exists():
        return
    report, t = json.loads(p.read_text(encoding="utf-8")), mtime(p)
    rows = [from_result(f"m5c-triple-{arm}", report["heldout_level"], {"attempts": attempts}, t=t)
            for arm, attempts in report["evaluation"].items() if attempts]
    if "demo" in report:
        rows.append(from_result("m5c-triple-demo-replay", report["training_level"],
                                {"attempts": [report["demo"]]}, t=t))
    write("m5c-triple", rows)


def m6_search():
    rows = []
    pool = ROOT / "build/m6-scale"
    solutions = pool / "solutions"
    online_index = pool / "online-train.json"
    online_names = ({f"online:{item['id']}": item["name"]
                     for item in json.loads(online_index.read_text(encoding="utf-8"))}
                    if online_index.exists() else {})
    reported = set()
    for p in sorted(solutions.glob("*.json")):
        if p.name.endswith(".progress.json"):
            continue
        report = json.loads(p.read_text(encoding="utf-8"))
        reported.add(report["level"])
        verified = report["verified"]
        normal = report["normal_attempts"]
        progress_file = p.with_suffix(".progress.json")
        progress = (json.loads(progress_file.read_text(encoding="utf-8"))
                    if not verified and progress_file.exists() else {})
        entry = row("m6-search", report["level"], name=report["name"], t=mtime(p),
                        normal_attempts=max(normal, progress.get("verification_attempts", 0)),
                        practice_attempts=max(report["practice_attempts"], progress.get("evals", 0)),
                        input_timing=report.get("input_timing", "tick"),
                        normal_clears=int(verified), practice_clear=verified,
                        best_progress=1.0 if verified else 0.0,
                        first_clear_attempt=normal if verified else None)
        rows.extend(timed_solver_rows(entry, report | progress))
    for level, name in online_names.items():
        p = solutions / f"{level.replace(':', '_')}.progress.json"
        if level in reported or not p.exists():
            continue
        progress = json.loads(p.read_text(encoding="utf-8"))
        entry = row("m6-search", level, name=name, t=mtime(p),
                        normal_attempts=progress.get("verification_attempts", 0),
                        practice_attempts=progress["evals"],
                        input_timing=progress.get("input_timing", "tick"))
        rows.extend(timed_solver_rows(entry, progress))
    if rows:
        write("m6-search", rows)


def m6_curve():
    p = ROOT / "build/m6-scale/curve/report.json"
    if not p.exists():
        return
    report, t = json.loads(p.read_text(encoding="utf-8")), mtime(p)
    rows = []
    for level, demo in report["demos"].items():
        rows.append(row("m6-demo-replay", level, name=demo["name"], t=t, normal_attempts=1,
                        normal_clears=1, best_progress=1.0, first_clear_attempt=1))
    for run, result in report["runs"].items():
        for official, name in enumerate(OFFICIAL, 1):
            if name in result.get("official", {}):
                eval_run = {"attempts": [result["official"][name]]}
                rows.append(from_result(f"{run}-official", f"official:{official}", eval_run, name=name, t=t))
        for key, attempt in result.get("online", {}).items():
            level, _, name = key.partition("/")
            rows.append(from_result(f"{run}-online", f"online:{level}", {"attempts": [attempt]}, name=name, t=t))
    if rows:
        write("m6-curve", rows)


def m6_guided():
    path = ROOT / "build/m6-scale/guided/report.json"
    if not path.exists():
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for run in report["runs"]:
        generation = run["generation"]
        label = "m6-guided-control" if generation < 0 else f"m6-guided-g{generation}"
        for key, result in run["levels"].items():
            verified = result["verified"]
            normal = result["normal_attempts"]
            entry = row(label, key, name=result["name"], t=mtime(path), normal_attempts=normal,
                            practice_attempts=result["practice_attempts"], normal_clears=int(verified),
                            input_timing=result.get("input_timing", "tick"),
                            best_progress=float(verified), first_clear_attempt=normal if verified else None)
            rows.extend(timed_solver_rows(entry, result))
    if rows:
        write("m6-guided", rows)


def m6_dagger():
    p = ROOT / "build/m6-scale/dagger/report.json"
    if not p.exists():
        return
    report = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    for label, run in report["runs"].items():
        for variant, attempt in run.get("drills", {}).items():
            rows.append(from_result(f"m6-{label}", drill(variant), {"attempts": [attempt]}, t=mtime(p)))
        for entry, attempt in run.get("online", {}).items():
            level, _, name = entry.partition("/")
            rows.append(from_result(f"m6-{label}", f"online:{level}", {"attempts": [attempt]}, name=name, t=mtime(p)))
    if rows:
        write("m6-dagger", rows)


def m5c_triple_multi():
    p = ROOT / "build/m5c-expert/triple-multi/report.json"
    if not p.exists():
        return
    report = json.loads(p.read_text(encoding="utf-8"))
    rows = []
    for label, run in report["runs"].items():
        source = f"m5c-triple-multi-{label}"
        rows.append(from_result(source, "drill:triple-spike/heldout-2102", {"attempts": run["triple"]}, t=mtime(p)))
        for variant, attempt in run["other"].items():
            rows.append(from_result(source, drill(variant), {"attempts": [attempt]}, t=mtime(p)))
    for variant, tape in report["tapes"].items():
        if tape["verified"]:
            rows.append(row("m5c-triple-training-search", f"drill:triple-spike/{variant}", t=mtime(p),
                            normal_attempts=1, practice_attempts=tape["evaluations"], normal_clears=1,
                            practice_clear=True, best_progress=1.0, first_clear_attempt=1))
    if rows:
        write("m5c-triple-multi", rows)


if __name__ == "__main__":
    for step in (m4, m5, m5b, m5c, m5c_expert, m5c_triple, m6_search, m6_curve, m6_guided,
                 m6_dagger, m5c_triple_multi):
        step()
    from gdbot.attempts import read, summarize
    s = summarize(read())
    print(f"{len(s)} levels; normal {sum(x['normal_attempts'] for x in s)}, practice {sum(x['practice_attempts'] for x in s)}")
