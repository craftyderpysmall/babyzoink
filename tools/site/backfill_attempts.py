"""Rebuild the per-level attempt ledger (build/attempts/) from completed study reports.

Idempotent: each study becomes one ledger file named after it, rewritten on every run.
Sources: M4 paired practice, M5 curriculum (held-out, validation, train, official), M5b transfer
(validation arms, official training + zero-shot, online held-out, drill regression), M5c search
teacher solutions. Missing reports are skipped.
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
    rows = []
    for p in sorted((ROOT / "build/m5c").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if "level" not in d:
            continue
        rows.append(solver_row(d["level"], d["result"], t=mtime(p)))
    if rows:
        write("m5c-search", rows)


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
    return row("m5c-search", level, name=label, t=t, normal_attempts=1, practice_attempts=res["evals"],
               normal_clears=int(res["verified"]), best_progress=1.0 if res["verified"] else 0.0,
               first_clear_attempt=1 if res["verified"] else None, practice_clear=True)


if __name__ == "__main__":
    for step in (m4, m5, m5b, m5c):
        step()
    from gdbot.attempts import read, summarize
    s = summarize(read())
    print(f"{len(s)} levels; normal {sum(x['normal_attempts'] for x in s)}, practice {sum(x['practice_attempts'] for x in s)}")
